"""Single-worker API. Device operations are serialized by ControlService."""
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
import asyncio
import json
import secrets
import hashlib
import threading
import time
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.middleware.trustedhost import TrustedHostMiddleware
from urllib.parse import urlparse
from coc_bot.control.service import ControlService, BusyError
from coc_bot.control.settings import settings_snapshot, save_settings, RevisionConflict
from coc_bot.control.calibration import Captures, checklist
from coc_bot.config import load_config, project_root, profile_root
from coc_bot.web.auth import Authentication


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Payload):
    password: str = Field(max_length=256)


class Start(Payload):
    practice: StrictBool = False


class Settings(Payload):
    revision: str
    values: dict


class Selection(Payload):
    capture: str
    part: str
    selection: list = Field(max_length=500)
    revision: str
    cols: StrictInt = 7
    rows: StrictInt = 1
    jitter: StrictInt = 6


class Rename(Payload):
    name: str = Field(max_length=80)


def create_app(service=None, auth_path=None, origins=None, secure_cookie=False,
               scope=None, shared_auth=None, enable_simulation=True):
    service = service or ControlService()
    auth = shared_auth or Authentication(auth_path or project_root() / "data/web-auth.json")
    if not auth.path.is_file():
        raise RuntimeError("Set a browser password first: python -m coc_bot.web --set-password")
    allowed_origins = set(origins or ["http://127.0.0.1:8765", "http://localhost:8765"])
    captures = Captures()
    simulation = None
    simulation_temp = None

    @asynccontextmanager
    async def lifespan(app):
        from loguru import logger
        sink = logger.add(lambda message: service.events.append(
            message.record["level"].name, message.record["message"]))
        try:
            yield
        finally:
            logger.remove(sink)
            await asyncio.to_thread(service.close)
            simulation_stopped = True
            if simulation is not None:
                simulation_stopped = await asyncio.to_thread(simulation.close)
            if simulation_temp is not None and simulation_stopped:
                import shutil
                shutil.rmtree(simulation_temp)
            elif simulation_temp is not None:
                logger.warning("First-launch test data retained because a tool is still stopping: {}", simulation_temp)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[
        urlparse(origin).hostname for origin in allowed_origins])
    app.state.service, app.state.auth, app.state.captures = service, auth, captures

    @app.middleware("http")
    async def guard(request, call_next):
        api_path = request.url.path.removeprefix(request.scope.get("root_path", ""))
        if api_path.startswith("/api/"):
            if request.headers.get("origin") and request.headers["origin"] not in allowed_origins:
                return Response("Origin rejected", status_code=403)
            if api_path != "/api/login":
                csrf = auth.session(request.cookies.get("coc_session"))
                if not csrf:
                    return Response("Login required", status_code=401)
                if request.method not in ("GET", "HEAD") and not secrets.compare_digest(
                        request.headers.get("x-csrf-token", ""), csrf):
                    return Response("Request token rejected", status_code=403)
            length = request.headers.get("content-length", "0")
            max_size = 50*1024*1024 if api_path == "/api/backups/import" else 100000
            if not length.isdigit() or int(length) > max_size:
                return Response("Request too large", status_code=413)
            if request.method not in ("GET", "HEAD") and api_path != "/api/backups/import":
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > max_size:
                        return Response("Request too large", status_code=413)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
        token = profile_root.set(scope)
        try:
            response = await call_next(request)
        finally:
            profile_root.reset(token)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; connect-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if api_path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return Response(str(exc), status_code=409 if isinstance(exc, RevisionConflict) else 400)

    @app.exception_handler(BusyError)
    async def busy(request, exc):
        return Response(str(exc), status_code=409)

    from coc_bot.runtime.device_lease import DeviceBusy
    @app.exception_handler(DeviceBusy)
    async def device_busy(request, exc):
        return Response("Another app is controlling this device. Stop it first.", status_code=409)

    @app.post("/api/login")
    def login(body: Login, request: Request):
        try:
            token, csrf = auth.login(body.password, request.client.host)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        response = Response(json.dumps({"csrf": csrf}), media_type="application/json")
        response.set_cookie("coc_session", token, httponly=True, samesite="strict",
                            secure=secure_cookie, max_age=auth.lifetime)
        return response

    @app.get("/api/session")
    def session(request: Request):
        return {"csrf": auth.session(request.cookies.get("coc_session"))}

    @app.post("/api/logout")
    def logout(request: Request):
        auth.logout(request.cookies.get("coc_session"))
        response = Response("{}" ,media_type="application/json")
        response.delete_cookie("coc_session")
        return response

    @app.get("/api/status")
    def status():
        return service.snapshot()

    @app.get("/api/mode")
    def interface_mode():
        return {"first_launch": scope is not None}

    @app.post("/api/start")
    def start(body: Start):
        service.start(body.practice)
        return service.snapshot()

    @app.post("/api/stop")
    def stop():
        service.stop()
        return service.snapshot()

    @app.post("/api/farm")
    def farm():
        return {"message": service.farm()}

    @app.get("/api/settings")
    def settings():
        with service.lock:
            return settings_snapshot()

    @app.put("/api/settings")
    def update(body: Settings):
        with service.mutation():
            result = save_settings(body.values, body.revision)
            service._finished_generation = -1
            return result

    @app.get("/api/setup")
    def setup():
        with service.lock:
            return checklist()

    @app.get("/api/readiness")
    def readiness():
        from coc_bot.calibration.profiles import check_calibration
        config = load_config()
        return {"issues": check_calibration(config), "farm_ready": config.farm_calibrated}

    @app.get("/api/report")
    def report():
        return {"status": service.snapshot(), "setup": checklist(),
                "events": service.events.since()}

    @app.post("/api/profiles")
    def profile(body: Rename):
        from coc_bot.calibration.profiles import save_interface_profile
        with service.mutation():
            saved = save_interface_profile(body.name, load_config())
            return {"id": saved.stamp}

    def capture(cancel, pan=False):
        from coc_bot.runtime.device_lease import DeviceLease
        session = service.session(cancel)
        with DeviceLease(session.config.adb_device):
            frame = session.prepare_farm_program_deploy()["frame"] if pan else session.capture.screenshot()
            with service.lock:
                return captures.add(frame)

    @app.post("/api/capture")
    def capture_now():
        service.job("capture", lambda cancel: capture(cancel))
        return service.snapshot()

    @app.post("/api/capture/pan")
    def pan_capture():
        service.job("capture", lambda cancel: capture(cancel, True))
        return service.snapshot()

    @app.get("/api/captures/{ident}")
    def image(ident: str):
        with service.lock:
            return Response(captures.get(ident)[1], media_type="image/png")

    @app.post("/api/setup")
    def save_part(body: Selection):
        with service.mutation():
            return captures.save(body.capture, body.part, body.selection, body.revision,
                                 body.cols, body.rows, body.jitter)

    @app.post("/api/diagnostics/{action}")
    def diagnostic(action: str):
        service.diagnostic(action)
        return service.snapshot()

    def find_backup(ident):
        from coc_bot.control.backups import list_backups
        found = next((b for b in list_backups() if b.stamp == ident), None)
        if found is None or not found.path.resolve().is_relative_to(
                (project_root() / "data/calibration_backups").resolve()):
            raise HTTPException(404, "Backup not found")
        return found

    @app.get("/api/backups")
    def backups():
        from coc_bot.control.backups import list_backups
        return [{"id": b.stamp, "label": b.label} for b in list_backups()]

    @app.post("/api/backups")
    def backup():
        from coc_bot.control.backups import create_backup
        with service.mutation():
            saved = create_backup()
            return {"id": saved.stamp}

    @app.get("/api/backups/{ident}/export")
    def export(ident: str):
        from coc_bot.control.archive import export_calibration
        with service.lock:
            content = export_calibration(find_backup(ident))
        return Response(content, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="calibration.zip"'})

    @app.post("/api/backups/import")
    async def import_backup(request: Request, name: str):
        from coc_bot.control.archive import import_calibration, LIMIT
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > LIMIT:
                raise HTTPException(413, "Calibration archive exceeds 50 MB")
            chunks.append(chunk)
        def publish():
            with service.mutation():
                return {"id": import_calibration(b"".join(chunks), name).stamp}
        return await asyncio.to_thread(publish)

    @app.post("/api/backups/{ident}/restore")
    def restore(ident: str):
        from coc_bot.control.backups import restore_backup
        with service.mutation():
            restore_backup(find_backup(ident))
            return checklist()

    @app.patch("/api/backups/{ident}")
    def rename(ident: str, body: Rename):
        from coc_bot.control.backups import rename_backup
        with service.mutation():
            return {"id": rename_backup(find_backup(ident), body.name).stamp}

    @app.delete("/api/backups/{ident}")
    def delete(ident: str):
        from coc_bot.control.backups import delete_backup
        with service.mutation():
            delete_backup(find_backup(ident))
            return {"deleted": True}

    @app.get("/api/events")
    def events(after: int = 0):
        return service.events.since(max(0, after))

    gallery_lock = threading.Lock()
    gallery_cache = {"at": 0, "paths": [], "index": {}}
    def collection_images():
        base = project_root() / "data/collection"
        # Paths never come from the browser. Only enumerated files below the
        # collection root can be served, including when a folder is symlinked.
        with gallery_lock:
            if time.monotonic() - gallery_cache["at"] > 5:
                paths = [p for p in base.rglob("*.png")
                         if p.resolve().is_relative_to(base.resolve()) and p.is_file()]
                paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                gallery_cache.update(at=time.monotonic(), paths=paths,
                    index={hashlib.sha256(str(p).encode()).hexdigest(): p for p in paths})
            return list(gallery_cache["paths"])

    @app.get("/api/library")
    def library(offset: int = 0, limit: int = 24):
        paths = collection_images()
        page = paths[max(0, offset):max(0, offset)+min(100, max(1, limit))]
        status_path = project_root() / "data/collection/status.json"
        try:
            collection = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            collection = None
        return {"total": len(paths), "collection": collection, "images": [
            {"id": hashlib.sha256(str(p).encode()).hexdigest(), "label": p.name}
            for p in page]}

    @app.get("/api/library/images/{ident}")
    def library_image(ident: str):
        collection_images()
        with gallery_lock:
            path = gallery_cache["index"].get(ident)
        base = project_root() / "data/collection"
        if path is None or not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
            raise HTTPException(404, "Image not found")
        return FileResponse(path, media_type="image/png")

    @app.websocket("/api/events/ws")
    async def live(ws: WebSocket):
        origin = ws.headers.get("origin")
        if origin not in allowed_origins or not auth.session(ws.cookies.get("coc_session")):
            await ws.close(code=1008)
            return
        await ws.accept()
        token = profile_root.set(scope)
        cursor = 0
        try:
            while auth.session(ws.cookies.get("coc_session")):
                history = service.events.since(cursor)
                cursor = history["cursor"]
                snapshot = await asyncio.to_thread(service.snapshot)
                await ws.send_json({"status": snapshot, "events": history})
                await asyncio.sleep(1)
            await ws.close(code=1008)
        except WebSocketDisconnect:
            pass
        finally:
            profile_root.reset(token)

    @app.websocket("/api/viewer/ws")
    async def viewer(ws: WebSocket):
        from coc_bot.web.viewer import run_viewer
        token = profile_root.set(scope)
        try:
            await run_viewer(ws, service, auth, allowed_origins)
        finally:
            profile_root.reset(token)

    if enable_simulation:
        import tempfile
        import shutil
        simulation_temp = tempfile.mkdtemp(prefix="coc-first-launch-")
        simulation_root = Path(simulation_temp)
        shutil.copytree(project_root() / "config", simulation_root / "config")
        # This profile deliberately contains no calibration, templates, settings
        # or runtime data. It is discarded when this server exits.
        simulation = ControlService(service.controller.new_controller(), session_factory=service.session_factory)
        simulation.lock = service.lock
        simulation.peers = [service]
        service.peers = [simulation]
        simulation.events = service.events
        @app.post("/api/first-launch/reset")
        def reset_first_launch():
            with service.mutation():
                data = simulation_root / "data"
                if data.exists():
                    shutil.rmtree(data)
                simulation._finished_generation = -1
                return {"reset": True}
        child = create_app(simulation, origins=allowed_origins, secure_cookie=secure_cookie,
            scope=simulation_root, shared_auth=auth, enable_simulation=False)
        app.mount("/first-launch", child)

    assets = Path(__file__).parent / "static"
    if assets.is_dir():
        app.mount("/", StaticFiles(directory=assets, html=True), name="web")
    return app
