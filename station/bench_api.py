"""Routes for local component commissioning, separate from production inspections."""
import asyncio
import threading
import time
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field
from .schema import Model
from .controller import Conflict
from .bench import BenchSetup, serial_ports
from .usb_camera import CameraProfile


class Pulse(Model):
    target: str = Field(pattern="^(motor|led)$")
    seconds: float = Field(ge=0.1, le=60)
    generation: int = Field(ge=0)
    request_id: str = Field(min_length=8, max_length=100)
    issued_at: float


class Heartbeat(Model):
    run_id: str = Field(min_length=1, max_length=100)


class Device(Model):
    device: str = Field(min_length=1, max_length=240)


class CameraApply(Model):
    profile: CameraProfile
    save: bool = True
    expected_revision: int = Field(ge=0)


def install(app, controller, bench, camera, permitted, editable, production_busy, maintenance_active, workers):
    store = controller.store
    captures = store.root / "device-tests"

    def available(allow_led=False):
        editable()
        if production_busy() or maintenance_active.is_set() or bench.native_busy:
            raise Conflict("진행 중인 점검이 끝난 후 다시 시도하세요.")
        if bench.run and not (allow_led and bench.run["target"] == "led"):
            raise Conflict("출력 시험을 먼저 정지하세요.")

    async def native(function, *, allow_led=False):
        with controller.lock, bench.lock:
            available(allow_led)
            bench.native_busy = True
            bench.cancel.clear()

        def run():
            try:
                return function()
            except (Conflict, ValueError, HTTPException):
                raise
            except Exception as exc:
                raise ValueError(str(exc)) from exc
            finally:
                bench.native_busy = False
        try:
            future = asyncio.get_running_loop().run_in_executor(None, run)
        except BaseException:
            bench.native_busy = False
            raise
        workers.add(future)

        def completed(f):
            workers.discard(f)
            if not f.cancelled():
                f.exception()
        future.add_done_callback(completed)
        return await asyncio.shield(future)

    @app.get("/api/bench")
    def state():
        return {**bench.status(), "camera": camera.status()}

    @app.get("/api/bench/ports")
    def ports():
        return {"ports": serial_ports()}

    @app.put("/api/bench/setup")
    async def setup(body: BenchSetup, request: Request):
        actor = permitted(request, ("admin",))
        return await native(lambda: bench.save_setup(body, actor))

    @app.post("/api/bench/io/connect")
    async def connect(request: Request):
        permitted(request)
        return await native(bench.connect)

    @app.post("/api/bench/io/disconnect")
    async def disconnect(request: Request):
        permitted(request)
        bench.stop("점검 종료")
        return await native(bench.disconnect)

    @app.post("/api/bench/output")
    def pulse(body: Pulse, request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            editable()
            if production_busy() or maintenance_active.is_set() or bench.native_busy:
                raise Conflict("진행 중인 점검이 끝난 후 다시 시도하세요.")
            return bench.pulse(**body.model_dump())

    @app.post("/api/bench/heartbeat")
    def heartbeat(body: Heartbeat, request: Request):
        permitted(request)
        return bench.heartbeat(body.run_id)

    @app.post("/api/bench/stop")
    def stop(request: Request):
        permitted(request)
        result = bench.stop()
        # This route also works while a camera/RFID worker or a start request is pending.
        controller.fault("DEVICE_TEST_STOP")
        return result

    @app.post("/api/bench/rfid")
    async def rfid(request: Request):
        permitted(request)
        return await native(bench.rfid_test)

    @app.post("/api/bench/ocr")
    async def ocr(request: Request):
        permitted(request)
        def execute():
            app.state.vision.load()
            return {"ok": app.state.vision.status()["loaded"], "detail": "OCR 모델 준비 완료"}
        return await native(execute, allow_led=True)

    @app.get("/api/bench/camera/devices")
    async def cameras():
        return await asyncio.to_thread(camera.backend.devices)

    @app.post("/api/bench/camera/inspect")
    async def inspect(body: Device, request: Request):
        permitted(request)
        return await native(lambda: camera.inspect(body.device), allow_led=True)

    @app.post("/api/bench/camera/apply")
    async def apply(body: CameraApply, request: Request):
        actor = permitted(request, ("admin",))
        def execute():
            if body.expected_revision != camera.revision:
                raise Conflict("다른 화면에서 카메라 설정을 변경했습니다. 다시 불러오세요.")
            return camera.apply(body.profile, persist=body.save, actor=actor)
        return await native(execute, allow_led=True)

    @app.post("/api/bench/camera/connect")
    async def camera_connect(request: Request):
        permitted(request)
        return await native(camera.connect, allow_led=True)

    @app.post("/api/bench/camera/disconnect")
    async def camera_disconnect(request: Request):
        permitted(request)
        def execute():
            camera.close()
            return camera.status()
        return await native(execute, allow_led=True)

    @app.post("/api/bench/camera/capture")
    async def capture(request: Request):
        actor = permitted(request)
        def execute():
            import cv2
            controller.check_disk()
            image, meta = camera.after(time.monotonic_ns(), 10)
            ident = str(uuid.uuid4())
            captures.mkdir(exist_ok=True)
            path = captures / (ident + ".png")
            ok, encoded = cv2.imencode(".png", image)
            if not ok:
                raise ValueError("시험 사진을 저장하지 못했습니다.")
            path.write_bytes(encoded.tobytes())
            result = {"id": ident, "url": "/api/bench/captures/" + ident,
                      "width": image.shape[1], "height": image.shape[0],
                      "time": time.time(), "metadata": meta, "actor": actor}
            try:
                store.event("BENCH_CAMERA_CAPTURE", result)
                store.put("last_bench_capture", result)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return result
        return await native(execute, allow_led=True)

    @app.get("/api/bench/captures/latest")
    def latest():
        return store.get("last_bench_capture")

    @app.get("/api/bench/captures/{ident}")
    def image(ident: str):
        try:
            parsed = str(uuid.UUID(ident))
        except ValueError:
            raise HTTPException(404)
        path = captures / (parsed + ".png")
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")
