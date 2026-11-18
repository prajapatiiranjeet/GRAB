import { h, render } from 'preact';
import { memo } from 'preact/compat';
import { useCallback, useEffect, useState } from 'preact/hooks';
import './style.css';
import { applyTheme, persistThemePreference, readThemePreference, watchSystemTheme } from './theme.js';

const api = async (path, body) => {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed.');
  return data;
};

const ResultRow = memo(function ResultRow({ jobId, item, index, checked, onToggle, onSave }) {
  return <article class="result-row">
    <label class="result-check-wrap"><input class="result-check" type="checkbox" aria-label={`Select ${item.title}`} checked={checked} onChange={event => onToggle(index, event.currentTarget.checked)} /></label>
    <span class="playlist-thumb result-thumb">{item.thumbnail && <img src={item.thumbnail} loading="lazy" alt="" onError={event => event.currentTarget.remove()} />}</span>
    <div class="result-item-meta"><b>{String(index + 1).padStart(2, '0')} / {item.title || item.name}</b><small>{formatBytes(item.size)} · {item.format || 'FILE'}</small></div>
    <button type="button" class="button--plain result-save" onClick={() => onSave(jobId, index + 1)}>SAVE</button>
  </article>;
});

function formatBytes(bytes) {
  if (!Number.isFinite(Number(bytes))) return 'SIZE UNKNOWN';
  const value = Number(bytes);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function clickDownload(url) {
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

const ResultsBlock = memo(function ResultsBlock({ job, offline }) {
  const finished = (job.items || []).map((item, index) => ({ item, index })).filter(row => row.item.status === 'done');
  const failed = (job.items || []).map((item, index) => ({ item, index })).filter(row => row.item.status === 'failed');
  const [selected, setSelected] = useState(() => new Set(finished.map(row => row.index)));
  const [saveProgress, setSaveProgress] = useState('');
  const [saveError, setSaveError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const active = finished.filter(row => selected.has(row.index));
  const toggle = useCallback((index, checked) => {
    setSelected(current => { const next = new Set(current); checked ? next.add(index) : next.delete(index); return next; });
  }, []);

  async function checkSaveLimit() {
    const response = await fetch(`/api/jobs/${job.job_id}/save-check`);
    if (response.ok) return true;
    let message = 'Unable to save this file.';
    try { message = (await response.json()).error || message; } catch { /* non-JSON response */ }
    if (response.status === 429) message += ` Retry in ${response.headers.get('Retry-After') || '60'} seconds.`;
    throw Error(message);
  }

  async function saveOne(jobId, itemId) {
    if (offline) { setSaveError('YOU’RE OFFLINE. CHECK YOUR CONNECTION.'); return; }
    setSaveError('');
    try { await checkSaveLimit(); clickDownload(`/api/jobs/${jobId}/files/${itemId}`); }
    catch (cause) { setSaveError(cause.message); }
  }
  const saveOneStable = useCallback(saveOne, [offline, job.job_id]);

  async function saveSelected() {
    if (offline) { setSaveError('YOU’RE OFFLINE. CHECK YOUR CONNECTION.'); return; }
    setSaveError('');
    for (let i = 0; i < active.length; i += 1) {
      setSaveProgress(`SAVING ${i + 1}/${active.length}`);
      try { await checkSaveLimit(); clickDownload(`/api/jobs/${job.job_id}/files/${active[i].index + 1}`); }
      catch (cause) { setSaveError(cause.message); break; }
      if (i + 1 < active.length) await new Promise(resolve => setTimeout(resolve, 400));
    }
    setSaveProgress('');
  }

  async function deleteFiles() {
    setDeleting(true); setSaveError('');
    try {
      const response = await fetch(`/api/jobs/${job.job_id}`, { method: 'DELETE' });
      const data = await response.json();
      if (!response.ok) throw Error(data.error || 'Could not delete server files.');
      setDeleted(true);
    } catch (cause) { setSaveError(cause.message); }
    finally { setDeleting(false); }
  }

  return <section class="results-panel" aria-label="Download results">
    <div class="results-heading"><small>RESULTS / {finished.length} READY · {failed.length} FAILED</small><h2>YOUR FILES</h2></div>
    {finished.length > 0 && !deleted && <>
      <div class="result-select-bar">
        <b>{active.length}/{finished.length} SELECTED</b>
        <button type="button" class="button--plain" onClick={() => setSelected(new Set(finished.map(row => row.index)))}>SELECT ALL</button>
        <button type="button" class="button--plain" onClick={() => setSelected(new Set())}>CLEAR</button>
      </div>
      <div class="result-list">{finished.map(({ item, index }) => <ResultRow key={index} jobId={job.job_id} item={item} index={index} checked={selected.has(index)} onToggle={toggle} onSave={saveOneStable} />)}</div>
      <p class="save-permission-note">YOUR BROWSER MAY ASK PERMISSION FOR MULTIPLE DOWNLOADS.</p>
      {saveProgress && <p class="save-progress" role="status">{saveProgress}</p>}
      <button type="button" class="button--download" disabled={!active.length || Boolean(saveProgress)} onClick={saveSelected}>SAVE SELECTED</button>
      {!active.length && <p class="selection-hint">SELECT ONE OR MORE FINISHED FILES TO SAVE.</p>}
      {saveError && <p class="message message--error" role="alert">{saveError}</p>}
      <p class="expiry-note">FILES DELETED FROM SERVER IN ~{job.ttl_min || 15} MIN. SAVE NOW.</p>
      <button type="button" class="button--plain delete-server-files" disabled={deleting} onClick={deleteFiles}>{deleting ? 'DELETING…' : 'DONE, DELETE FROM SERVER'}</button>
    </>}
    {deleted && <p class="message message--notice" role="status">FILES DELETED FROM SERVER.</p>}
    {failed.length > 0 && <div class="failed-results"><b>FAILED ITEMS / {failed.length}</b>{failed.map(({ item, index }) => <p key={index}>ITEM {String(index + 1).padStart(2, '0')} · {item.title || 'ITEM'} — {item.reason || 'Download failed.'}</p>)}</div>}
  </section>;
});

function BrandLogo() {
  return (
    <svg class="brand-lockup" viewBox="0 0 640 170" role="img" aria-label="Grab">
      <path class="brand-symbol" d="M36 34h184v48H36zM36 34h48v188H36zM36 174h184v48H36zM172 112h48v110h-48zM132 112h88v40h-88z" transform="translate(4 8) scale(.62)" />
      <g class="brand-wordmark" fill="none" stroke="currentColor" stroke-width="18" stroke-linecap="square" stroke-linejoin="miter">
        <path d="M250 50h-56v90h56v-36h-26" />
        <path d="M280 140V50h52l24 24v12l-24 24h-52m52 0 30 30" />
        <path d="m396 140 52-90 52 90m-83-36h62" />
        <path d="M534 140V52h48l22 22-22 22h-48m48 0 22 22-22 22h-48" />
      </g>
    </svg>
  );
}

function App() {
  const [url, setUrl] = useState('');
  const [info, setInfo] = useState(null);
  const [selected, setSelected] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);
  const [themePreference, setThemePreference] = useState(readThemePreference);
  const [options, setOptions] = useState(() => JSON.parse(localStorage.getItem('grab-options') || '{"format":"mp4","quality":"best","audio":false,"bitrate":"192"}'));
  const [offline, setOffline] = useState(!navigator.onLine);
  const [signature, setSignature] = useState('');

  useEffect(() => {
    applyTheme(themePreference);
    return watchSystemTheme(themePreference, systemDark => applyTheme(themePreference, { systemDark }));
  }, [themePreference]);

  useEffect(() => {
    persistThemePreference(themePreference);
  }, [themePreference]);

  useEffect(() => {
    fetch('/api/config').then(response => response.ok ? response.json() : null).then(config => setSignature(config?.signature || '')).catch(() => {});
  }, []);

  useEffect(() => {
    const onNetworkChange = () => setOffline(!navigator.onLine);
    window.addEventListener('online', onNetworkChange);
    window.addEventListener('offline', onNetworkChange);
    return () => {
      window.removeEventListener('online', onNetworkChange);
      window.removeEventListener('offline', onNetworkChange);
    };
  }, []);

  useEffect(() => {
    try { localStorage.setItem('grab-options', JSON.stringify(options)); } catch { /* Storage can be disabled. */ }
  }, [options]);

  useEffect(() => {
    if (!job?.job_id) return undefined;
    let live = true;
    let timer;
    const poll = async () => {
      try {
        const response = await fetch(`/api/jobs/${job.job_id}`);
        const data = await response.json();
        if (live) {
          setJob(current => ({ ...current, ...data }));
          if (data.status !== 'done' && data.status !== 'failed') timer = setTimeout(poll, 1200);
        }
      } catch {
        if (live) timer = setTimeout(poll, 2000);
      }
    };
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, [job?.job_id, job?.status]);

  function setOption(key, value) {
    setOptions(current => ({ ...current, [key]: value }));
  }

  async function fetchInfo(event) {
    event.preventDefault();
    setError('');
    setInfo(null);
    setBusy(true);
    try {
      const data = await api('/api/info', { url });
      setInfo(data);
      setSelected(data.type === 'playlist' ? data.entries.map(item => item.url) : [url]);
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setError('');
    setBusy(true);
    try {
      const urls = info.type === 'playlist' ? info.entries.map(item => item.url) : [url];
      const titles = info.type === 'playlist' ? info.entries.map(item => item.title) : [info.title];
      const thumbnails = info.type === 'playlist' ? info.entries.map(item => item.thumbnail || null) : [info.thumbnail || null];
      const data = await api('/api/download', {
        url,
        urls,
        titles,
        thumbnails,
        source_title: info.title,
        selected: info.type === 'playlist' ? selected : undefined,
        ...options,
      });
      setJob(data);
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }

  function formatTime(seconds) {
    if (!seconds) return '—';
    return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  }

  return (
    <main>
      <header class="site-header">
        <div class="header-utility">
          <small>PUBLIC MEDIA / TOOL 01</small>
          <div class="theme-control" role="group" aria-label="Color theme">
            <span>THEME</span>
            <div class="theme-options">
              {['system', 'light', 'dark'].map(preference => <button
                type="button"
                class="theme-option"
                aria-pressed={themePreference === preference}
                onClick={() => setThemePreference(preference)}
                key={preference}
              >{preference.toUpperCase()}</button>)}
            </div>
          </div>
        </div>
        <BrandLogo />
        <p class="brand-promise">PASTE A PUBLIC LINK. FETCH THE FILE.</p>
      </header>

      {offline && <aside class="message message--error" role="status">YOU’RE OFFLINE. CHECK YOUR CONNECTION.</aside>}

      <form class="fetch-form" onSubmit={fetchInfo}>
        <label for="url">PASTE LINK</label>
        <div class="link-row">
          <input id="url" type="url" required placeholder="https://…" value={url} onInput={event => setUrl(event.currentTarget.value)} />
          <button disabled={busy}>{busy ? 'FETCHING' : 'FETCH'}</button>
        </div>
      </form>

      {error && <aside class="message message--error" role="alert">{error}</aside>}

      {info && (
        <section class="media-panel" aria-label="Media details">
          <div class="media-meta">
            <div>
              <small>{info.type === 'playlist' ? 'PLAYLIST' : 'MEDIA'} / SOURCE</small>
              <h2>{info.title}</h2>
              <p>{info.uploader || 'UNKNOWN SOURCE'}{info.duration ? ` · ${formatTime(info.duration)}` : ''}</p>
            </div>
            {info.thumbnail && <img src={info.thumbnail} width="96" height="64" loading="lazy" alt="" />}
          </div>

          {info.type === 'playlist' && <>
            <div class="select-bar">
              <b>{selected.length} / {info.entries.length} SELECTED</b>
              <button type="button" class="button--plain" onClick={() => setSelected(info.entries.map(item => item.url))}>SELECT ALL</button>
              <button type="button" class="button--plain" onClick={() => setSelected([])}>CLEAR</button>
            </div>
            {info.truncated && <p class="message message--notice">ONLY THE FIRST 50 ITEMS ARE LOADED.</p>}
            <div class="playlist-list">
              {info.entries.map((item, index) => (
                <label class={`playlist-row ${selected.includes(item.url) ? 'is-selected' : ''}`} key={item.id || index}>
                  <input
                    type="checkbox"
                    checked={selected.includes(item.url)}
                    onChange={event => setSelected(current => event.currentTarget.checked ? [...current, item.url] : current.filter(itemUrl => itemUrl !== item.url))}
                  />
                  <span class="playlist-thumb" role="img" aria-label={item.thumbnail ? `Thumbnail for ${item.title}` : `No thumbnail available for ${item.title}`}>
                    {item.thumbnail && <img src={item.thumbnail} width="72" height="48" loading="lazy" alt="" onError={event => event.currentTarget.remove()} />}
                  </span>
                  <span class="playlist-title">{String(index + 1).padStart(2, '0')} / {item.title}</span>
                  <data>{formatTime(item.duration)}</data>
                </label>
              ))}
            </div>
          </>}

          <div class="download-settings">
            <label><span>MODE</span><select value={options.audio ? 'audio' : 'video'} onChange={event => setOption('audio', event.currentTarget.value === 'audio')}><option value="video">VIDEO</option><option value="audio">AUDIO ONLY</option></select></label>
            {!options.audio && <label><span>QUALITY</span><select value={options.quality} onChange={event => setOption('quality', event.currentTarget.value)}>{['best', '2160p', '1440p', '1080p', '720p', '480p', '360p'].filter(quality => quality === 'best' || info.type !== 'video' || (info.formats || []).some(format => format.height >= parseInt(quality, 10))).map(quality => <option value={quality} key={quality}>{quality === 'best' ? 'BEST AVAILABLE' : quality}</option>)}</select></label>}
            <label><span>FORMAT</span><select value={options.format} onChange={event => setOption('format', event.currentTarget.value)}>{(options.audio ? ['mp3', 'm4a', 'opus', 'wav', 'flac'] : ['mp4', 'webm', 'mkv']).map(format => <option key={format}>{format}</option>)}</select></label>
            {options.audio && options.format === 'mp3' && <label><span>BITRATE</span><select value={options.bitrate} onChange={event => setOption('bitrate', event.currentTarget.value)}>{['320', '192', '128'].map(bitrate => <option key={bitrate}>{bitrate}</option>)}</select></label>}
          </div>
          <button class="button--download" disabled={busy || (info.type === 'playlist' && !selected.length)} onClick={download}>DOWNLOAD{info.type === 'playlist' ? ` ${selected.length} SELECTED` : ''}</button>
        </section>
      )}

      {job && <section class="job-panel" aria-live="polite">
        <small>JOB / {job.status?.toUpperCase()}</small>
        {(job.items || []).map((item, index) => <div class="job-row" key={index}>
          <b>ITEM {String(index + 1).padStart(2, '0')} · {item.status?.toUpperCase()}</b>
          {item.reason && (!['done', 'failed'].includes(job.status) || !(job.items || []).some(row => row.status === 'done')) && <p>{item.reason}</p>}
          {item.status === 'downloading' && <div class="progress-bar"><i style={{ width: `${item.progress || 0}%` }} /></div>}
        </div>)}
      </section>}

      {job && ['done', 'failed'].includes(job.status) && (job.items || []).some(item => item.status === 'done') && <ResultsBlock key={job.job_id} job={job} offline={offline} />}

      <footer class="site-footer">
        <small>GRAB / REV 2.0 · ©</small>
        <p>FOR PERSONAL OFFLINE USE OF PUBLIC CONTENT. RESPECT PLATFORM TERMS AND COPYRIGHT. NOTHING IS STORED PERMANENTLY ON THIS SERVER.</p>
        {signature && <p class="signature-line">{signature}</p>}
      </footer>
    </main>
  );
}

render(<App />, document.getElementById('app'));
