from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .auth import Auth
from .controller import Controller, Conflict
from .devices import ReplayIO, UnavailableIO, LeaseGuard
from .rules import decode_epc, RuleError
from .schema import Model, Brand, Recipe, Command, Adjustment, StationConfig
from .storage import Store, utc
from .telemetry import collect
from .vision import Vision
from .runtime import HardwareCycle

ROOT = Path(__file__).resolve().parents[1]


class Password(Model):
    password: str = Field(min_length=1, max_length=64)
    username: str = Field(default="admin", min_length=1, max_length=40)


class BrandSave(Model):
    brand: Brand
    expected_revision: int | None = None
    reason: str = Field(default="메이커 설정 저장", min_length=3, max_length=500)


class UserSave(Model):
    username: str
    role: str
    enabled: bool = True
    password: str = Field(default="", max_length=64)
    reason: str = Field(min_length=3, max_length=500)


def create_app(data_dir: Path | None = None, io=None, vision=None):
    store = Store(data_dir or Path(os.environ.get("TXRX_DATA", ROOT / "runtime")))
    config_path = Path(os.environ.get("TXRX_CONFIG", ROOT / "config/station.json"))
    config = (
        StationConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else StationConfig()
    )
    camera = None
    detector = None
    hardware_errors = []
    if io is None:
        if config.mode == "REPLAY":
            io = ReplayIO()
        else:
            from .hardware import GpioIO, Camera, ProductDetector

            try:
                io = GpioIO(config)
            except Exception as exc:
                io = UnavailableIO(str(exc))
            try:
                camera = Camera(config)
            except Exception as exc:
                hardware_errors.append(str(exc))
            try:
                detector = ProductDetector(
                    config.commissioning.detector_module,
                    config.commissioning.detector_sha256,
                )
            except Exception as exc:
                hardware_errors.append(str(exc))
    vision = vision or Vision()
    controller = Controller(store, io, config)
    controller.external_busy = lambda: vision.status().get("busy", False)
    auth = Auth(store)
    if not store.get("initial_catalog_seeded", False):
        for seed in sorted((ROOT / "config/brands").glob("*.samples.json")):
            brand = Brand.model_validate_json(seed.read_text(encoding="utf-8"))
            if not any(b["id"] == brand.id for b in store.brands()):
                store.save_brand(brand.model_dump(), None, "local-seed")
        store.put("initial_catalog_seeded", True)
    hardware_monitor = (
        HardwareCycle(controller, camera, detector, vision)
        if config.mode == "HARDWARE"
        else None
    )
    if hardware_monitor:
        controller.runtime_blockers = hardware_monitor.blockers
        controller.external_busy = (
            lambda: vision.status().get("busy", False) or hardware_monitor.worker_busy()
        )

    async def watch():
        nonlocal hardware_monitor
        guard = LeaseGuard(io, config.io_lease_ms)
        try:
            while True:
                await asyncio.sleep(0.1)
                guard.renew()
                state = controller.snapshot()
                phase = (state["session"] or {}).get("phase")
                if (
                    config.mode == "HARDWARE"
                    and phase
                    in (
                        "FEEDING",
                        "EJECTING",
                        "PASSED",
                        "STOPPING",
                        "INSPECTING",
                        "RETRY_PENDING",
                    )
                    and time.monotonic() - controller.last_client > 3
                ):
                    controller.fault("OPERATOR_SCREEN_DISCONNECTED")
                if guard.failed and phase not in (None, "FAULT", "FINISHED", "DONE"):
                    controller.fault(guard.failed)
                    guard.failed = None
                if hardware_monitor:
                    try:
                        await hardware_monitor.tick()
                    except Exception as exc:
                        controller.fault("HARDWARE_MONITOR_ERROR: " + str(exc))
        finally:
            guard.close()

    async def maintain():
        while True:
            state = controller.snapshot()
            phase = (state["session"] or {}).get("phase")
            if (
                phase
                in (
                    None,
                    "READY",
                    "PAUSED",
                    "DONE",
                    "FINISHED",
                    "ABORTED",
                    "HOLD",
                    "FAULT",
                )
                and not state["busy"]
            ):
                try:
                    worker = asyncio.create_task(asyncio.to_thread(store.daily_backup))
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        await worker
                        raise
                except Exception as exc:
                    try:
                        store.event("BACKUP_FAILED", {"error": str(exc)})
                    except Exception:
                        pass
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(watch())
        maintenance = asyncio.create_task(maintain())
        yield
        controller.stop_outputs()
        if controller.session and controller.session["phase"] not in (
            "DONE",
            "FINISHED",
            "ABORTED",
        ):
            controller.fault("SERVICE_SHUTDOWN")
        task.cancel()
        maintenance.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        try:
            await maintenance
        except asyncio.CancelledError:
            pass
        if hardware_monitor:
            await hardware_monitor.close()
        if camera:
            camera.close()
        io.close()
        store.close()

    app = FastAPI(
        title="TXRX local inspection",
        version="0.3.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    from .limits import BodyLimit

    app.add_middleware(BodyLimit)
    app.state.store, app.state.controller, app.state.auth = store, controller, auth
    app.state.vision = vision

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.url.hostname
        if host not in ("127.0.0.1", "localhost", "::1", "testserver"):
            return JSONResponse(
                {"detail": "로컬 장비에서만 사용할 수 있습니다."}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.url.netloc:
            return JSONResponse(
                {"detail": "다른 출처의 요청은 허용되지 않습니다."}, status_code=403
            )
        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "잘못된 요청 길이입니다."}, status_code=400)
        if content_length > 22 * 1024 * 1024:
            return JSONResponse(
                {"detail": "요청은 22MB 이하여야 합니다."}, status_code=413
            )
        exempt = ("/api/auth", "/api/health")
        if request.url.path.startswith("/api/") and not request.url.path.startswith(
            exempt
        ):
            if not auth.valid(request.cookies.get("txrx_session")):
                return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse(
            {"detail": str(exc)}, status_code=409 if isinstance(exc, Conflict) else 422
        )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(
            {
                "detail": "입력 형식을 확인하세요.",
                "errors": [
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                    for e in exc.errors()
                ],
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        controller.stop_outputs()
        try:
            controller.fault("APPLICATION_ERROR")
        except Exception:
            pass
        return JSONResponse(
            {
                "detail": "처리 오류로 정지했습니다. 장비 상태와 저장 공간을 확인하세요.",
                "error_type": type(exc).__name__,
            },
            status_code=500,
        )

    @app.get("/api/auth")
    def auth_state(request: Request):
        profile = auth.profile(request.cookies.get("txrx_session"))
        return {
            "configured": auth.configured(),
            "authenticated": profile is not None,
            "user": profile,
        }

    def permitted(request, roles=("operator", "engineer", "admin")):
        profile = auth.profile(request.cookies.get("txrx_session"))
        if not profile or profile["role"] not in roles:
            raise HTTPException(403, "이 작업에 필요한 권한이 없습니다.")
        return profile["username"]

    def login_response(pin, username="admin"):
        token = auth.login(pin, username)
        result = JSONResponse({"ok": True})
        result.set_cookie(
            "txrx_session", token, httponly=True, samesite="strict", max_age=12 * 3600
        )
        return result

    @app.post("/api/auth/setup")
    def setup(body: Password):
        if auth.configured():
            raise Conflict("이미 초기 설정을 완료했습니다.")
        auth.set_pin(body.password)
        store.event("ADMIN_INITIALIZED", {})
        return login_response(body.password)

    @app.post("/api/auth/login")
    def login(body: Password):
        return login_response(body.password, body.username)

    @app.get("/api/users")
    def users(request: Request):
        permitted(request, ("admin",))
        return auth.users()

    @app.post("/api/users")
    def save_user(body: UserSave, request: Request):
        actor = permitted(request, ("admin",))
        editable()
        return auth.save_user(
            body.username, body.role, body.enabled, body.password, actor, body.reason
        )

    @app.post("/api/auth/logout")
    def logout(request: Request):
        controller.stop_outputs()
        if controller.session:
            controller.fault("OPERATOR_LOGOUT")
        auth.sessions.pop(request.cookies.get("txrx_session"), None)
        result = JSONResponse({"ok": True})
        result.delete_cookie("txrx_session")
        return result

    @app.get("/api/health/live")
    def live():
        return {"alive": True, "mode": config.mode}

    @app.get("/api/health/ready")
    def ready():
        reasons = (
            config.commissioning.blockers()
            + io.blockers()
            + controller.runtime_blockers()
            + hardware_errors
        )
        return {
            "software": True,
            "hardware_ready": config.mode == "HARDWARE" and not reasons,
            "blockers": reasons,
        }

    @app.get("/api/status")
    def status():
        controller.last_client = time.monotonic()
        return {**controller.snapshot(), "vision": vision.status()}

    @app.websocket("/api/ws")
    async def stream(ws: WebSocket):
        origin = ws.headers.get("origin")
        if (
            ws.url.hostname not in ("127.0.0.1", "localhost", "::1", "testserver")
            or (origin and urlparse(origin).netloc != ws.url.netloc)
            or not auth.valid(ws.cookies.get("txrx_session"))
        ):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while auth.valid(ws.cookies.get("txrx_session")):
                # Only an acknowledged screen heartbeat extends operator presence.
                await ws.send_json(
                    {
                        "state": {**controller.snapshot(), "vision": vision.status()},
                        "event_seq": store.last_event_seq(),
                    }
                )
                message = await asyncio.wait_for(ws.receive_json(), timeout=2)
                if not isinstance(message, dict) or message.get("type") != "heartbeat":
                    break
                controller.last_client = time.monotonic()
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    @app.get("/api/brands")
    def brands():
        return store.brands()

    def editable():
        state = controller.snapshot()
        if state["busy"] or (
            state["session"]
            and state["session"]["phase"] not in ("FINISHED", "DONE", "ABORTED")
        ):
            raise Conflict("진행 중인 작업을 종료한 후 설정을 수정하세요.")

    @app.post("/api/brands")
    def save_brand(body: BrandSave, request: Request):
        actor = permitted(request, ("admin", "engineer"))
        editable()
        if auth.profile(request.cookies.get("txrx_session"))["role"] == "engineer":
            prior = store.brand(body.brand.id)
            if {k: v for k, v in prior.items() if k not in ("ocr_regions", "note")} != {
                k: v
                for k, v in body.brand.model_dump().items()
                if k not in ("ocr_regions", "note")
            }:
                raise HTTPException(403, "제품 master 변경은 관리자 권한이 필요합니다.")
        return store.save_brand(
            body.brand.model_dump(), body.expected_revision, actor, body.reason
        )

    @app.post("/api/brands/validate")
    def validate_brand(body: Brand):
        return body.model_dump()

    @app.delete("/api/brands/{ident}")
    def delete_brand(
        ident: str, revision: int, request: Request, reason: str = "메이커 설정 삭제"
    ):
        actor = permitted(request, ("admin",))
        editable()
        store.delete_brand(ident, revision, actor, reason)
        return {"ok": True}

    @app.post("/api/sessions")
    def new_session(recipe: Recipe, request: Request):
        if "ocr" in recipe.channels:
            vision.load()
        return controller.new_session(recipe, permitted(request))

    @app.post("/api/commands")
    def command(cmd: Command, request: Request):
        actor = permitted(
            request,
            (
                ("engineer", "admin")
                if cmd.action in ("reset", "discard")
                else ("operator", "engineer", "admin")
            ),
        )
        return controller.command(cmd, actor)

    @app.get("/api/commands/{ident}")
    def command_receipt(ident: str):
        with store.lock:
            row = store.conn.execute(
                "SELECT body FROM commands WHERE id=?", (ident,)
            ).fetchone()
        return {"found": row is not None, "result": json.loads(row[0]) if row else None}

    @app.post("/api/adjustments")
    def adjust(body: Adjustment, request: Request):
        return controller.adjust(body, permitted(request, ("engineer", "admin")))

    @app.get("/api/history")
    def history(offset: int = 0):
        if offset < 0:
            raise ValueError("이력 위치는 0 이상이어야 합니다.")
        return {
            "sessions": store.histories(offset=offset),
            "inspections": store.inspection_rows(offset=offset),
        }

    @app.get("/api/events")
    def events(after_seq: int | None = None):
        return {
            "events": store.events(max(0, after_seq) if after_seq is not None else None)
        }

    @app.get("/api/equipment")
    def equipment():
        return {
            "system": collect(store.root),
            "io": io.snapshot(),
            "vision": vision.status(),
            "metrics": store.metrics(),
            "last_daily_backup": store.get("last_daily_backup"),
            "camera": (
                camera.status()
                if camera
                else {"connected": False, "error": "카메라 미연결"}
            ),
            "config": config.model_dump(),
            "blockers": config.commissioning.blockers()
            + io.blockers()
            + controller.runtime_blockers()
            + hardware_errors,
        }

    @app.post("/api/backup")
    def backup(request: Request):
        permitted(request, ("admin",))
        result = store.backup()
        store.event("BACKUP_CREATED", result)
        return result

    @app.get("/api/backups/{name}")
    def download_backup(name: str, request: Request):
        permitted(request, ("admin",))
        if not re.fullmatch(r"\d{8}-\d{6}-\d{6}\.sqlite3", name):
            raise HTTPException(404)
        path = store.root / "backups" / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename=name)

    @app.get("/api/evidence/{ident}")
    def evidence(ident: str):
        if not re.fullmatch(r"[0-9a-f-]{36}", ident):
            raise HTTPException(404)
        path = store.root / "evidence" / f"{ident}.png"
        if not path.is_file():
            path = store.root / "evidence" / f"{ident}.jpg"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(
            path, media_type="image/png" if path.suffix == ".png" else "image/jpeg"
        )

    @app.post("/api/replay")
    async def replay(
        request: Request,
        product_id: str = Form(...),
        epcs: str = Form(""),
        image: UploadFile | None = File(None),
    ):
        if config.mode != "REPLAY":
            raise Conflict("실물 모드에서는 파일·수동 EPC 입력을 사용할 수 없습니다.")
        if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,100}", product_id):
            raise ValueError("제품 식별자는 영문/숫자/._:- 1~100자입니다.")
        inspection, epoch, brand = controller.begin(
            product_id, actor=permitted(request)
        )
        recipe = Recipe.model_validate(inspection["recipe"])
        observations, failures, info = {}, [], None
        try:
            controller.inspecting(epoch)
            tags = sorted(
                {
                    v.strip().upper()
                    for v in epcs.replace(",", "\n").splitlines()
                    if v.strip()
                }
            )
            if "rfid" in recipe.channels:
                if len(tags) != 1:
                    failures.append(
                        {"code": "RFID_MISSING" if not tags else "MULTIPLE_RFID_TAGS"}
                    )
                else:
                    try:
                        observations["rfid"] = decode_epc(brand, tags[0])
                    except RuleError as exc:
                        failures.append({"code": str(exc)})
            inspection["rfid_epcs"] = tags
            if image is not None:
                data = await image.read(20 * 1024 * 1024 + 1)
                if len(data) > 20 * 1024 * 1024:
                    raise ValueError("이미지는 20MB 이하여야 합니다.")
                from PIL import Image, ImageOps
                import io as buffer

                with Image.open(buffer.BytesIO(data)) as im:
                    if im.width * im.height > 24_000_000:
                        raise ValueError("이미지는 2,400만 화소 이하여야 합니다.")
                    im.load()
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    target = store.root / "evidence" / f'{inspection["id"]}.png'
                    target.parent.mkdir(exist_ok=True)
                    im.save(target, format="PNG")
                    target.with_suffix(".original").write_bytes(data)
                info = {
                    "url": f'/api/evidence/{inspection["id"]}',
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "input_sha256": hashlib.sha256(data).hexdigest(),
                    "source": "UPLOADED_PHOTO",
                }
                if not failures and any(
                    c in recipe.channels for c in ("ocr", "barcode")
                ):
                    # Isolated to a worker thread; STOP/API remains responsive. A timeout
                    # latches fault, ignores late results, and Vision rejects overlapping work.
                    result = await asyncio.wait_for(
                        asyncio.to_thread(vision.inspect, target, brand, recipe),
                        timeout=120,
                    )
                    observations.update(result["observations"])
                    failures.extend(result["failures"])
                    inspection["vision"] = result
            elif any(c in recipe.channels for c in ("ocr", "barcode")):
                failures.append({"code": "IMAGE_MISSING"})
        except asyncio.TimeoutError:
            failures.append({"code": "VISION_TIMEOUT"})
        except Exception as exc:
            failures.append({"code": "INSPECTION_ERROR", "detail": str(exc)})
        return controller.complete(inspection, epoch, observations, failures, info)

    dist = ROOT / "ocr/frontend/dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def index(path: str):
        if path.startswith(("api/", "assets/")):
            raise HTTPException(404)
        if not (dist / "index.html").is_file():
            return JSONResponse(
                {"detail": "프론트엔드 빌드가 필요합니다."}, status_code=503
            )
        return FileResponse(dist / "index.html")

    return app
