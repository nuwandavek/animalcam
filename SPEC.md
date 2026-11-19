# animalcam — implementation spec

## Current scope

One Docker image watches live YouTube wildlife cams and serves a private image dashboard.
Every 15 minutes (configurable, minimum 10), it grabs a real frame and asks GPT-6 Luna
(`gpt-6-luna`) for a structured observation. **Birds and other small wildlife count as animals.**
The dashboard can trigger checks on demand for one selected cam or all cams.

Images stay on local disk. A small SQLite database stores metadata and the full LLM JSON.
Both live in a local directory mounted at `/data`. No S3 or separate database is needed.
Add streams through `/data/cams.toml`; it reloads without rebuilding or restarting.

These choices supersede the original Claude/Anthropic model, optional S3 discussion,
and loop-only container default. Detailed commands and configuration are in README.md.

## Schema

The app records authoritative metadata in one `checks` table:

- `id`, `cam_id`, `cam_name`, source stream `url`, camera `timezone`.
- `checked_at_utc`: UTC timestamp immediately after capture and before analysis.
- `status`: `ok`, `offline`, or `error`.
- `frame_path`: relative original JPEG path, nullable.
- `interesting`: boolean copied from the observation, for filtering.
- `interesting_score`: integer 0–10.
- `result_json`: complete validated observation.
- `alerted`, `error`, `model`: notification state, error details, model ID.

Luna returns strict JSON Schema output through the OpenAI Responses API:

```json
{
  "animals": [{
    "species": "ostrich",
    "group": "bird",
    "count": 3,
    "confidence": 0.94,
    "behaviors": ["drinking"],
    "notes": "Three birds visible beside the pool"
  }],
  "scene": "Three ostriches at the waterhole.",
  "interesting": true,
  "interesting_score": 8,
  "interesting_reason": "New ostriches since the last check.",
  "events": ["New bird sighting"],
  "local_time_from_overlay": null
}
```

Groups: bird, mammal, reptile, amphibian, fish, invertebrate, unknown. Counts are positive
integers; confidence is 0–1. Uncertain species use labels such as “unidentified bird” with
low confidence. Empty scenes have `animals: []`. The app supplies timestamp and URL;
overlay time is separate, nullable, and not authoritative.

The previous successful result for each camera is included for novelty assessment.
Repeated sightings should score low; new species and unusual interactions can score high.
The prompt ignores branding/weather overlays and qualifies behavior inferred from one still.
Invalid/incomplete responses become errors rather than fabricated observations.

## Dashboard

- Paginated image gallery, newest first.
- Filters: camera, species, UTC date range, status, interesting, animals present, birds.
- Detail: original image, camera-local time, species/counts/confidence/behaviors,
  events, reason, source stream, full saved JSON.
- Check now: selected cam or all cams; background processing, progress indication,
  automatic refresh. Repeated requests while busy are rejected.
- Optional password protects the page, API, images, and manual triggers.
- Localhost port binding by default. Remote access can use SSH forwarding or an HTTPS proxy.

## Capture and storage

- Fresh yt-dlp resolution on every check, `is_live` check; no thumbnails.
- Best available video URL; extraction and ffmpeg capture have hard timeouts.
- Full-resolution original retained, max 1280 px wide JPEG sent to the model.
- Capture day and night. Optional `YTDLP_COOKIES`.
- SQLite WAL mode; camera/time indexes. All images kept by default.
- Optional retention deletes only old empty, unalerted images, preserving their metadata.
- Camera failures are independent. Analysis failures retain captured frames;
  alert failures retain successful analysis.
- One worker handles scheduled and manual runs; a file lock prevents a second process
  from overlapping on the same mounted volume. Run one web process per container.

## Container and modes

- `run-once`: one pass, exit. Default Python CLI mode.
- `--cam`, `--dry-run`, `--frame`: capture/prompt testing. Dry runs have no persistent writes or alerts.
- `loop`: checks without the dashboard.
- `serve`: dashboard plus scheduler. Default Docker/Compose mode.
- `/data/cams.toml` overrides the baked-in config.
- Non-root Python 3.12 image with ffmpeg, Deno, and uv-managed dependencies.
- Host UID/GID can be selected to match bind-mount ownership.
- No platform-specific application code; intended for amd64 and arm64.
- Logs to stdout/stderr; per-check errors also in SQLite. yt-dlp version logged at startup.
- Rebuild without cache to update yt-dlp. Add a uv lock from an online environment for frozen installs.

## Alerts

Off by default until configured. Backends: ntfy and Discord. Include image, camera name,
species/counts, reason, local time, and source URL.

Require `interesting=true`, a score at least the configured threshold (default 6), and at
least one animal with confidence >=0.5. Default per-cam cooldown is 60 minutes, bypassed
when the confident species set differs from the last successfully sent alert. Failed sends
do not advance cooldown; they remain visible on the observation. No automatic resend queue.

## Initial capture evidence (2026-11-18)

The original spec recorded a successful home-Mac capture from
https://www.youtube.com/watch?v=ydYDqZQpim8 using yt-dlp default format and ffmpeg.
The 1920×1080 night frame showed an empty, floodlit waterhole. The YouTube channel
thumbnail was a static promo image and must not be used. Constrained
`best[height<=720]` selection failed; use default extraction instead.

Cloud-IP access is unverified. YouTube bot checks can affect cloud hosts; cookies may
help but are not guaranteed. Keep use personal and low frequency, with a private dashboard.

## Verification status

Automated tests cover JSON validation, Luna request formatting, persistence and previous
context, bird/species/date filters, retention, offline isolation, dry runs, alert cooldown
and failure behavior, worker serialization, authentication, cross-origin run rejection,
and image-path containment. ffmpeg resizing was exercised on a synthetic test image.

Still verify on the deployment host: live YouTube capture, a real Luna vision response,
Docker build/run, amd64/arm64 build availability, browser appearance/interactions,
and a real notification once a destination is configured. Development environment
restrictions blocked external API network access, Docker daemon access, and local port binding.
