import fcntl
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx

from . import alert
from .analyze import analyze
from .grab import Offline, grab
from .store import Store, utcnow

log = logging.getLogger("animalcam")


class Busy(Exception):
    pass


def safe_error(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} from external service; check credentials, model access, or service limits"
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
        return "Capture or analysis timed out"
    if isinstance(exc, subprocess.CalledProcessError):
        return "ffmpeg could not capture or resize the frame"
    if isinstance(exc, httpx.RequestError):
        return "External service connection failed"
    if isinstance(exc, (ValueError, RuntimeError, Offline)):
        return str(exc)[:500]
    return f"{type(exc).__name__}: check local configuration and data-directory permissions"


def run_once(settings, cam_id=None, *, dry_run=False, frame=None):
    cams = settings.cams()
    if cam_id:
        cams = [c for c in cams if c.id == cam_id]
        if not cams:
            raise ValueError("Unknown cam ID")
    if frame and len(cams) != 1:
        raise ValueError("Use --cam with --frame when multiple cams are configured")
    if not settings.api_key:
        raise ValueError("Set OPENAI_API_KEY in .env to analyze frames")
    # Dry runs use temporary storage, including their DB and captures.
    with tempfile.TemporaryDirectory(prefix="animalcam-") as temp:
        root = Path(temp) if dry_run else settings.state_dir
        store = Store(root)
        with (root / ".run.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy("A check is already running") from None
            summaries = []
            for cam in cams:
                at = utcnow().isoformat()
                relative = f"frames/{cam.id}/{utcnow().strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:6]}.jpg"
                destination = root / relative
                result, check_id = None, None
                try:
                    if frame:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if frame.suffix.lower() in {".jpg", ".jpeg"}:
                            shutil.copyfile(frame, destination)
                        else:
                            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(frame),
                                            "-frames:v", "1", str(destination)],
                                           capture_output=True, timeout=30, check=True)
                    else:
                        grab(cam, destination)
                    at = utcnow().isoformat()
                    previous = store.latest(cam.id)
                    if dry_run and (settings.state_dir / "animalcam.db").exists():
                        # Read prior context without opening the real DB for writes.
                        import sqlite3
                        from contextlib import closing
                        with closing(sqlite3.connect((settings.state_dir / "animalcam.db").as_uri() + "?mode=ro", uri=True)) as db:
                            row = db.execute("SELECT result_json FROM checks WHERE cam_id=? AND result_json IS NOT NULL ORDER BY id DESC LIMIT 1", (cam.id,)).fetchone()
                            previous = {"result": json.loads(row[0])} if row else None
                    result = analyze(destination, cam, previous["result"] if previous else None, settings)
                    if dry_run:
                        print(json.dumps({"cam_id": cam.id, "timestamp": at, "url": cam.url, "result": result}, indent=2))
                    else:
                        check_id = store.insert(cam, at, "ok", relative, result, model=settings.model)
                        if settings.backend != "none" and alert.should_alert(result, store.latest(cam.id, alerted=True), at, settings):
                            try:
                                alert.send(cam, result, destination, at, settings)
                                store.finish_alert(check_id)
                            except Exception as exc:
                                error = "Alert failed: " + safe_error(exc)
                                store.finish_alert(check_id, error)
                                log.error("%s: %s", cam.id, error)
                    log.info("%s: %s (score %s)", cam.id, result["scene"], result["interesting_score"])
                    summaries.append({"cam_id": cam.id, "status": "ok", "id": check_id})
                except Exception as exc:
                    status = "offline" if isinstance(exc, Offline) else "error"
                    error = safe_error(exc)
                    if not dry_run:
                        check_id = store.insert(cam, at, status, relative if destination.exists() else None,
                                                result, error, settings.model)
                    log.warning("%s: %s: %s", cam.id, status, error)
                    summaries.append({"cam_id": cam.id, "status": status, "error": error, "id": check_id})
            if not dry_run:
                store.prune(settings.retention_days)
            return summaries


class Worker:
    """One worker for both scheduled and on-demand checks; the server stays responsive."""
    def __init__(self, settings):
        self.settings = settings
        self.condition = threading.Condition()
        self.stopping = False
        self.pending = None
        self.state = {"running": False, "queued": False, "cam_id": None, "started_at": None,
                      "last_finished_at": None, "last_run": [], "error": None,
                      "next_run_at": None, "schedule_enabled": settings.schedule_enabled}
        self.thread = threading.Thread(target=self.work, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        self.thread.join(timeout=80)

    def request(self, cam_id=None):
        with self.condition:
            if self.state["running"] or self.state["queued"]:
                raise Busy("A check is already running or queued")
            self.pending = (cam_id,)
            self.state.update(queued=True, cam_id=cam_id)
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            return dict(self.state)

    def work(self):
        from datetime import datetime, timezone
        seconds = self.settings.interval * 60
        next_run = time.time() if self.settings.run_on_start else (time.time() // seconds + 1) * seconds
        while True:
            with self.condition:
                while not self.stopping:
                    self.state["next_run_at"] = datetime.fromtimestamp(next_run, timezone.utc).isoformat() if self.settings.schedule_enabled else None
                    due = self.settings.schedule_enabled and time.time() >= next_run
                    if self.pending or due:
                        cam_id = self.pending[0] if self.pending else None
                        self.pending = None
                        self.state.update(running=True, queued=False, cam_id=cam_id,
                                          started_at=utcnow().isoformat(), error=None)
                        break
                    self.condition.wait(timeout=max(.1, next_run - time.time()) if self.settings.schedule_enabled else None)
                if self.stopping:
                    return
            try:
                results = run_once(self.settings, cam_id)
                with self.condition:
                    self.state["last_run"] = results
                    failures = [r for r in results if r["status"] == "error"]
                    self.state["error"] = f"{len(failures)} camera check(s) failed; see the gallery" if failures else None
            except Exception as exc:
                with self.condition:
                    self.state["error"] = safe_error(exc)
                log.error("Run failed: %s", safe_error(exc))
            finally:
                with self.condition:
                    self.state.update(running=False, last_finished_at=utcnow().isoformat())
                    next_run = (time.time() // seconds + 1) * seconds
                    self.condition.notify_all()
