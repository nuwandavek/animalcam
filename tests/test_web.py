from fastapi.testclient import TestClient

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
    with TestClient(create_app(settings, worker)) as client:
        assert client.get("/healthz").status_code == 200
        for route in ["/", "/api/state", "/api/checks", f"/api/checks/{check_id}/image", "/assets/app.js"]:
            assert client.get(route).status_code == 401
        client.auth = ("animalcam", "test-password")
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/checks?group=bird&interesting=true").json()["total"] == 1
        assert client.get("/api/checks?species=jackal").json()["total"] == 0
        assert client.get(f"/api/checks/{check_id}/image").content == b"jpeg"
        assert client.get("/api/checks?date_from=2026-11-20&date_to=2026-11-18").status_code == 422
        assert client.get("/api/checks?limit=999999").status_code == 422
        assert client.post("/api/run", json={"cam_id": "waterhole"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/run", json={"cam_id": "nope"}).status_code == 404
        assert client.post("/api/run", json={"cam_id": "waterhole"}, headers={"Origin": "http://testserver"}).status_code == 202
        assert worker.pending == ["waterhole"]
        assert client.post("/api/run", json={}).status_code == 409


def test_cams_reload_and_image_path_protection(settings, observation):
    worker = FakeWorker()
    with TestClient(create_app(settings, worker)) as client:
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
    with TestClient(create_app(settings, FakeWorker())) as client:
        assert client.post("/api/run", json={}).status_code == 503
        assert client.get("/api/state").json()["configured"] is False
