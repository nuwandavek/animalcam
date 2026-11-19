import copy
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from animalcam.config import Cam
from animalcam.stats import summarize
from animalcam.store import Store
from animalcam.web import create_app
from test_web import FakeWorker


def test_stats_use_camera_local_days_and_count_frames_not_individuals(settings, observation):
    store = Store(settings.state_dir)
    cam = settings.cams()[0]
    now = datetime(2026, 11, 20, 1, tzinfo=timezone.utc)
    # Namibia is UTC+2: this belongs to Nov 20 at 00:00.
    store.insert(cam, "2026-11-19T22:10:00+00:00", "ok", result=observation)
    # Same species appears twice in JSON; count the frame once.
    duplicate = {**observation, "animals": observation["animals"] * 2}
    store.insert(cam, "2026-11-19T22:40:00+00:00", "ok", result=duplicate)
    store.insert(cam, "2026-11-19T21:00:00+00:00", "ok", result=observation)
    store.insert(cam, "2026-11-19T23:15:00+00:00", "ok", result={**observation, "animals": []})
    store.insert(cam, "2026-11-19T23:30:00+00:00", "offline")
    stats = summarize(store, [cam], "day", now=now)
    assert stats["dates"] == ["2026-11-19", "2026-11-20"]
    assert stats["total_checks"] == 4 and stats["wildlife_frames"] == 3
    assert stats["species"][0]["count"] == 3
    midnight = next(cell for cell in stats["activity"] if cell["date"] == "2026-11-20" and cell["hour"] == 0)
    assert midnight["checks"] == 2 and midnight["sightings"] == 2
    one = next(cell for cell in stats["activity"] if cell["date"] == "2026-11-20" and cell["hour"] == 1)
    assert one["checks"] == 1 and one["sightings"] == 0
    assert next(cell for cell in stats["activity"] if cell["hour"] == 8)["checks"] == 0


def test_top_five_other_and_low_confidence_exclusion(settings, observation):
    store = Store(settings.state_dir); cam = settings.cams()[0]
    now = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
    for index, name in enumerate(["ostrich", "gemsbok", "zebra", "jackal", "leopard", "oryx", "elephant"]):
        result = copy.deepcopy(observation)
        result["animals"][0]["species"] = name
        for _ in range(index+1): store.insert(cam, "2026-11-19T12:00:00+00:00", "ok", result=result)
    uncertain = copy.deepcopy(observation)
    uncertain["animals"][0].update(species="unidentified bird", confidence=.2, count=20)
    store.insert(cam, "2026-11-19T12:00:00+00:00", "ok", result=uncertain)
    stats = summarize(store, [cam], "week", now=now)
    assert stats["species_count"] == 7
    assert len(stats["species"]) == 6
    assert stats["species"][-1]["other"] and stats["species"][-1]["count"] == 3
    assert stats["wildlife_frames"] == 28 and stats["total_checks"] == 29
    assert stats["dates"] == ["2026-11-16"]
    assert len(stats["activity"]) == 24
    assert summarize(store, [cam], "month", now=now)["dates"] == ["2026-11-01"]
    assert summarize(store, [cam], "week", cam_id="missing", now=now)["total_checks"] == 0


def test_all_grains_keep_the_entire_history_and_marginal_totals(settings, observation):
    store = Store(settings.state_dir); cam = settings.cams()[0]
    now = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
    for at in ["2025-12-31T22:10:00+00:00", "2026-01-04T22:10:00+00:00",
               "2026-02-01T00:00:00+00:00", "2026-11-19T12:00:00+00:00"]:
        store.insert(cam, at, "ok", result=observation)
    summaries = {period: summarize(store, [cam], period, now=now) for period in ["day", "week", "month"]}
    for stats in summaries.values():
        assert stats["total_checks"] == stats["wildlife_frames"] == 4
        assert stats["species"][0]["count"] == 4
        assert sum(cell["sightings"] for cell in stats["hour_totals"]) == 4
        assert sum(cell["sightings"] for cell in stats["bucket_totals"]) == 4
        assert stats["history_start"] == "2026-01-01"
    assert summaries["day"]["dates"][0] == "2026-01-01"
    assert summaries["week"]["dates"][0] == "2025-12-29"  # Monday of the ISO week.
    assert summaries["month"]["dates"][0] == "2026-01-01"
    assert len(summaries["month"]["dates"]) == 11  # Calendar months, not a 30-day window.
    january = next(row for row in summaries["month"]["bucket_totals"] if row["date"] == "2026-01-01")
    assert january["sightings"] == 2


def test_dst_repeat_hour_is_combined_and_stats_api_is_authenticated(settings, observation):
    store = Store(settings.state_dir)
    cam = Cam("west", "West camera", "https://example.com/live", "America/Los_Angeles")
    store.insert(cam, "2026-11-01T08:15:00+00:00", "ok", result=observation)
    store.insert(cam, "2026-11-01T09:15:00+00:00", "ok", result=observation)
    stats = summarize(store, [cam], "day", now=datetime(2026, 11, 1, 20, tzinfo=timezone.utc))
    assert next(cell for cell in stats["activity"] if cell["hour"] == 1)["sightings"] == 2
    settings.password = "test"
    with TestClient(create_app(settings, FakeWorker(), FakeWorker())) as client:
        assert client.get("/api/stats").status_code == 401
        client.auth = (settings.user, "test")
        assert client.get("/api/stats?period=month").status_code == 200
        assert client.get("/api/stats?period=year").status_code == 422
        assert client.get("/assets/kiwi-explorer.webp").headers["content-type"].startswith("image/webp")
        for name in ["vega.min.js", "vega-interpreter.min.js", "charts.js"]:
            assert client.get(f"/assets/{name}").status_code == 200
        assert "unsafe-eval" not in client.get("/").headers["content-security-policy"]
