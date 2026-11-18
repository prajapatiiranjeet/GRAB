import pytest
from fastapi import HTTPException
from app.main import validate_url, friendly, safe_error_detail, error_message

def test_rejects_non_http():
    with pytest.raises(HTTPException): validate_url('file:///etc/passwd')

def test_blocks_private_resolution(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',lambda *a:[(None,None,None,None,('127.0.0.1',0))])
    with pytest.raises(HTTPException): validate_url('http://example.test')

def test_error_mapping_private():
    assert friendly(Exception('private video'))[0].startswith('This content is private')

def test_error_mapping_blocked_outbound_network():
    message, status = friendly(Exception('Unable to download API page: [WinError 10013] access forbidden by its access permissions'))
    assert status == 502
    assert 'outbound network access' in message

def test_error_mapping_missing_ffmpeg():
    message, status = friendly(Exception('ffmpeg not found'))
    assert status == 500
    assert 'Install FFmpeg' in message

def test_video_stream_403_explains_lower_quality_retry():
    message, status = friendly(Exception('unable to download video data: HTTP Error 403: Forbidden'))
    assert status == 403
    assert 'lower resolution' in message

def test_missing_impersonation_dependency_is_explained():
    message, status = friendly(Exception('The extractor is attempting impersonation, but none of these impersonate targets are available: firefox'))
    assert status == 500
    assert 'impersonation support' in message

def test_unexpected_error_diagnostic_redacts_urls():
    detail = safe_error_detail(Exception('failed: https://example.test/watch?v=private-id'))
    assert 'example.test' not in detail
    assert '[link]' in detail

def test_unexpected_error_message_is_diagnostic():
    message, _ = error_message(Exception('fragment download failed'))
    assert 'fragment download failed' in message
    assert message != 'Could not process this link. Check it and try again.'
