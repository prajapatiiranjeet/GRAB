from __future__ import annotations
import asyncio, base64, ipaddress, logging, mimetypes, os, socket, tempfile, time, uuid, shutil, re, html, unicodedata, subprocess, json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

ROOT=Path(__file__).parent
STATIC=ROOT/'static'
TMP=Path(tempfile.gettempdir())/'grab-downloads'; TMP.mkdir(exist_ok=True)
logger=logging.getLogger(__name__)
JOBS: dict[str,dict[str,Any]]={}; LIMIT=int(os.getenv('MAX_PLAYLIST_ITEMS','50')); MAX_MB=int(os.getenv('MAX_FILE_MB','500'))
EXPIRED_JOBS:set[str]=set()
ACTIVE_STREAM_JOBS:dict[str,int]={}
JOB_TTL_MIN=max(1,int(os.getenv('JOB_TTL_MIN','15')))
slots=asyncio.Semaphore(int(os.getenv('MAX_CONCURRENT_JOBS','2')))
ITEM_LIMIT=max(1,int(os.getenv('MAX_CONCURRENT_ITEMS','3')))
hits: dict[str,list[float]]={}

class Link(BaseModel): url:str
class Download(Link):
    urls:list[str]|None=None; titles:list[str]|None=None; thumbnails:list[str|None]|None=None; source_title:str|None=None
    format:str='mp4'; quality:str='best'; audio:bool=False; bitrate:str='192'; selected:list[str]|None=None

def friendly(err: Exception) -> tuple[str,int]:
    s=str(err).lower()
    if any(x in s for x in ('ffmpeg not found','ffmpeg is not installed','ffmpeg binary not found','ffmpeg-location')):
        return 'FFmpeg is missing. Install FFmpeg or run Grab in Docker, then restart the server.',500
    if any(x in s for x in ('winerror 10013','forbidden by its access permissions','network is unreachable','network is down','unable to download api page')):
        return 'The server cannot reach YouTube right now. Check outbound network access and try again.',502
    if any(x in s for x in ('temporary failure in name resolution','name or service not known','getaddrinfo failed','no address associated with hostname')):
        return 'The server could not resolve the media site. Check its DNS and try again.',502
    if 'impersonation' in s and ('no targets available' in s or 'none of these impersonate targets are available' in s or 'curl_cffi' in s):
        return 'This site needs yt-dlp browser-impersonation support. Update requirements and restart Grab.',500
    if any(x in s for x in ('failed to extract any player response','nsig extraction failed','sign in to confirm you\'re not a bot','confirm you\'re not a bot')):
        return 'The platform is blocking the server right now. Try again later; cookies may help.',429
    if any(x in s for x in ('unable to download webpage','urlopen error','connection reset','remote end closed connection','connection refused','connection timed out')):
        return 'Could not reach the media site. Check the server connection and try again.',502
    if 'unable to download video data' in s and ('403' in s or 'forbidden' in s):
        return 'YouTube refused the media stream (HTTP 403). Try a lower resolution or retry later; cookies may help.',403
    if any(x in s for x in ('unsupported url','no suitable extractor')): return "This site isn't supported.",400
    if any(x in s for x in ('private','login required','members-only','sign in to confirm your age')): return 'This content is private or needs a login. Only public content can be downloaded.',403
    if 'age' in s and 'restrict' in s: return 'This age-restricted content needs sign-in and cannot be fetched.',403
    if any(x in s for x in ('geo restrict','not available in your country')): return 'Not available in this server’s region.',403
    if any(x in s for x in ('live event will begin','premiere','is a live stream')): return 'Live streams can’t be downloaded until they end.',400
    if 'mp4 compatibility conversion failed' in s: return 'Grab could not convert this video to a widely compatible MP4. Try a lower resolution or MKV.',500
    if any(x in s for x in ('429','403','bot','too many requests','http error 5')): return 'The platform is blocking the server right now. Try again later; cookies may help.',429
    if any(x in s for x in ('unavailable','removed','deleted')): return 'This video was removed or is unavailable.',404
    if 'timed out' in s or 'timeout' in s: return 'The request timed out. Try again.',504
    if 'file too large' in s: return 'This file exceeds the configured size limit.',413
    if 'ffmpeg' in s or 'postprocessing' in s: return 'The media conversion failed. Try another format.',500
    return 'Could not process this link. Check it and try again.',400

GENERIC_ERROR="Could not process this link. Check it and try again."
ANSI_ESCAPE_RE=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
def parse_progress_percent(value:Any)->float:
    clean=ANSI_ESCAPE_RE.sub('',str(value)).replace('%','').strip()
    match=re.search(r'-?\d+(?:\.\d+)?',clean)
    if not match: return 0.0
    return max(0.0,min(100.0,float(match.group(0))))

def safe_error_detail(err:Exception)->str:
    """Add a useful unexpected-error hint while never returning a full URL."""
    detail=re.sub(r'https?://[^\s\]>)]+','[link]',str(err))
    detail=re.sub(r'(?i)\b(cookie|authorization|token|password)\b\s*[:=]\s*[^\s,;]+',r'\1=[redacted]',detail)
    detail=' '.join(detail.split())
    return f'{type(err).__name__}: {detail[:180]}'

def error_message(err:Exception)->tuple[str,int]:
    message,status=friendly(err)
    if message==GENERIC_ERROR:
        message=f'Could not process this link ({safe_error_detail(err)}).'
    return message,status

def bundled_ffmpeg() -> str | None:
    """Use system FFmpeg when available, with a Windows-only bundled fallback."""
    if shutil.which('ffmpeg'):
        return None
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None

def thumbnail_url(info:dict[str,Any]) -> str | None:
    """Pick an extractor-provided thumbnail, including formats with only a thumbnails list."""
    direct=info.get('thumbnail')
    if isinstance(direct,str) and direct.strip(): return direct
    thumbnails=info.get('thumbnails') or []
    candidates=[item for item in thumbnails if isinstance(item,dict) and isinstance(item.get('url'),str) and item['url'].strip()]
    if not candidates: return None
    def resolution(item):
        try: return int(item.get('width') or 0)*int(item.get('height') or 0)
        except (TypeError,ValueError): return 0
    return max(candidates,key=resolution)['url']

def playlist_entry(entry:dict[str,Any],index:int,source_url:str,is_youtube:bool)->dict[str,Any]:
    identifier=entry.get('id')
    thumbnail=thumbnail_url(entry)
    if not thumbnail and is_youtube and identifier:
        thumbnail=f'https://i.ytimg.com/vi/{quote(str(identifier),safe="")}/mqdefault.jpg'
    return {
        'index':index+1,
        'id':identifier,
        'title':entry.get('title') or 'Untitled',
        'duration':entry.get('duration'),
        'thumbnail':thumbnail,
        'url':entry.get('url') or entry.get('webpage_url') or source_url,
    }

def validate_url(raw:str)->str:
    try:
        p=urlparse(raw.strip())
        if p.scheme not in ('http','https') or not p.hostname: raise ValueError()
        infos=socket.getaddrinfo(p.hostname,None)
        for info in infos:
            addr=ipaddress.ip_address(info[4][0].split('%')[0])
            if not addr.is_global: raise ValueError()
        return raw.strip()
    except Exception: raise HTTPException(400,"That doesn't look like a valid link.")

def rate(request:Request, kind:str):
    ip=request.client.host if request.client else 'unknown'; now=time.time(); key=f'{ip}:{kind}'
    window=60 if kind=='info' else 600
    vals=[t for t in hits.get(key,[]) if now-t < window]
    cap=(int(os.getenv('INFO_REQUESTS_PER_MIN','10')) if kind=='info' else
         int(os.getenv('DOWNLOAD_JOBS_PER_10_MIN','3')) if kind=='download' else
         int(os.getenv('SAVE_REQUESTS_PER_10_MIN','240')))
    if len(vals)>=cap:
        retry_after=max(1,int(window-(now-min(vals))+0.999))
        raise HTTPException(429,'Too many requests. Please wait before trying again.',headers={'Retry-After':str(retry_after)})
    vals.append(now); hits[key]=vals

def opts(extra=None):
    o={'quiet':True,'no_warnings':True,'socket_timeout':25,'noplaylist':False,'extract_flat':'in_playlist','ignoreerrors':False}
    ffmpeg=bundled_ffmpeg()
    if ffmpeg:
        o['ffmpeg_location']=ffmpeg
    cb=os.getenv('COOKIES_B64')
    if cb:
        cp=TMP/'cookies.txt'; cp.write_bytes(base64.b64decode(cb)); o['cookiefile']=str(cp)
    if extra:o.update(extra)
    return o

@asynccontextmanager
async def lifespan(app):
    task=asyncio.create_task(cleaner()); yield; task.cancel()
async def cleaner():
    while True:
        now=time.time(); cutoff=now-JOB_TTL_MIN*60
        for jid,j in list(JOBS.items()):
            if j.get('status') in ('done','failed') and not ACTIVE_STREAM_JOBS.get(jid) and j.get('last_activity',j.get('finished',j.get('created',now)))<cutoff:
                shutil.rmtree(TMP/jid,ignore_errors=True)
                JOBS.pop(jid,None)
                EXPIRED_JOBS.add(jid)
        for p in TMP.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime<cutoff:
                    p.unlink(missing_ok=True)
                elif p.is_dir() and p.name not in JOBS and p.stat().st_mtime<cutoff:
                    shutil.rmtree(p,ignore_errors=True)
            except OSError: pass
        await asyncio.sleep(60)
app=FastAPI(lifespan=lifespan)

def signature_text()->str:
    return os.getenv('SIGNATURE_TEXT','Made with love by Ranjeet Prajapati')

def error_page(status:int,message:str)->str:
    signature=signature_text()
    footer=f'<footer><b>GRAB / REV 2.0 · ©</b>{f"<p>{html.escape(signature)}</p>" if signature else ''}</footer>'
    return f'<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{status} · Grab</title><style>*{{box-sizing:border-box;border-radius:0!important}}body{{margin:0;padding:8vw;background:#f4f0e7;color:#191916;font:700 14px ui-monospace,monospace}}main{{max-width:760px;margin:auto}}h1{{font:900 clamp(4rem,18vw,10rem)/.85 system-ui,sans-serif;letter-spacing:-.06em;margin:2rem 0}}p{{line-height:1.6}}footer{{border-top:3px solid;padding-top:12px;margin-top:40px;font-size:11px;letter-spacing:.07em}}</style><main><small>GRAB / REQUEST STATUS</small><h1>{status}</h1><p>{html.escape(message)}</p>{footer}</main></html>'

@app.exception_handler(HTTPException)
async def http_error(req, exc):
    if req.url.path.startswith('/api/'): return JSONResponse({'error':exc.detail},status_code=exc.status_code,headers=exc.headers)
    return Response(error_page(exc.status_code,str(exc.detail)),status_code=exc.status_code,media_type='text/html')
@app.exception_handler(405)
async def method_error(req,exc): return JSONResponse({'error':'That action is not available.'},405) if req.url.path.startswith('/api/') else Response('METHOD NOT ALLOWED',405)
@app.exception_handler(422)
async def validation_error(req,exc): return JSONResponse({'error':'Check the submitted information and try again.'},422) if req.url.path.startswith('/api/') else Response('CHECK THE SUBMITTED INFORMATION',422)
@app.exception_handler(Exception)
async def server_error(req,exc): return JSONResponse({'error':'Something went wrong. Try again.'},500) if req.url.path.startswith('/api/') else Response(error_page(500,'Something went wrong. Try again.'),500,media_type='text/html')

@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/api/config')
def config(): return {'signature':signature_text()}
@app.get('/robots.txt')
def robots(): return Response('User-agent: *\nAllow: /\nDisallow: /api/\n',media_type='text/plain')
@app.get('/api/info')
async def info_get(): raise HTTPException(405,'Use POST to fetch link information.')
@app.post('/api/info')
async def info(data:Link,request:Request):
    rate(request,'info'); url=validate_url(data.url)
    try:
        result=await asyncio.wait_for(asyncio.to_thread(lambda: YoutubeDL(opts({'extract_flat':'in_playlist'})).extract_info(url,download=False)),timeout=35)
    except Exception as e:
        msg,code=error_message(e); raise HTTPException(code,msg)
    if not result: raise HTTPException(404,'This video was removed or is unavailable.')
    entries=result.get('entries')
    if entries is not None:
        entries=[e for e in entries if e][:LIMIT]
        if not entries: raise HTTPException(404,'This playlist is empty or private.')
        host=(urlparse(url).hostname or '').lower().removeprefix('www.')
        is_youtube=host=='youtu.be' or host=='youtube.com' or host.endswith('.youtube.com')
        return {'type':'playlist','title':result.get('title') or 'Playlist','uploader':result.get('uploader'),'entries':[playlist_entry(e,i,url,is_youtube) for i,e in enumerate(entries)],'truncated':len(entries)>=LIMIT}
    return {'type':'video','title':result.get('title') or 'Video','uploader':result.get('uploader'),'duration':result.get('duration'),'thumbnail':thumbnail_url(result),'formats':[{'height':f.get('height'),'ext':f.get('ext')} for f in result.get('formats',[]) if f.get('height')]}

def item_output_dir(root:Path,jid:str,idx:int)->Path:
    return root/jid/f'item-{idx+1:02d}'

ILLEGAL_NAME_RE=re.compile(r'[\\/:*?"<>|]')
CONTROL_RE=re.compile(r'[\x00-\x1f\x7f]')
RESERVED_NAMES={'CON','PRN','AUX','NUL','CONIN$','CONOUT$',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}

def safe_media_name(value:str)->str:
    name=str(value or 'download.bin').replace('\\','/').split('/')[-1]
    suffix=Path(name).suffix
    stem=name[:-len(suffix)] if suffix else name
    stem=CONTROL_RE.sub('',stem)
    stem=ILLEGAL_NAME_RE.sub('',stem)
    stem=' '.join(stem.split()).strip(' .') or 'download'
    if stem.upper() in RESERVED_NAMES: stem='download'
    stem=stem[:160].rstrip(' .') or 'download'
    return f'{stem}{suffix[:16]}'

def content_disposition(filename:str)->str:
    filename=safe_media_name(filename)
    suffix=Path(filename).suffix
    stem=filename[:-len(suffix)] if suffix else filename
    ascii_stem=unicodedata.normalize('NFKD',stem).encode('ascii','ignore').decode('ascii')
    ascii_stem=''.join(ch if 32<=ord(ch)<127 and ch not in '"\\;' else '_' for ch in ascii_stem).strip(' .') or 'download'
    ascii_suffix=unicodedata.normalize('NFKD',suffix).encode('ascii','ignore').decode('ascii')
    fallback=ascii_stem+ascii_suffix
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename,safe='')}"

def prepare_signature(path:Path)->None:
    """Try to add a comment tag by stream-copying; unsupported formats stay untouched."""
    signature=signature_text()
    if not signature: return
    ffmpeg=bundled_ffmpeg() or shutil.which('ffmpeg')
    if not ffmpeg: return
    temp=path.with_name(f'{path.stem}.signature-tmp{path.suffix}')
    try:
        result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(path),'-map','0','-c','copy','-metadata',f'comment={signature}',str(temp)],capture_output=True,timeout=90)
        if result.returncode==0 and temp.is_file() and temp.stat().st_size:
            temp.replace(path)
    except (OSError,subprocess.SubprocessError):
        pass
    finally:
        temp.unlink(missing_ok=True)

def make_mp4_playable(path:Path)->None:
    """Preserve H.264/AAC streams; transcode only streams that common players reject."""
    ffmpeg=bundled_ffmpeg() or shutil.which('ffmpeg')
    if not ffmpeg: raise RuntimeError('FFmpeg is required to check MP4 compatibility.')
    probe=shutil.which('ffprobe')
    try:
        if probe:
            result=subprocess.run([probe,'-v','error','-show_entries','stream=codec_type,codec_name,pix_fmt','-of','json',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            if result.returncode: raise RuntimeError('Could not inspect the downloaded MP4 streams.')
            streams=json.loads(result.stdout).get('streams',[])
            video=next((stream for stream in streams if stream.get('codec_type')=='video'),{})
            audio_codecs=[stream.get('codec_name') for stream in streams if stream.get('codec_type')=='audio']
            video_codec=video.get('codec_name'); pixel_format=video.get('pix_fmt')
        else:
            result=subprocess.run([ffmpeg,'-hide_banner','-i',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            output=result.stderr+result.stdout
            video_line=next((line for line in output.splitlines() if re.search(r'\bVideo:',line)), '')
            audio_lines=[line for line in output.splitlines() if re.search(r'\bAudio:',line)]
            video_match=re.search(r'\bVideo:\s*([a-zA-Z0-9_]+)',video_line)
            pixel_match=re.search(r',\s*(yuv[a-zA-Z0-9]+|gbr[a-zA-Z0-9]*)',video_line)
            video_codec=video_match.group(1).lower() if video_match else None
            audio_codecs=[match.group(1).lower() for line in audio_lines if (match:=re.search(r'\bAudio:\s*([a-zA-Z0-9_]+)',line))]
            pixel_format=pixel_match.group(1).lower() if pixel_match else None
            if 'Input #0' not in output: raise RuntimeError('Could not inspect the downloaded MP4 streams.')
    except (OSError,subprocess.SubprocessError,json.JSONDecodeError) as exc:
        raise RuntimeError(f'Could not inspect MP4 compatibility: {exc}') from exc

    if not video_codec: raise RuntimeError('The downloaded file has no readable video stream.')
    video_ok=video_codec=='h264' and pixel_format in ('yuv420p','yuvj420p')
    audio_ok=all(codec=='aac' for codec in audio_codecs)
    signature=signature_text()
    if video_ok and audio_ok and not signature: return

    temp=path.with_name(f'{path.stem}.compatible-tmp{path.suffix}')
    vcodec='copy' if video_ok else 'libx264'
    acodec='copy' if audio_ok else 'aac'
    args=[ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(path),'-map','0:v:0','-map','0:a?','-map_metadata','0','-c:v',vcodec,'-c:a',acodec]
    if vcodec=='libx264': args.extend(['-preset','veryfast','-crf','22','-pix_fmt','yuv420p'])
    if acodec=='aac': args.extend(['-b:a','192k'])
    args.extend(['-tag:v','avc1','-movflags','+faststart'])
    if signature: args.extend(['-metadata',f'comment={signature}'])
    args.append(str(temp))
    try:
        result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=max(300,int(os.getenv('MP4_CONVERT_TIMEOUT','7200'))))
        if result.returncode or not temp.is_file() or not temp.stat().st_size:
            detail=(result.stderr or 'FFmpeg did not produce a playable MP4.')[-300:]
            raise RuntimeError(f'MP4 compatibility conversion failed: {detail}')
        temp.replace(path)
    except (OSError,subprocess.SubprocessError) as exc:
        raise RuntimeError(f'MP4 compatibility conversion failed: {exc}') from exc
    finally:
        temp.unlink(missing_ok=True)

async def stream_job_file(path:Path,jid:str):
    ACTIVE_STREAM_JOBS[jid]=ACTIVE_STREAM_JOBS.get(jid,0)+1
    try:
        with path.open('rb') as handle:
            while True:
                chunk=await asyncio.to_thread(handle.read,1024*1024)
                if not chunk: break
                job=JOBS.get(jid)
                if job: job['last_activity']=time.time()
                yield chunk
    finally:
        remaining=ACTIVE_STREAM_JOBS.get(jid,1)-1
        if remaining: ACTIVE_STREAM_JOBS[jid]=remaining
        else: ACTIVE_STREAM_JOBS.pop(jid,None)
        job=JOBS.get(jid)
        if job: job['last_activity']=time.time()

def lookup_job(jid:str)->dict[str,Any]:
    if jid not in JOBS:
        if jid in EXPIRED_JOBS: raise HTTPException(410,'Files are gone. Start again.')
        raise HTTPException(404,'Unknown job.')
    return JOBS[jid]

def require_finished(job:dict[str,Any])->None:
    if job.get('status') not in ('done','failed'): raise HTTPException(409,'Job is still running.')

def download_one(url,jid,idx,settings):
    out=item_output_dir(TMP,jid,idx); out.mkdir(parents=True,exist_ok=True); item=JOBS[jid]['items'][idx]; item['status']='downloading'
    def hook(d):
        if d['status']=='downloading':
            item['status']='downloading'; item['progress']=parse_progress_percent(d.get('_percent_str','0')); item['speed']=d.get('_speed_str')
        elif d['status']=='finished': item['status']='converting'
    audio=settings['audio']; fmt=settings['format']; quality=settings['quality']
    if audio: f='bestaudio/best'; post=[{'key':'FFmpegExtractAudio','preferredcodec':fmt,'preferredquality':settings['bitrate'] if fmt=='mp3' else '0'}]
    else:
        height=int(quality[:-1]) if quality.endswith('p') and quality[:-1].isdigit() else None
        limit=f'[height<={height}]' if height else ''
        fallback=f'bestvideo{limit}+bestaudio/best{limit}'
        if fmt=='mp4':
            compatible=f'bestvideo{limit}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/best{limit}[vcodec^=avc1][acodec^=mp4a]'
            f=f'{compatible}/{fallback}'
        else: f=fallback
        post=[{'key':'FFmpegVideoConvertor','preferedformat':fmt}]
    yopts=opts({'outtmpl':str(out/'%(title).120B-%(id)s.%(ext)s'),'format':f,'merge_output_format':fmt,'progress_hooks':[hook],'max_filesize':MAX_MB*1024*1024,'postprocessors':post,'noplaylist':True,'socket_timeout':max(30,int(os.getenv('DOWNLOAD_SOCKET_TIMEOUT','60'))),'retries':10,'fragment_retries':10,'extractor_retries':3})
    try:
        with YoutubeDL(yopts) as ydl: ydl.download([url])
        files=[p for p in out.iterdir() if p.is_file() and p.name!='cookies.txt']
        if not files: raise RuntimeError('No output file')
        p=max(files,key=lambda x:x.stat().st_mtime)
        if not audio and fmt=='mp4': make_mp4_playable(p)
        else: prepare_signature(p)
        item.update(status='done',file=str(p),name=p.name,size=p.stat().st_size,format=p.suffix.lstrip('.').upper(),progress=100)
    except Exception as e:
        item.update(status='failed',reason=error_message(e)[0])

async def run_job(jid,urls,settings):
    job=JOBS.get(jid)
    if not job: return
    try:
        async with slots:
            job['status']='downloading'
            item_slots=asyncio.Semaphore(ITEM_LIMIT)
            async def download_limited(index,url):
                async with item_slots:
                    await asyncio.to_thread(download_one,url,jid,index,settings)
            await asyncio.gather(*(download_limited(i,u) for i,u in enumerate(urls)))
            done=[i for i in job['items'] if i['status']=='done']
            job['status']='done' if done else 'failed'
    except Exception:
        logger.exception('Unexpected error while completing download job %s',jid)
        job['status']='done' if any(i.get('status')=='done' for i in job['items']) else 'failed'
        job['error']='The playlist job stopped unexpectedly. Completed files are still available.'
    finally:
        job['finished']=time.time(); job['last_activity']=job['finished']

@app.post('/api/download')
async def create_download(data:Download,request:Request):
    rate(request,'download')
    source_urls=data.urls or [data.url]
    if len(source_urls)>LIMIT: raise HTTPException(413,f'Only the first {LIMIT} playlist items can be downloaded.')
    chosen=[]
    for index,raw in enumerate(source_urls):
        if data.selected is not None and raw not in data.selected: continue
        chosen.append((validate_url(raw), (data.titles[index] if data.titles and index<len(data.titles) else None), (data.thumbnails[index] if data.thumbnails and index<len(data.thumbnails) else None)))
    if not chosen: raise HTTPException(400,'Select at least one item.')
    urls=[row[0] for row in chosen]
    jid=uuid.uuid4().hex; now=time.time(); JOBS[jid]={'status':'queued','created':now,'last_activity':now,'title':data.source_title or 'Public media','items':[{'status':'queued','progress':0,'title':row[1] or f'Item {i+1:02d}','thumbnail':row[2]} for i,row in enumerate(chosen)]}
    settings={'format':data.format,'quality':data.quality,'audio':data.audio,'bitrate':data.bitrate}
    EXPIRED_JOBS.discard(jid)
    asyncio.create_task(run_job(jid,urls,settings)); return {'job_id':jid}
@app.get('/api/jobs/{jid}')
def job(jid:str):
    found=lookup_job(jid)
    return {**found,'expires_at':found.get('last_activity',time.time())+JOB_TTL_MIN*60,'ttl_min':JOB_TTL_MIN}
@app.get('/api/jobs/{jid}/events')
async def events(jid:str):
    lookup_job(jid)
    async def stream():
        while jid in JOBS:
            yield f"data: {__import__('json').dumps(JOBS[jid])}\n\n"
            if JOBS[jid]['status'] in ('done','failed'): break
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

@app.get('/api/jobs/{jid}/save-check')
def save_check(jid:str,request:Request):
    rate(request,'save'); found=lookup_job(jid); require_finished(found)
    found['last_activity']=time.time()
    return {'ok':True}
@app.get('/api/jobs/{jid}/files/{item_id}')
def job_file(jid:str,item_id:int,request:Request):
    rate(request,'save'); found=lookup_job(jid); require_finished(found)
    if item_id<1 or item_id>len(found['items']): raise HTTPException(404,'Item not found.')
    item=found['items'][item_id-1]
    if item.get('status')!='done': raise HTTPException(404,'This item did not finish downloading.')
    path=Path(item.get('file',''))
    if not path.is_file(): raise HTTPException(410,'This file expired. Start again.')
    found['last_activity']=time.time()
    name=safe_media_name(item.get('name') or path.name)
    return StreamingResponse(stream_job_file(path,jid),media_type='application/octet-stream',headers={'Content-Disposition':content_disposition(name),'Cache-Control':'no-store'})

# Keep legacy links valid for bookmarks created by earlier Grab builds.
@app.get('/api/files/{jid}/{idx}')
def legacy_file(jid:str,idx:int,request:Request): return job_file(jid,idx+1,request)

@app.delete('/api/jobs/{jid}')
def delete_job(jid:str):
    found=lookup_job(jid)
    if found.get('status') not in ('done','failed'): raise HTTPException(409,'Job is still running.')
    if ACTIVE_STREAM_JOBS.get(jid): raise HTTPException(409,'A file is still being saved. Try again.')
    shutil.rmtree(TMP/jid,ignore_errors=True)
    JOBS.pop(jid,None); EXPIRED_JOBS.add(jid)
    return {'deleted':True}

@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith('api/'): return JSONResponse({'error':'Not found.'},404)
    if path in ('favicon.ico','favicon.svg','apple-touch-icon.png'):
        icon=STATIC/path
        if not icon.is_file(): icon=STATIC/'favicon.svg'
        media_type=mimetypes.guess_type(icon.name)[0] or 'application/octet-stream'
        return FileResponse(icon,media_type=media_type)
    f=STATIC/path if path else STATIC/'index.html'
    if f.is_file(): return FileResponse(f)
    if path=='about': return FileResponse(STATIC/'index.html')
    return Response(error_page(404,'Page not found.'),status_code=404,media_type='text/html')
