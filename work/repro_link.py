import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yt_dlp
from app.main import validate_url, friendly, opts
url = 'https://youtu.be/IFiBH02S18E'
print('version:', yt_dlp.version.__version__)
print('validated:', validate_url(url))
try:
    info = yt_dlp.YoutubeDL(opts()).extract_info(url, download=False)
    print('title:', info.get('title'))
except Exception as exc:
    print('exception:', type(exc).__name__)
    print('mapped:', friendly(exc))
