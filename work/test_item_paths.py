import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from app.main import item_output_dir
with TemporaryDirectory() as d:
    root = Path(d)
    first = item_output_dir(root, 'job-x', 0)
    second = item_output_dir(root, 'job-x', 1)
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / 'clip.mp4').write_bytes(b'first')
    (second / 'clip.mp4').write_bytes(b'second')
    assert (first / 'clip.mp4').read_bytes() != (second / 'clip.mp4').read_bytes()
print('separate playlist outputs OK')
