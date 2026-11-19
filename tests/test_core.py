import copy
import fcntl
import json
import subprocess
import threading
from datetime import date, timedelta

import httpx
import pytest
from pydantic import ValidationError

from animalcam import analyze as vision
from animalcam import runner
from animalcam.alert import should_alert
from animalcam.grab import Offline
from animalcam.store import Store, utcnow


def test_birds_and_json_validation(observation):
    result = vision.Observation.model_validate(observation)
    assert result.animals[0].group == "bird"
    bad = copy.deepcopy(observation)
    bad["animals"][0]["confidence"] = 1.1
    with pytest.raises(ValidationError):
        vision.Observation.model_validate(bad)
    with pytest.raises(ValidationError):
        vision.Observation.model_validate({**observation, "interesting_score": 15})


def test_luna_structured_request_and_response(settings, observation, monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/responses"
        data = json.loads(request.content)
        assert data["model"] == "gpt-6-luna" and data["store"] is False
        assert data["text"]["format"]["strict"] is True
        assert "previous" in data["input"][0]["content"][0]["text"]
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(observation)}]}]})
    real_client = httpx.Client
    monkeypatch.setattr(vision.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(vision, "image_data", lambda _: "data:image/jpeg;base64,test")
    assert vision.analyze(None, settings.cams()[0], observation, settings) == observation


def test_incomplete_model_output_is_error(settings, monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "incomplete", "output": []}))
    monkeypatch.setattr(vision.httpx, "Client", lambda **kw: real_client(transport=transport))
    monkeypatch.setattr(vision, "image_data", lambda _: "data:image/jpeg;base64,test")
    with pytest.raises(ValueError, match="incomplete"):
        vision.analyze(None, settings.cams()[0], None, settings)


def test_filters_retention_and_history(settings, observation):
    store, cam = Store(settings.state_dir), settings.cams()[0]
    at = utcnow().isoformat()
    bird = store.insert(cam, at, "ok", "frames/waterhole/bird.jpg", observation)
    empty = {**observation, "animals": [], "interesting": False, "interesting_score": 0}
    old = (utcnow() - timedelta(days=10)).isoformat()
    for name, result, alerted in [("empty", empty, False), ("bird", observation, False), ("alerted", empty, True)]:
        path = settings.state_dir / f"frames/waterhole/{name}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"jpeg")
        check_id = store.insert(cam, old, "ok", str(path.relative_to(settings.state_dir)), result)
        if alerted:
            store.finish_alert(check_id)
    assert store.list(group="bird")["total"] == 2
    assert store.list(species="OSTRICH", animals=True, interesting=True)["total"] == 2
    assert store.list(species="leopard")["total"] == 0
    assert store.list(date_from=date.fromisoformat(at[:10]))["total"] == 1
    assert store.get(bird)["url"] == cam.url
    assert store.get(bird)["result"] == observation
    store.prune(7)
    assert not (settings.state_dir / "frames/waterhole/empty.jpg").exists()
    assert (settings.state_dir / "frames/waterhole/bird.jpg").exists()
    assert (settings.state_dir / "frames/waterhole/alerted.jpg").exists()
    assert store.list()["total"] == 4


def test_alert_cooldown_compares_last_alert_species(settings, observation):
    now = utcnow()
    previous = {"result": observation, "checked_at_utc": now.isoformat()}
    assert should_alert(observation, None, now.isoformat(), settings)
    assert not should_alert(observation, previous, (now + timedelta(minutes=15)).isoformat(), settings)
    changed = copy.deepcopy(observation)
    changed["animals"][0].update(species="jackal", group="mammal")
    assert should_alert(changed, previous, (now + timedelta(minutes=15)).isoformat(), settings)
    assert not should_alert({**observation, "interesting": False}, None, now.isoformat(), settings)
    assert not should_alert({**observation, "animals": []}, None, now.isoformat(), settings)


def fake_grab(cam, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"jpeg")


def test_run_persists_and_uses_previous_observation(settings, observation, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "grab", fake_grab)
    monkeypatch.setattr(runner, "analyze", lambda frame, cam, previous, cfg: calls.append(previous) or observation)
    assert runner.run_once(settings)[0]["status"] == "ok"
    assert runner.run_once(settings)[0]["status"] == "ok"
    store = Store(settings.state_dir)
    assert store.list()["total"] == 2
    assert calls == [None, observation]
    assert (settings.state_dir / store.latest("waterhole")["frame_path"]).exists()


def test_dry_run_leaves_no_state(settings, observation, monkeypatch, capsys):
    monkeypatch.setattr(runner, "grab", fake_grab)
    monkeypatch.setattr(runner, "analyze", lambda *args: observation)
    runner.run_once(settings, dry_run=True)
    assert not settings.state_dir.exists()
    assert json.loads(capsys.readouterr().out)["result"]["animals"][0]["group"] == "bird"


def test_failure_isolation_and_offline(settings, observation, monkeypatch):
    settings.cams_path.write_text(settings.cams_path.read_text() + '''
[[cam]]
id = "other"
name = "Other cam"
url = "https://www.youtube.com/watch?v=other"
''')
    def grab(cam, path):
        if cam.id == "waterhole": raise Offline("Stream ended")
        fake_grab(cam, path)
    monkeypatch.setattr(runner, "grab", grab)
    monkeypatch.setattr(runner, "analyze", lambda *args: observation)
    results = runner.run_once(settings)
    assert [r["status"] for r in results] == ["offline", "ok"]
    assert Store(settings.state_dir).list(status="offline")["total"] == 1


def test_alert_failure_preserves_analysis(settings, observation, monkeypatch):
    settings.backend = "ntfy"
    monkeypatch.setattr(runner, "grab", fake_grab)
    monkeypatch.setattr(runner, "analyze", lambda *args: observation)
    def fail(*args): raise ValueError("Notification unavailable")
    monkeypatch.setattr(runner.alert, "send", fail)
    runner.run_once(settings)
    row = Store(settings.state_dir).latest("waterhole")
    assert row["result"] == observation and row["status"] == "ok" and not row["alerted"]
    assert row["error"].startswith("Alert failed")


def test_consecutive_identical_scenes_send_only_one_alert(settings, observation, monkeypatch):
    settings.backend = "ntfy"
    sent = []
    monkeypatch.setattr(runner, "grab", fake_grab)
    monkeypatch.setattr(runner, "analyze", lambda *args: observation)
    monkeypatch.setattr(runner.alert, "send", lambda *args: sent.append(args[1]))
    runner.run_once(settings)
    runner.run_once(settings)
    checks = Store(settings.state_dir).list()["checks"]
    assert len(sent) == 1
    assert [check["alerted"] for check in checks] == [False, True]


def test_cross_process_lock(settings):
    Store(settings.state_dir)
    with (settings.state_dir / ".run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(runner.Busy):
            runner.run_once(settings)


def test_manual_worker_serializes_requests(settings, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def run(cfg, cam):
        entered.set(); assert release.wait(3)
        return [{"cam_id": cam, "status": "ok"}]
    monkeypatch.setattr(runner, "run_once", run)
    worker = runner.Worker(settings)
    worker.request("waterhole")
    with pytest.raises(runner.Busy): worker.request()
    worker.start()
    try:
        assert entered.wait(2)
        assert worker.snapshot()["running"]
        with pytest.raises(runner.Busy): worker.request()
        release.set()
        with worker.condition:
            assert worker.condition.wait_for(lambda: not worker.state["running"], timeout=2)
        assert worker.snapshot()["last_run"][0]["cam_id"] == "waterhole"
    finally:
        release.set(); worker.stop()


def test_sensitive_exception_text_is_not_logged():
    url = "https://secret.example/webhook/token"
    request = httpx.Request("POST", url)
    response = httpx.Response(401, request=request)
    exc = httpx.HTTPStatusError("secret", request=request, response=response)
    assert "secret" not in runner.safe_error(exc)
    assert "secret" not in runner.safe_error(subprocess.CalledProcessError(1, ["ffmpeg", url]))
