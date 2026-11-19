import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Cam:
    id: str
    name: str
    url: str
    timezone: str = "UTC"


@dataclass
class Settings:
    state_dir: Path
    cams_path: Path
    api_key: str
    model: str
    base_url: str
    interval: float
    threshold: int
    cooldown: float
    retention_days: int
    backend: str
    password: str
    user: str
    schedule_enabled: bool
    run_on_start: bool

    @classmethod
    def load(cls):
        load_dotenv()
        state = Path(os.getenv("STATE_DIR", "data")).resolve()
        fallback = Path(__file__).resolve().parent.parent / "cams.toml"
        cams_path = Path(os.getenv("CAMS_FILE", str(state / "cams.toml" if (state / "cams.toml").exists() else fallback)))
        s = cls(
            state, cams_path, os.getenv("OPENAI_API_KEY", ""),
            os.getenv("ANIMALCAM_MODEL", "gpt-6-luna"),
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            float(os.getenv("ANIMALCAM_INTERVAL_MIN", "15")),
            int(os.getenv("ANIMALCAM_ALERT_THRESHOLD", "6")),
            float(os.getenv("ANIMALCAM_COOLDOWN_MIN", "60")),
            int(os.getenv("ANIMALCAM_RETENTION_DAYS", "0")),
            os.getenv("ALERT_BACKEND", "none"), os.getenv("DASHBOARD_PASSWORD", ""),
            os.getenv("DASHBOARD_USER", "animalcam"),
            os.getenv("ANIMALCAM_SCHEDULE_ENABLED", "1") == "1",
            os.getenv("ANIMALCAM_RUN_ON_START", "1") == "1",
        )
        if s.interval < 10 or not 0 <= s.threshold <= 10 or s.cooldown < 0 or s.retention_days < 0:
            raise ValueError("Interval must be >=10 min, threshold 0–10, cooldown/retention >=0")
        if s.backend not in {"none", "ntfy", "discord"}:
            raise ValueError("ALERT_BACKEND must be none, ntfy, or discord")
        return s

    def cams(self):
        with self.cams_path.open("rb") as f:
            entries = tomllib.load(f).get("cam", [])
        cams = [Cam(**entry) for entry in entries]
        ids = [c.id for c in cams]
        if not cams or len(ids) != len(set(ids)):
            raise ValueError("cams.toml needs at least one cam, with unique IDs")
        for cam in cams:
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", cam.id):
                raise ValueError("Cam IDs must contain only letters, digits, hyphens, or underscores")
            if not cam.url.startswith("https://"):
                raise ValueError("Cam URLs must use https://")
            ZoneInfo(cam.timezone)
        return cams
