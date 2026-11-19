import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict

from .runner import Busy, Worker
from .store import Store

STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cam_id: str | None = None


def create_app(settings, worker=None):
    store = Store(settings.state_dir)
    worker = worker or Worker(settings)
    basic = HTTPBasic(auto_error=False)

    def authorize(credentials: HTTPBasicCredentials | None = Depends(basic)):
        if settings.password:
            valid_user = secrets.compare_digest((credentials.username if credentials else "").encode(), settings.user.encode())
            valid_password = secrets.compare_digest((credentials.password if credentials else "").encode(), settings.password.encode())
            if not (valid_user and valid_password):
                raise HTTPException(401, "Sign in to animalcam", headers={"WWW-Authenticate": 'Basic realm="animalcam"'})

    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title="animalcam", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.worker = worker

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/", dependencies=[Depends(authorize)])
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/assets/{name}", dependencies=[Depends(authorize)])
    def assets(name: Literal["app.js", "style.css"]):
        return FileResponse(STATIC / name)

    @app.get("/api/state", dependencies=[Depends(authorize)])
    def state():
        from dataclasses import asdict
        return {"worker": worker.snapshot(), "cams": [asdict(c) for c in settings.cams()],
                "species": store.species(), "model": settings.model, "interval_min": settings.interval,
                "configured": bool(settings.api_key)}

    @app.get("/api/checks", dependencies=[Depends(authorize)])
    def checks(cam: str | None = None, species: str | None = None, group: str | None = None,
               interesting: bool = False, animals: bool = False,
               status: Literal["ok", "offline", "error"] | None = None,
               date_from: date | None = None, date_to: date | None = None,
               limit: int = Query(48, ge=1, le=100), offset: int = Query(0, ge=0)):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "Start date must be before end date")
        return store.list(cam=cam, species=species, group=group, interesting=interesting,
                          animals=animals, status=status, date_from=date_from, date_to=date_to,
                          limit=limit, offset=offset)

    @app.get("/api/checks/{check_id}", dependencies=[Depends(authorize)])
    def detail(check_id: int):
        row = store.get(check_id)
        if not row:
            raise HTTPException(404, "Check not found")
        return row

    @app.get("/api/checks/{check_id}/image", dependencies=[Depends(authorize)])
    def image(check_id: int):
        row = store.get(check_id)
        if not row or not row["frame_path"]:
            raise HTTPException(404, "Image no longer available")
        path = (settings.state_dir / row["frame_path"]).resolve()
        if not path.is_relative_to((settings.state_dir / "frames").resolve()) or not path.is_file():
            raise HTTPException(404, "Image not found")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/run", status_code=202, dependencies=[Depends(authorize)])
    def run(body: RunRequest, request: Request):
        origin = request.headers.get("origin")
        if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Use Check now from this dashboard")
        if not settings.api_key:
            raise HTTPException(503, "Set OPENAI_API_KEY in .env first")
        if body.cam_id and body.cam_id not in {c.id for c in settings.cams()}:
            raise HTTPException(404, "Unknown cam ID")
        try:
            worker.request(body.cam_id)
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        return {"queued": True}

    return app
