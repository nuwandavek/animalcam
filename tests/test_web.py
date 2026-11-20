import copy

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from animalcam.runner import Busy
from animalcam.store import Store, utcnow
from animalcam.web import create_app


class FakeWorker:
    def __init__(self): self.pending = []
    def start(self): pass
    def stop(self): pass
    def snapshot(self): return {"running": False, "queued": bool(self.pending)}
    def request(self, cam_id=None):
        if self.pending: raise Busy("Already queued")
        self.pending.append(cam_id)


def test_dashboard_auth_images_filters_and_manual_run(settings, observation):
    settings.password = "test-password"
    worker = FakeWorker()
    store = Store(settings.state_dir)
    path = settings.state_dir / "frames/waterhole/test.jpg"
    path.parent.mkdir(parents=True); path.write_bytes(b"jpeg")
    check_id = store.insert(settings.cams()[0], utcnow().isoformat(), "ok", "frames/waterhole/test.jpg", observation)
    with TestClient(create_app(settings, worker, FakeWorker())) as client:
        assert client.get("/healthz").status_code == 200
        for route in ["/", "/api/state", "/api/checks", "/api/highlight", f"/api/checks/{check_id}/image", "/assets/app.js"]:
            assert client.get(route).status_code == 401
        client.auth = ("animalcam", "test-password")
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/checks?group=bird&interesting=true").json()["total"] == 1
        assert client.get("/api/checks?species=jackal").json()["total"] == 0
        assert client.get(f"/api/checks/{check_id}/image").content == b"jpeg"
        assert client.get("/api/highlight").json()["check"]["id"] == check_id
        assert client.get("/api/checks?date_from=2026-11-20&date_to=2026-11-18").status_code == 422
        assert client.get("/api/checks?limit=999999").status_code == 422
        assert client.post("/api/run", json={"cam_id": "waterhole"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/run", json={"cam_id": "nope"}).status_code == 404
        assert client.post("/api/run", json={"cam_id": "waterhole"}, headers={"Origin": "http://testserver"}).status_code == 202
        assert worker.pending == ["waterhole"]
        assert client.post("/api/run", json={}).status_code == 409


def test_cams_reload_and_image_path_protection(settings, observation):
    worker = FakeWorker()
    with TestClient(create_app(settings, worker, FakeWorker())) as client:
        assert len(client.get("/api/state").json()["cams"]) == 1
        settings.cams_path.write_text(settings.cams_path.read_text() + '''
[[cam]]
id = "new-cam"
name = "New cam"
url = "https://www.youtube.com/watch?v=second"
''')
        assert len(client.get("/api/state").json()["cams"]) == 2
        assert client.post("/api/run", json={"cam_id": "new-cam"}).status_code == 202
        check_id = Store(settings.state_dir).insert(settings.cams()[0], utcnow().isoformat(), "ok", "../cams.toml", observation)
        assert client.get(f"/api/checks/{check_id}/image").status_code == 404


def test_missing_key_disables_manual_checks(settings):
    settings.api_key = ""
    with TestClient(create_app(settings, FakeWorker(), FakeWorker())) as client:
        assert client.post("/api/run", json={}).status_code == 503
        assert client.get("/api/state").json()["configured"] is False


@pytest.mark.parametrize("client_ip,origin,expected", [
    ("172.20.0.1", "https://animalcam.example", 202),
    ("172.20.0.1", "https://evil.example", 403),
    ("203.0.113.5", "https://animalcam.example", 403),
])
def test_https_manual_checks_trust_only_configured_proxy(settings, client_ip, origin, expected):
    worker = FakeWorker()
    app = ProxyHeadersMiddleware(create_app(settings, worker, FakeWorker()),
                                 trusted_hosts="127.0.0.1,172.20.0.1")
    async def from_peer(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "client": (client_ip, 12345)}
        await app(scope, receive, send)

    with TestClient(from_peer) as client:
        response = client.post("/api/run", json={}, headers={
            "Host": "animalcam.example", "Origin": origin, "X-Forwarded-Proto": "https",
        })
        assert response.status_code == expected
        assert bool(worker.pending) is (expected == 202)


@pytest.mark.parametrize("score,count,names,confidence,expected", [
    (8, 1, ["ostrich"], .9, True),
    (2, 6, ["ostrich"], .9, True),
    (2, 1, ["ostrich", "gemsbok"], .9, True),
    (2, 1, ["brown hyena"], .9, True),
    (9, 1, ["pangolin"], .9, True),
    (2, 1, ["ostrich"], .9, False),
    (10, 1, [], .9, False),
    (10, 6, ["ostrich"], .2, False),
])
def test_highlight_qualifies_real_wildlife_by_interest_abundance_variety_or_predator(
        settings, observation, score, count, names, confidence, expected):
    store = Store(settings.state_dir)
    result = copy.deepcopy(observation)
    result.update(interesting_score=score, interesting=score >= 6)
    result["animals"] = [{**observation["animals"][0], "species": name, "count": count,
                          "group": "bird" if name == "ostrich" else "mammal",
                          "confidence": confidence} for name in names]
    path = settings.state_dir / "frames/waterhole/highlight.jpg"
    path.parent.mkdir(parents=True); path.write_bytes(b"jpeg")
    check_id = store.insert(settings.cams()[0], utcnow().isoformat(), "ok",
                            "frames/waterhole/highlight.jpg", result)
    with TestClient(create_app(settings, FakeWorker(), FakeWorker())) as client:
        data = client.get("/api/highlight").json()
        assert bool(data["check"]) is expected
        if expected:
            assert data["check"]["id"] == check_id
            assert client.get(data["check"]["image_url"]).status_code == 200
        assert data["has_alternatives"] is False


def test_shuffle_replaces_current_highlight_and_skips_unavailable_frames(settings, observation):
    store = Store(settings.state_dir)
    cam, at = settings.cams()[0], utcnow().isoformat()
    ids = []
    for name in ["first", "second"]:
        path = settings.state_dir / f"frames/waterhole/{name}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"jpeg")
        ids.append(store.insert(cam, at, "ok", str(path.relative_to(settings.state_dir)), observation))
    store.insert(cam, at, "ok", "frames/waterhole/missing.jpg", observation)
    outside = settings.state_dir / "private.txt"
    outside.write_text("Not an image")
    store.insert(cam, at, "ok", "private.txt", observation)
    with TestClient(create_app(settings, FakeWorker(), FakeWorker())) as client:
        first = client.get("/api/highlight").json()
        assert first["has_alternatives"] is True
        assert first["check"]["id"] in ids
        second = client.get(f"/api/highlight?exclude_id={first['check']['id']}").json()
        assert second["check"]["id"] in ids and second["check"]["id"] != first["check"]["id"]
        assert client.get("/api/highlight?exclude_id=-1").status_code == 422
    for path in (settings.state_dir / "frames").rglob("*.jpg"):
        path.unlink()
    assert store.highlight() == {"check": None, "has_alternatives": False, "selection": None}
