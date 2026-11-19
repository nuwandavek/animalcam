import os
import subprocess
import sys
from pathlib import Path


class Offline(Exception):
    pass


def grab(cam, destination: Path):
    # Extraction runs in a child so the entire resolution has a hard deadline.
    # The signed stream URL stays in memory and is resolved anew for every capture.
    code = """
import json, os, sys
import yt_dlp
options = {'quiet': True, 'no_warnings': True, 'noplaylist': True,
           'socket_timeout': 20, 'retries': 1, 'extractor_retries': 1}
if os.getenv('YTDLP_COOKIES'):
    options['cookiefile'] = os.environ['YTDLP_COOKIES']
with yt_dlp.YoutubeDL(options) as ydl:
    info = ydl.extract_info(sys.argv[1], download=False)
if not info.get('is_live'):
    print(json.dumps({'live': False}))
else:
    formats = [f for f in info.get('formats', []) if f.get('vcodec') != 'none' and f.get('url')]
    best = max(formats, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0)) if formats else info
    print(json.dumps({'live': True, 'url': best['url'], 'headers': best.get('http_headers', info.get('http_headers', {}))}))
"""
    import json
    resolved = subprocess.run([sys.executable, "-c", code, cam.url], capture_output=True,
                              text=True, timeout=90)
    if resolved.returncode:
        # yt-dlp errors can include signed URLs or cookie details: keep them out of logs.
        message = resolved.stderr.lower()
        if "not currently live" in message or "live event will begin" in message:
            raise Offline("Stream is not currently live")
        hint = "YouTube bot check; try an up-to-date yt-dlp or YTDLP_COOKIES" if "bot" in message else "check stream availability and update yt-dlp"
        raise RuntimeError(f"yt-dlp failed: {hint}")
    info = json.loads(resolved.stdout)
    if not info["live"]:
        raise Offline("Stream is offline or ended")
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = "".join(f"{k}: {v}\r\n" for k, v in info.get("headers", {}).items())
    try:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-rw_timeout", "20000000",
             "-headers", headers, "-i", info["url"], "-frames:v", "1", str(destination)],
            capture_output=True, timeout=60, check=True,
        )
        if not destination.exists() or destination.stat().st_size == 0:
            raise RuntimeError("ffmpeg produced an empty image")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
