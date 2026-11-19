# animalcam

Watch YouTube wildlife cams, identify wildlife with **GPT-6 Luna**, and browse a private image journal. Birds count too.

One Docker container serves the dashboard and runs checks every 15 minutes. **All images and the SQLite database live in a local directory you mount at `/data`.** There is no cloud storage or separate database service.

## Run

```bash
# Skip this copy if .env is already configured.
cp -n .env.example .env
# Set OPENAI_API_KEY in .env.
mkdir -p data
cp -n cams.toml data/cams.toml
docker build -t animalcam .
docker run -d --name animalcam --init --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  --env-file .env \
  -p 127.0.0.1:8080:8080 \
  -v "$PWD/data:/data" \
  animalcam
```

Open **http://localhost:8080**. The first scheduled check starts immediately. **Check now** runs the selected camera, or every camera when “All cameras” is selected. Results appear without reloading the page. Capturing and analyzing a stream can take a couple of minutes; other gallery controls remain usable.

Or use Compose after creating `.env` and `data` as above:

```bash
ANIMALCAM_UID=$(id -u) ANIMALCAM_GID=$(id -g) docker compose up -d --build
docker compose logs -f
```

The dashboard is bound to localhost by default. For a remote box, an SSH tunnel gives it a local URL:

```bash
ssh -L 8080:127.0.0.1:8080 your-host
```

To expose it through your own HTTPS reverse proxy, set `DASHBOARD_PASSWORD` and optionally `DASHBOARD_USER` in `.env`; recreate the container. Authentication protects the page, API, manual runs, and images. The proxy should preserve the original Host and pass the HTTPS scheme. Use a **single web process**; its background worker already handles scheduling.

## Add cameras

Edit **`data/cams.toml`**, adding another block:

```toml
[[cam]]
id = "another-waterhole"
name = "Another waterhole"
url = "https://www.youtube.com/watch?v=VIDEO_ID"
timezone = "Africa/Windhoek"
```

Use a unique ID for each stream. The file is reloaded for every run and dashboard poll; no image rebuild or restart is needed. If `/data/cams.toml` is absent, the app uses the copy baked into the image. Removing a camera stops future checks; its existing observations remain in the journal.

## Saved data

```text
data/
  cams.toml
  animalcam.db
  animalcam.db-wal / animalcam.db-shm   # SQLite may create these while running
  frames/<cam_id>/<UTC timestamp>-<unique suffix>.jpg
```

| Field | Meaning |
| --- | --- |
| `id` | Unique check ID |
| `checked_at_utc` | UTC timestamp, recorded after capture, before analysis |
| `cam_id`, `cam_name`, `url`, `timezone` | Camera identity and source stream URL |
| `status` | `ok`, `offline`, or `error` |
| `frame_path` | Original JPEG, relative to `/data`; null when unavailable/expired |
| `interesting`, `interesting_score` | Searchable copies of the model's classification |
| `result_json` | Complete validated model observation, shown as `result` in the API |
| `alerted`, `error`, `model` | Notification outcome, any error, model ID |

The model returns this structured JSON (the example is illustrative):

```json
{
  "animals": [{
    "species": "ostrich",
    "group": "bird",
    "count": 3,
    "confidence": 0.94,
    "behaviors": ["drinking"],
    "notes": "Three birds beside the pool"
  }],
  "scene": "Three ostriches at the waterhole.",
  "interesting": true,
  "interesting_score": 8,
  "interesting_reason": "New ostriches since the previous check.",
  "events": ["New bird sighting"],
  "local_time_from_overlay": null
}
```

Animal groups are `bird`, `mammal`, `reptile`, `amphibian`, `fish`, `invertebrate`, or `unknown`. Uncertain identifications should say “unidentified bird” etc. with low confidence. A single still cannot establish movement, so the prompt asks the model to qualify inferred events. Empty scenes use `animals: []`.

The previous successful observation for each camera is included in the next prompt to assess novelty. Timestamp and URL come from the application, rather than being guessed by the model. The camera overlay timestamp is separate and is not treated as authoritative.

The gallery filters by camera, species, UTC date range, status, interesting sightings, animals present, and birds. Click a check to view its full image, species counts, confidence, behaviors, events, and saved JSON. Gallery times use the camera's timezone. **All images are kept by default**, including empty scenes. Set `ANIMALCAM_RETENTION_DAYS=7` to remove empty, unalerted images older than a week while keeping their database records. Animal sightings, alerted frames, and frames whose analysis failed are retained.

Back up the mounted directory. For a live database snapshot, use SQLite's `.backup` command or Python's `sqlite3.Connection.backup()`; stop the container before copying the directory as ordinary files.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | required | OpenAI API credential |
| `ANIMALCAM_MODEL` | `gpt-6-luna` | Vision model; Responses API and strict JSON Schema |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for a Responses-compatible endpoint |
| `ANIMALCAM_INTERVAL_MIN` | `15` | Automatic check interval, minimum 10 minutes |
| `ANIMALCAM_SCHEDULE_ENABLED` | `1` | Set `0` for manual checks only |
| `ANIMALCAM_RUN_ON_START` | `1` | Run immediately at startup when scheduling is enabled |
| `ANIMALCAM_RETENTION_DAYS` | `0` | Empty-frame retention; `0` keeps everything |
| `ANIMALCAM_ALERT_THRESHOLD` | `6` | Minimum interesting score for alerts |
| `ANIMALCAM_COOLDOWN_MIN` | `60` | Per-camera cooldown; a changed confident species set bypasses it |
| `ALERT_BACKEND` | `none` | `none`, `ntfy`, or `discord` |
| `NTFY_TOPIC`, `NTFY_TOKEN`, `NTFY_URL` | — | ntfy destination, optional token, optional server (default `https://ntfy.sh`) |
| `WEBHOOK_URL` | — | Discord webhook when that backend is selected |
| `DASHBOARD_PASSWORD`, `DASHBOARD_USER` | unset / `animalcam` | Optional HTTP Basic authentication |
| `YTDLP_COOKIES` | unset | Optional Netscape-format cookies file inside the container |
| `STATE_DIR` | `/data` in Docker; `./data` locally | Persistent files |
| `CAMS_FILE` | `/data/cams.toml` if present | Explicit config path override |

Alerts are off until you choose a destination. For ntfy, set `ALERT_BACKEND=ntfy` and a long random `NTFY_TOPIC`. For Discord, set `ALERT_BACKEND=discord` and `WEBHOOK_URL`. Sends include the JPEG, species/counts, reason, camera local time, and stream link. A sighting must be marked interesting, meet the score threshold, and contain at least one animal with confidence ≥0.5. Failed sends preserve the observation, do not start the cooldown, and appear as an error on the check. There is no automatic resend queue.

Automatic runs align to interval boundaries in UTC after the initial run. Manual checks share the same worker and file lock, so checks cannot overlap on the same data volume. Requests are rejected as busy while a run is queued or active. Manual checks can run between scheduled captures.

## Other modes

```bash
# Capture/analyze once, persist result, then exit.
docker run --rm --user "$(id -u):$(id -g)" --env-file .env \
  -v "$PWD/data:/data" animalcam run-once

# Real capture + model response, no persistent writes and no alerts.
docker run --rm --env-file .env -v "$PWD/data:/data" \
  animalcam run-once --cam namib-waterhole --dry-run

# Analyze an existing JPEG instead of capturing a stream.
docker run --rm --user "$(id -u):$(id -g)" --env-file .env \
  -v "$PWD/data:/data" animalcam run-once --cam namib-waterhole \
  --frame /data/example.jpg --dry-run

# Background checks without the dashboard.
docker run --rm --user "$(id -u):$(id -g)" --env-file .env \
  -v "$PWD/data:/data" animalcam loop
```

`run-once` returns a nonzero exit code for capture/analysis errors and zero for a successful run or offline cameras. Failures are handled independently per camera. Logs go to stdout/stderr (`docker logs -f animalcam`); results/errors also go into SQLite. Dry runs print JSON to stdout and logs to stderr. They use temporary storage and can read prior context from an existing database without writing new checks/images there.

## Local development

Python 3.12+, `uv`, ffmpeg, and a supported JavaScript runtime (Deno recommended; included in Docker):

```bash
uv sync
uv run python -m animalcam serve --host 127.0.0.1
uv run python -m animalcam --cam namib-waterhole --dry-run
uv run pytest
```

Docker resolves dependencies from `pyproject.toml` when built. To lock a deployment after an online local install, commit the generated `uv.lock` and copy it into Docker before using `uv sync --frozen --no-dev`. A lockfile could not be generated in the restricted development environment.

## YouTube maintenance

Each check resolves a fresh signed stream URL; no cached URLs or static YouTube thumbnails are used. Originals stay full resolution; the model receives a JPEG at most 1280 pixels wide. Night checks continue. Deno and yt-dlp's default challenge-solver dependency are included in the image.

YouTube may reject requests from some cloud IPs. A home capture succeeded during initial spec testing; cloud capture must be tested on the chosen host. If necessary, mount cookies at `/data/cookies.txt` and set `YTDLP_COOKIES=/data/cookies.txt`. Cookies are not guaranteed to fix every rejection. See [yt-dlp YouTube notes](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube) and [JavaScript runtime setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

The installed yt-dlp version is logged at startup. To pick up updates:

```bash
docker compose build --pull --no-cache
docker compose up -d --force-recreate
# If using a local uv lock:
uv lock --upgrade-package yt-dlp
```

The image uses architecture-independent Python code and multiarch base images, with no fixed platform setting. It is intended for amd64 and arm64. Container builds and live services still need verification on the deployment host. Keep use personal and low frequency; the default dashboard is local/private.
