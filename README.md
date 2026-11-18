# Grab

Grab fetches public videos and audio supported by yt-dlp for personal offline use. It uses a small Preact interface and a FastAPI backend, served as one Docker web service.

## Why this stack

Preact keeps playlist selection and progress updates quick with a small runtime; Vite emits static assets that FastAPI serves from the same container. Python keeps yt-dlp in-process and avoids shelling out with user-provided data. FastAPI provides typed request validation and asynchronous job endpoints with little extra weight. `curl-cffi` provides the browser-impersonation transport needed by extractors for sites that check TLS fingerprints. The app has no external fonts, UI kit, CDN, analytics, or database.

The release build is intentionally not committed; Docker builds it in the Node stage. After `npm run build`, measure compressed assets with `gzip -c app/static/assets/*.js | wc -c` and `gzip -c app/static/assets/*.css | wc -c`.

The Grab identity uses an open-frame G symbol and matching display lockup in `brand/`. The interface defaults to the system colour scheme; use the Theme menu to choose System, Light, or Dark. Manual choices persist in that browser, and System follows OS theme changes without a reload.

## Local run

Requirements: Python 3.12+, Node 22+, and npm. On Windows, the Python environment includes a bundled FFmpeg fallback; on other systems, install ffmpeg or run through Docker.

```sh
npm install
npm run build
python -m venv .venv
# Activate the environment, then:
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. For a single-container local run, use `docker build -t grab .` and `docker run --rm -p 10000:10000 grab`.

## Render deploy

Push this project to a Git repository, create a Render Blueprint from it, and deploy the `render.yaml` web service. Set optional `COOKIES_B64` only through Render's secret environment setting. The service listens on `$PORT` and reports health at `/health`.

Render's free tier has ephemeral disk and limited RAM/CPU. YouTube and Instagram often block datacenter IPs, so some downloads may fail until cookies are added or the app is run locally. yt-dlp extractors change frequently: periodically update the pinned `yt-dlp` version in `requirements.txt`, rebuild, and redeploy.

## Notes

Playlist processing is capped by `MAX_PLAYLIST_ITEMS` (50 by default), active jobs by `MAX_CONCURRENT_JOBS` (2), and simultaneous items within a playlist by `MAX_CONCURRENT_ITEMS` (3). Downloads use a 60-second socket timeout and retry transient read failures. Per-file size is capped by `MAX_FILE_MB` (500), info requests by `INFO_REQUESTS_PER_MIN` (10), and download jobs by `DOWNLOAD_JOBS_PER_10_MIN` (3). Completed files remain downloadable multiple times and are removed 15 minutes after the job finishes. The app is intended for public content and personal offline use; users are responsible for platform terms and copyright. No account or permanent storage is used.
