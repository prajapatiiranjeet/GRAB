from pathlib import Path
import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app import main


@pytest.fixture
def save_env(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'TMP', tmp_path)
    main.JOBS.clear()
    main.EXPIRED_JOBS.clear()
    main.hits.clear()
    yield tmp_path
    main.JOBS.clear()
    main.EXPIRED_JOBS.clear()


def ready_job(tmp_path: Path, *, title='My Playlist', items=None):
    files = []
    rows = []
    for index, (name, status) in enumerate(items or [('Song.mp4', 'done')]):
        path = tmp_path / 'job-test' / f'item-{index + 1:02d}' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if status == 'done':
            path.write_bytes(b'example media')
            files.append(path)
        rows.append({'status': status, 'name': name, 'file': str(path), 'size': path.stat().st_size if path.exists() else 0, 'title': Path(name).stem})
    main.JOBS['job-test'] = {'status': 'done', 'title': title, 'created': 1, 'finished': 1, 'last_activity': 1, 'items': rows}
    return rows, files


def request():
    return Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': [], 'query_string': b'', 'scheme': 'http', 'server': ('testserver', 80), 'client': ('127.0.0.1', 10000)})


def status_of(call):
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code


async def collect(stream):
    return b''.join([chunk async for chunk in stream])


def test_media_filename_sanitizes_path_and_unicode():
    name = main.safe_media_name('../../../../CON:bad/../कहानी 🎵.mp4')
    assert name == 'कहानी 🎵.mp4'
    assert '..' not in name and '/' not in name and '\\' not in name


def test_zip_endpoint_is_removed():
    assert not any(route.path.endswith('/zip') for route in main.app.routes)


def test_error_pages_include_configured_footer_signature(monkeypatch):
    monkeypatch.setenv('SIGNATURE_TEXT', 'Made with love by Ranjeet Prajapati')
    assert 'Made with love by Ranjeet Prajapati' in main.error_page(404, 'Page not found.')
    assert 'Made with love by Ranjeet Prajapati' in main.error_page(500, 'Something went wrong.')
    monkeypatch.setenv('SIGNATURE_TEXT', '')
    assert 'Made with love by Ranjeet Prajapati' not in main.error_page(404, 'Page not found.')


def test_delete_job_removes_files_and_marks_it_gone(save_env):
    _, files = ready_job(save_env)
    assert main.delete_job('job-test') == {'deleted': True}
    assert not files[0].exists()
    assert status_of(lambda: main.job_file('job-test', 1, request())) == 410


def test_save_rate_limit_has_retry_after(save_env, monkeypatch):
    ready_job(save_env)
    monkeypatch.setenv('SAVE_REQUESTS_PER_10_MIN', '1')
    monkeypatch.setattr(main.time, 'time', lambda: 1000.0)
    main.hits['127.0.0.1:save'] = [999.0]
    with pytest.raises(HTTPException) as error:
        main.job_file('job-test', 1, request())
    assert error.value.status_code == 429
    assert error.value.headers['Retry-After'] == '599'


def test_file_download_has_utf8_and_ascii_filename(save_env):
    ready_job(save_env, items=[('मेरा 🎵.mp4', 'done')])
    response = main.job_file('job-test', 1, request())
    assert isinstance(response, StreamingResponse)
    disposition = response.headers['content-disposition']
    assert 'filename="download.mp4"' in disposition
    assert "filename*=UTF-8''%E0%A4%AE%E0%A5%87%E0%A4%B0%E0%A4%BE%20%F0%9F%8E%B5.mp4" in disposition
    assert asyncio.run(collect(response.body_iterator)) == b'example media'


@pytest.mark.parametrize(('job_state', 'expected'), [
    ('unknown', 404), ('expired', 410), ('running', 409),
])
def test_job_status_codes(save_env, job_state, expected):
    if job_state == 'expired': main.EXPIRED_JOBS.add('job-test')
    if job_state == 'running': main.JOBS['job-test'] = {'status': 'downloading', 'items': []}
    assert status_of(lambda: main.job_file('job-test', 1, request())) == expected


def test_failed_or_missing_file_has_clear_status(save_env):
    ready_job(save_env, items=[('Song.mp4', 'failed')])
    assert status_of(lambda: main.job_file('job-test', 1, request())) == 404
    assert status_of(lambda: main.job_file('job-test', 9, request())) == 404
    ready_job(save_env)
    Path(main.JOBS['job-test']['items'][0]['file']).unlink()
    assert status_of(lambda: main.job_file('job-test', 1, request())) == 410


def test_signature_metadata_is_stream_copied_without_reencode(tmp_path, monkeypatch):
    media = tmp_path / 'audio.mp3'
    media.write_bytes(b'media')
    calls = []
    monkeypatch.setenv('SIGNATURE_TEXT', 'Made with love')
    monkeypatch.setattr(main, 'bundled_ffmpeg', lambda: 'ffmpeg.exe')
    def fake_run(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b'tagged')
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(main.subprocess, 'run', fake_run)
    main.prepare_signature(media)
    assert media.read_bytes() == b'tagged'
    assert '-c' in calls[0] and calls[0][calls[0].index('-c') + 1] == 'copy'
    assert '-metadata' in calls[0] and 'comment=Made with love' in calls[0]


def test_empty_signature_disables_metadata(monkeypatch, tmp_path):
    media = tmp_path / 'audio.mp3'
    media.write_bytes(b'media')
    monkeypatch.setenv('SIGNATURE_TEXT', '')
    monkeypatch.setattr(main, 'bundled_ffmpeg', lambda: pytest.fail('FFmpeg should not run'))
    main.prepare_signature(media)
    assert media.read_bytes() == b'media'
    assert main.config()['signature'] == ''
