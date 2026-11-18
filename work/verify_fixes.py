import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from app.main import item_output_dir, safe_error_detail
with TemporaryDirectory() as d:
    a=item_output_dir(Path(d),'job',0); b=item_output_dir(Path(d),'job',1)
    assert a != b
assert 'example.test' not in safe_error_detail(Exception('bad https://example.test/watch?v=x'))
print('playlist paths and safe diagnostics pass')
