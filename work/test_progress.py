import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import parse_progress_percent
assert parse_progress_percent(f'{chr(27)}[0;94m100.0{chr(27)}[0m') == 100.0
assert parse_progress_percent(f'{chr(27)}[0;94m100.0{chr(27)}[0m%') == 100.0
print('exact traceback value parses')
