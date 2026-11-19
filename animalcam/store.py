import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def utcnow():
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "animalcam.db"
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY, cam_id TEXT NOT NULL, cam_name TEXT NOT NULL,
                    url TEXT NOT NULL, timezone TEXT NOT NULL, checked_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ok','offline','error')),
                    frame_path TEXT, result_json TEXT, interesting INTEGER NOT NULL DEFAULT 0,
                    interesting_score INTEGER, alerted INTEGER NOT NULL DEFAULT 0, error TEXT,
                    model TEXT
                );
                CREATE INDEX IF NOT EXISTS checks_cam_time ON checks(cam_id,checked_at_utc DESC);
                CREATE INDEX IF NOT EXISTS checks_time ON checks(checked_at_utc DESC);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def insert(self, cam, at, status, frame=None, result=None, error=None, model=None):
        with self.db() as db:
            cur = db.execute("""INSERT INTO checks
                (cam_id,cam_name,url,timezone,checked_at_utc,status,frame_path,result_json,
                 interesting,interesting_score,error,model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cam.id, cam.name, cam.url, cam.timezone, at, status, frame,
                 json.dumps(result) if result is not None else None,
                 int(result.get("interesting", False)) if result else 0,
                 result.get("interesting_score") if result else None, error, model))
            return cur.lastrowid

    def latest(self, cam_id, alerted=False):
        with self.db() as db:
            row = db.execute("SELECT * FROM checks WHERE cam_id=? AND result_json IS NOT NULL "
                             + ("AND alerted=1 " if alerted else "")
                             + "ORDER BY id DESC LIMIT 1", (cam_id,)).fetchone()
        return self.decode(row) if row else None

    def finish_alert(self, check_id, error=None):
        with self.db() as db:
            db.execute("UPDATE checks SET alerted=?,error=? WHERE id=?", (int(error is None), error, check_id))

    @staticmethod
    def decode(row):
        data = dict(row)
        raw = data.pop("result_json")
        data["result"] = json.loads(raw) if raw else None
        data["interesting"] = bool(data["interesting"])
        data["alerted"] = bool(data["alerted"])
        data["image_url"] = f"/api/checks/{data['id']}/image" if data["frame_path"] else None
        return data

    def list(self, *, cam=None, species=None, group=None, interesting=False, animals=False,
             status=None, date_from=None, date_to=None, limit=48, offset=0):
        where, params = [], []
        for column, value in [("cam_id", cam), ("status", status)]:
            if value:
                where.append(f"{column}=?")
                params.append(value)
        for column, value in [("species", species), ("group", group)]:
            if value:
                where.append("EXISTS (SELECT 1 FROM json_each(result_json,'$.animals') "
                             f"WHERE lower(json_extract(value,'$.{column}'))=lower(?))")
                params.append(value)
        if interesting:
            where.append("interesting=1")
        if animals:
            where.append("json_array_length(result_json,'$.animals')>0")
        if date_from:
            where.append("checked_at_utc>=?")
            params.append(date_from.isoformat() + "T00:00:00")
        if date_to:
            where.append("checked_at_utc<?")
            params.append((date_to + timedelta(days=1)).isoformat() + "T00:00:00")
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.db() as db:
            total = db.execute("SELECT count(*) FROM checks" + clause, params).fetchone()[0]
            rows = db.execute("SELECT * FROM checks" + clause + " ORDER BY id DESC LIMIT ? OFFSET ?",
                              [*params, limit, offset]).fetchall()
        return {"total": total, "checks": [self.decode(row) for row in rows]}

    def get(self, check_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
        return self.decode(row) if row else None

    def species(self):
        with self.db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT json_extract(value,'$.species') AS species "
                    "FROM checks,json_each(result_json,'$.animals') ORDER BY species")]

    def prune(self, days):
        if not days:
            return
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        with self.db() as db:
            rows = db.execute("""SELECT id,frame_path FROM checks WHERE checked_at_utc<?
                AND status='ok' AND alerted=0 AND json_array_length(result_json,'$.animals')=0
                AND frame_path IS NOT NULL""", (cutoff,)).fetchall()
            for row in rows:
                path = (self.root / row["frame_path"]).resolve()
                if path.is_relative_to((self.root / "frames").resolve()):
                    path.unlink(missing_ok=True)
                    db.execute("UPDATE checks SET frame_path=NULL WHERE id=?", (row["id"],))
