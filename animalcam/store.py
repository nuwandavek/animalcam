import json
import random
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
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY, check_id INTEGER, cam_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL, model TEXT NOT NULL, response_id TEXT,
                    status TEXT NOT NULL, input_tokens INTEGER, cached_input_tokens INTEGER,
                    output_tokens INTEGER, reasoning_tokens INTEGER, estimated_cost_usd REAL,
                    cache_write_tokens INTEGER,
                    image_width INTEGER, elapsed_ms INTEGER, source TEXT NOT NULL,
                    usage_json TEXT, rates_json TEXT, service_tier TEXT, error TEXT
                );
                CREATE INDEX IF NOT EXISTS llm_calls_check ON llm_calls(check_id);
                CREATE UNIQUE INDEX IF NOT EXISTS llm_calls_backfill_once ON llm_calls(check_id)
                    WHERE source='backfill';
                CREATE TABLE IF NOT EXISTS species_facts (
                    species TEXT PRIMARY KEY, cam_id TEXT NOT NULL, title TEXT, fact TEXT,
                    source_name TEXT, source_url TEXT, verified_at_utc TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at_utc TEXT, error TEXT
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(llm_calls)")}
            for name, kind in [("cache_write_tokens", "INTEGER"), ("web_search_calls", "INTEGER"), ("tool_cost_usd", "REAL")]:
                if name not in columns:
                    db.execute(f"ALTER TABLE llm_calls ADD COLUMN {name} {kind}")

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
        if not row:
            return None
        data = self.decode(row)
        with self.db() as db:
            data["llm_calls"] = [dict(call) for call in db.execute(
                "SELECT * FROM llm_calls WHERE check_id=? ORDER BY id", (check_id,))]
        data["fact"] = self.fact(data["result"]) if data["result"] else None
        return data

    def record_call(self, cam_id, call, check_id=None):
        columns = ["created_at_utc", "model", "response_id", "status", "input_tokens",
                   "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "estimated_cost_usd",
                   "image_width", "elapsed_ms", "source", "service_tier", "web_search_calls", "tool_cost_usd", "error"]
        with self.db() as db:
            cursor = db.execute("INSERT INTO llm_calls (check_id,cam_id," + ",".join(columns)
                + ",usage_json,rates_json) VALUES (" + ",".join("?" for _ in range(len(columns)+4)) + ")",
                [check_id, cam_id, *(call.get(key) for key in columns),
                 json.dumps(call.get("usage")), json.dumps(call.get("rates"))])
            return cursor.lastrowid

    def link_calls(self, call_ids, check_id):
        with self.db() as db:
            db.executemany("UPDATE llm_calls SET check_id=? WHERE id=?", [(check_id, i) for i in call_ids])

    def cost_summary(self):
        with self.db() as db:
            row = db.execute("""SELECT count(*) AS calls, coalesce(sum(estimated_cost_usd),0) AS total_usd,
                coalesce(sum(CASE WHEN source='backfill' THEN estimated_cost_usd ELSE 0 END),0) AS backfilled_usd,
                sum(CASE WHEN source='backfill' THEN 1 ELSE 0 END) AS backfilled_calls,
                sum(CASE WHEN estimated_cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced_calls
                FROM llm_calls""").fetchone()
        return {key: value or 0 for key, value in dict(row).items()}

    def fact(self, result):
        with self.db() as db:
            for animal in sorted(result["animals"], key=lambda a: a["confidence"], reverse=True):
                if animal["confidence"] < .7:
                    continue
                row = db.execute("SELECT species,title,fact AS text,source_name AS source,source_url AS url,verified_at_utc "
                                 "FROM species_facts WHERE species=? AND status='ready'",
                                 (animal["species"].strip().casefold(),)).fetchone()
                if row:
                    return dict(row)
        return None

    def facts_revision(self):
        with self.db() as db:
            return db.execute("SELECT coalesce(max(verified_at_utc),'') FROM species_facts").fetchone()[0]

    def highlight(self, exclude_id=None):
        """Pick a real wildlife frame, favoring variety, abundance, and model interest."""
        with self.db() as db:
            rows = db.execute("""SELECT * FROM checks WHERE status='ok' AND frame_path IS NOT NULL
                AND json_array_length(result_json,'$.animals')>0""").fetchall()
        candidates = []
        for row in rows:
            path = (self.root / row["frame_path"]).resolve()
            if not path.is_relative_to((self.root / "frames").resolve()) or not path.is_file():
                continue
            check = self.decode(row)
            animals = [a for a in check["result"]["animals"] if a["confidence"] >= .5]
            if not animals:
                continue
            count = sum(a["count"] for a in animals)
            species = {a["species"].strip().casefold() for a in animals}
            # Rarity is camera-dependent and assessed by the model's score/reason.
            # Common predators get an additional boost, without treating all birds
            # or all unfamiliar species as rare.
            predators = ("hyena", "hyaena", "leopard", "cheetah", "lion", "jackal", "wild dog")
            predator = any(any(word in name for word in predators) for name in species)
            score = check["interesting_score"] or 0
            if score < 8 and count < 4 and len(species) < 2 and not predator:
                continue
            weight = 1 + score ** 2 + min(count, 30) * 3 + len(species) * 15 + int(predator) * 45
            reasons = []
            if count >= 4:
                reasons.append(f"{count} animals in one frame")
            if len(species) >= 2:
                reasons.append(f"{len(species)} species together")
            if predator:
                reasons.append("Predator sighting")
            if score >= 8:
                reasons.append("A highly noteworthy moment when captured")
            candidates.append((check, weight, {"animal_count": count, "species_count": len(species),
                                              "reason": " · ".join(reasons)}))
        # Avoid repeating the current image when another qualifying frame exists.
        alternatives = [entry for entry in candidates if entry[0]["id"] != exclude_id]
        pool = alternatives or candidates
        if not pool:
            return {"check": None, "has_alternatives": False, "selection": None}
        selected = random.choices(pool, weights=[entry[1] for entry in pool], k=1)[0]
        return {"check": selected[0], "has_alternatives": len(candidates) > 1,
                "selection": selected[2], "fact": self.fact(selected[0]["result"])}

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
