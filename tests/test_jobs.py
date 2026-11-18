from pathlib import Path
from app.main import item_output_dir, parse_progress_percent

def test_playlist_items_get_separate_output_directories(tmp_path: Path):
    first = item_output_dir(tmp_path, 'job-1', 0)
    second = item_output_dir(tmp_path, 'job-1', 1)
    assert first != second
    assert first == tmp_path / 'job-1' / 'item-01'
    assert second == tmp_path / 'job-1' / 'item-02'

def test_progress_parser_handles_yt_dlp_ansi_coloring():
    assert parse_progress_percent('\x1b[0;94m100.0\x1b[0m%') == 100.0
    assert parse_progress_percent('\x1b[0;94m100.0\x1b[0m') == 100.0
    assert parse_progress_percent('\x1b[0;94m 37.5%\x1b[0m') == 37.5
    assert parse_progress_percent('--%') == 0.0
