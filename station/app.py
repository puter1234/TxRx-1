from __future__ import annotations

import asyncio
import json
import os
import re
import time
import threading
from datetime import datetime, timezone
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
from .bench import Bench
from .usb_camera import CameraManager

ROOT = Path(__file__).resolve().parents[1]


class Password(Model):
    password: str = Field(min_length=1, max_length=64)


class PasswordChange(Model):
    current: str = Field(min_length=1, max_length=64)
    next: str = Field(min_length=6, max_length=64)


class BrandSave(Model):
    brand: Brand
    expected_revision: int | None = None
    reason: str = Field(default="메이커 설정 저장", min_length=3, max_length=500)


class OperatorSettings(Model):
    save_photos: bool = True


def create_app(data_dir: Path | None = None, io=None, vision=None, camera=None, bench_factory=Bench):
    store = Store(data_dir or Path(os.environ.get("TXRX_DATA", ROOT / "runtime")))
    config_path = Path(os.environ.get("TXRX_CONFIG", ROOT / "config/station.json"))
    config = (
        StationConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else StationConfig()
    )
    camera = camera or CameraManager(config, store)
    detector = None
    hardware_errors = []
    if io is None:
        if config.mode == "REPLAY":
            io = ReplayIO()
        else:
            from .hardware import GpioIO, ProductDetector

            try:
                io = GpioIO(config)
            except Exception as exc:
                io = UnavailableIO(str(exc))
            try:
                camera.connect()
            except Exception as exc:
                camera.error = str(exc)
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
    maintenance_active = threading.Event()
    maintenance_workers = set()
    prior_busy = controller.external_busy
    bench = bench_factory(config, io, store)
    controller.external_busy = lambda: maintenance_active.is_set() or prior_busy() or bench.busy()

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
        bench.stop("서비스 종료")
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
        if maintenance_workers:
            await asyncio.gather(*maintenance_workers, return_exceptions=True)
        if camera:
            camera.close()
        bench.close()
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
    app.state.bench, app.state.camera = bench, camera

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
        bench.stop("처리 오류")
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
            raise HTTPException(403, "환경 설정 비밀번호를 입력하세요.")
        return profile["username"]

    def cookie_response(token):
        result = JSONResponse({"ok": True})
        result.set_cookie(
            "txrx_session", token, httponly=True, samesite="strict", max_age=12 * 3600
        )
        return result

    def login_response(pin):
        return cookie_response(auth.login(pin))

    @app.post("/api/auth/local")
    def local_entry(request: Request):
        token = request.cookies.get("txrx_session")
        return cookie_response(token if auth.valid(token) else auth.local_session())

    @app.post("/api/auth/setup")
    def setup(body: Password):
        if auth.configured():
            raise Conflict("이미 초기 설정을 완료했습니다.")
        auth.set_pin(body.password)
        store.event("ADMIN_INITIALIZED", {})
        return login_response(body.password)

    @app.post("/api/auth/login")
    def login(body: Password):
        return login_response(body.password)

    @app.post("/api/auth/password")
    def change_password(body: PasswordChange, request: Request):
        permitted(request, ("admin",))
        editable()
        temporary = auth.login(body.current)
        auth.sessions.pop(temporary, None)
        auth.save_user("admin", "admin", True, body.next, "admin", "비밀번호 변경")
        return login_response(body.next)

    @app.post("/api/auth/logout")
    def logout(request: Request):
        auth.sessions.pop(request.cookies.get("txrx_session"), None)
        return cookie_response(auth.local_session())

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
        actor = permitted(request, ("admin",))
        editable()
        return store.save_brand(
            body.brand.model_dump(), body.expected_revision, actor, body.reason
        )

    @app.post("/api/brands/validate")
    def validate_brand(body: Brand):
        return body.model_dump()

    @app.get("/api/settings")
    def operator_settings():
        return {
            "save_photos": store.get(
                "save_pass_photos", config.mode != "HARDWARE"
            ),
            "data_dir": str(store.root),
            "count_method": "stopped_product",
        }

    @app.put("/api/settings")
    def save_operator_settings(body: OperatorSettings, request: Request):
        actor = permitted(request, ("admin",))
        with controller.lock:
            editable()
            with store.transaction() as c:
                c.execute(
                    "INSERT OR REPLACE INTO meta VALUES(?,?)",
                    ("save_pass_photos", json.dumps(body.save_photos)),
                )
                store.event(
                    "PHOTO_POLICY_CHANGED",
                    {"save_photos": body.save_photos, "actor": actor},
                    c,
                )
        return operator_settings()

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
        actor = permitted(request)
        if cmd.action in ("stop", "pause", "finish"):
            bench.stop("작업 정지")
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
        return controller.adjust(body, permitted(request))

    @app.get("/api/history")
    def history(offset: int = 0, session_id: str | None = None):
        if offset < 0:
            raise ValueError("이력 위치는 0 이상이어야 합니다.")
        return {
            "sessions": store.histories(offset=offset),
            "inspections": store.inspection_rows(offset=offset, session_id=session_id),
        }

    @app.get("/api/events")
    def events(after_seq: int | None = None):
        return {
            "events": store.events(max(0, after_seq) if after_seq is not None else None)
        }

    @app.get("/api/event-history")
    def event_history(since: datetime, until: datetime, before_seq: int | None = None):
        if since.tzinfo is None or until.tzinfo is None or since >= until:
            raise ValueError("조회 시작과 종료 시각을 확인하세요.")
        # Stored UTC timestamps use isoformat with an explicit +00:00 offset.
        start = since.astimezone(timezone.utc).isoformat()
        end = until.astimezone(timezone.utc).isoformat()
        return {"events": store.event_page(start, end, before_seq)}

    @app.get("/api/equipment")
    def equipment():
        return {
            "data_dir": str(store.root),
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

    @app.get("/api/camera/frame")
    async def camera_frame():
        if camera is None or not camera.status()["connected"]:
            raise HTTPException(503, "카메라가 연결되지 않았습니다.")
        import cv2
        from fastapi.responses import Response

        def encode():
            frame, _ = camera.read_latest()
            # Preview is bounded; saved test captures keep the original resolution.
            if frame.shape[1] > 1280:
                frame = cv2.resize(frame, (1280, max(1, round(frame.shape[0] * 1280 / frame.shape[1]))))
            ok, data = cv2.imencode(".jpg", frame)
            if not ok:
                raise RuntimeError("카메라 영상 변환 실패")
            return data.tobytes()

        return Response(await asyncio.to_thread(encode), media_type="image/jpeg")

    @app.post("/api/device/test/{kind}")
    async def device_test(kind: str, request: Request):
        permitted(request)
        if kind not in ("sensor", "rfid", "ocr"):
            raise HTTPException(404)
        with controller.lock:
            editable()
            if controller.external_busy():
                raise Conflict("진행 중인 점검이 끝난 후 다시 시도하세요.")
            maintenance_active.set()
            controller.stop_outputs()

        def check():
            try:
                snap = io.snapshot()
                if config.mode == "HARDWARE" and snap.get("km2_on") is not False:
                    raise Conflict("장비 정지 상태를 확인할 수 없습니다.")
                if kind == "sensor":
                    raw = snap.get("di_raw")
                    return {
                        "ok": bool(snap.get("connected") and raw is not None),
                        "detail": (
                            "센서 미연결"
                            if raw is None
                            else "입력 신호 " + ", ".join(map(str, raw))
                        ),
                    }
                if kind == "rfid":
                    if config.mode != "HARDWARE" or not snap.get("rfid_ready"):
                        return {"ok": False, "detail": "RFID 미연결"}
                    if not config.rfid_window_ms:
                        raise Conflict("RFID 읽기 시간이 미설정입니다.")
                    tags = io.inventory(config.rfid_window_ms, threading.Event())
                    return {
                        "ok": len(tags) == 1,
                        "detail": "읽은 태그 " + str(len(tags)) + "개",
                        "tags": tags,
                    }
                vision.load()
                return {"ok": vision.status()["loaded"], "detail": "OCR 모델 준비 완료"}
            finally:
                # An abandoned HTTP request must not clear native-worker ownership.
                maintenance_active.clear()

        try:
            future = asyncio.get_running_loop().run_in_executor(None, check)
        except BaseException:
            maintenance_active.clear()
            raise
        maintenance_workers.add(future)

        def completed(worker):
            maintenance_workers.discard(worker)
            if not worker.cancelled():
                worker.exception()  # Observe errors even after an HTTP disconnect.

        future.add_done_callback(completed)
        return await asyncio.shield(future)

    from .bench_api import install as install_bench

    install_bench(app, controller, bench, camera, permitted, editable, prior_busy,
                  maintenance_active, maintenance_workers)

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
                from .evidence import save_upload

                target, info = await asyncio.to_thread(
                    save_upload, store.root, inspection["id"], data
                )
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
            elif recipe.kind == "simple" or any(
                c in recipe.channels for c in ("ocr", "barcode")
            ):
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
