"""All-history wildlife summaries, bucketed in each camera's local calendar."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .store import utcnow


def bucket_for(day, period):
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    return day


def next_bucket(day, period):
    if period == "month":
        return day.replace(year=day.year + (day.month == 12), month=day.month % 12 + 1)
    return day + timedelta(days=7 if period == "week" else 1)


def summarize(store, cams, period="day", cam_id=None, now=None):
    now = now or utcnow()
    with store.db() as db:
        rows = db.execute("SELECT cam_id,timezone,checked_at_utc,result_json FROM checks "
                          "WHERE status='ok' AND result_json IS NOT NULL"
                          + (" AND cam_id=?" if cam_id else ""),
                          [cam_id] if cam_id else []).fetchall()
    species = Counter()
    bins = defaultdict(lambda: {"checks": 0, "sightings": 0})
    checks, sightings = 0, 0
    observed_dates = []
    for row in rows:
        instant = datetime.fromisoformat(row["checked_at_utc"])
        if instant > now:
            continue
        local = instant.astimezone(ZoneInfo(row["timezone"]))
        observed_dates.append(local.date())
        animals = json.loads(row["result_json"])["animals"]
        names = {a["species"].strip().casefold() for a in animals if a["confidence"] >= .5 and a["count"] > 0}
        species.update(names)
        cell = bins[(bucket_for(local.date(), period).isoformat(), local.hour)]
        cell["checks"] += 1
        cell["sightings"] += bool(names)
        checks += 1; sightings += bool(names)
    selected = [cam for cam in cams if not cam_id or cam.id == cam_id]
    today = max((now.astimezone(ZoneInfo(cam.timezone)).date() for cam in selected), default=now.date())
    start = bucket_for(min(observed_dates, default=today), period)
    end = bucket_for(max([today, *observed_dates]), period)
    dates, labels = [], []
    cursor = start
    # Include gaps rather than pretending that an unobserved hour was empty.
    while cursor <= end:
        dates.append(cursor.isoformat())
        labels.append(cursor.strftime("%b %Y" if period == "month" else "%b %d, %y"))
        cursor = next_bucket(cursor, period)
    ranked = sorted(species.items(), key=lambda item: (-item[1], item[0]))
    leaders = [{"species": name, "label": name, "count": count, "other": False} for name, count in ranked[:5]]
    if ranked:
        leaders.append({"species": "__other__", "label": "Other species", "count": sum(count for _, count in ranked[5:]), "other": True})
    activity = [{"date": day, "hour": hour, **bins[(day, hour)]} for day in dates for hour in range(24)]
    hour_totals = [{"hour": hour, "sightings": sum(bins[(day, hour)]["sightings"] for day in dates),
                    "checks": sum(bins[(day, hour)]["checks"] for day in dates)} for hour in range(24)]
    bucket_totals = [{"date": day, "sightings": sum(bins[(day, hour)]["sightings"] for hour in range(24)),
                      "checks": sum(bins[(day, hour)]["checks"] for hour in range(24))} for day in dates]
    return {"period": period, "dates": dates, "bucket_labels": labels, "species": leaders,
            "species_count": len(species), "activity": activity, "hour_totals": hour_totals,
            "bucket_totals": bucket_totals, "total_checks": checks, "wildlife_frames": sightings,
            "history_start": min(observed_dates).isoformat() if observed_dates else None,
            "timezone_mode": "camera-local"}
