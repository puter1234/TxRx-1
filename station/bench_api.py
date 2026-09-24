"""Routes for local component commissioning, separate from production inspections."""
import asyncio
import threading
import time
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field, model_validator
from .schema import Model
from .ocr_correction import OCRCorrection
from .storage import dump
from .controller import Conflict
from .bench import BenchSetup, serial_ports
from .usb_camera import CameraProfile


class Pulse(Model):
    target: str = Field(pattern="^(motor|led)$")
    seconds: float | None = Field(default=None, ge=0.1, le=60)
    generation: int = Field(ge=0)
    request_id: str = Field(min_length=8, max_length=100)
    issued_at: float


class Heartbeat(Model):
    run_id: str = Field(min_length=1, max_length=100)


class RFIDSetup(Model):
    rfid_port: str = Field(default="", max_length=200)
    rfid_window_ms: int = Field(default=500, ge=100, le=10000)
    rfid_protocol_confirmed: bool = False


class Device(Model):
    device: str = Field(min_length=1, max_length=240)


class CameraApply(Model):
    profile: CameraProfile
    save: bool = True
    expected_revision: int = Field(ge=0)


class BatchCapture(Model):
    count: int = Field(ge=1, le=500)


class OCRRead(Model):
    box: tuple[float, float, float, float]
    rotation: int = Field(default=0)
    correction: OCRCorrection = Field(default_factory=OCRCorrection)

    @model_validator(mode="after")
    def valid_box(self):
        x, y, w, h = self.box
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 or y + h > 1:
            raise ValueError("OCR 영역은 영상 안에 지정해야 합니다.")
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("OCR 회전값은 0, 90, 180, 270 중에서 선택하세요.")
        return self


def install(app, controller, bench, camera, permitted, editable, production_busy, maintenance_active, workers):
    store = controller.store
    captures = store.root / "device-tests"
    batch = {"active": False, "completed": 0, "target": 0}
    batch_cancel = threading.Event()

    def available(allow_led=False, allow_outputs=False):
        editable()
        if production_busy() or maintenance_active.is_set() or bench.native_busy or bench.rfid_busy:
            raise Conflict("진행 중인 점검이 끝난 후 다시 시도하세요.")
        if bench.runs and not allow_outputs and not (allow_led and set(bench.runs) == {"led"}):
            raise Conflict("출력 시험을 먼저 정지하세요.")

    async def native(function, *, allow_led=False, allow_outputs=False):
        busy_field = "rfid_busy" if allow_outputs else "native_busy"
        with controller.lock, bench.lock:
            available(allow_led, allow_outputs)
            setattr(bench, busy_field, True)
            bench.cancel.clear()

        def run():
            try:
                return function()
            except (Conflict, ValueError, HTTPException):
                raise
            except Exception as exc:
                raise ValueError(str(exc)) from exc
            finally:
                setattr(bench, busy_field, False)
        try:
            future = asyncio.get_running_loop().run_in_executor(None, run)
        except BaseException:
            setattr(bench, busy_field, False)
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
        return {**bench.status(), "camera": camera.status(), "batch": dict(batch)}

    @app.post("/api/bench/camera/batch/cancel")
    def cancel_batch(request: Request):
        permitted(request)
        batch_cancel.set()
        return {"ok": True}

    @app.post("/api/bench/camera/batch")
    async def batch_capture(body: BatchCapture, request: Request):
        actor = permitted(request)
        def execute():
            from .camera_batch import capture_batch
            ident = str(uuid.uuid4())
            captures.mkdir(exist_ok=True)
            batch_cancel.clear()
            batch.update(active=True, completed=0, target=body.count)
            try:
                result = capture_batch(camera, captures / (ident + ".zip"), body.count,
                    lambda: batch_cancel.is_set() or bench.cancel.is_set(), controller.check_disk,
                    lambda completed: batch.update(completed=completed))
                result.update(id=ident, url="/api/bench/batches/" + ident)
                store.event("BENCH_CAMERA_BATCH", {**result, "actor": actor})
                store.put("last_bench_batch", result)
                return result
            finally:
                batch["active"] = False
        return await native(execute, allow_led=True)

    @app.get("/api/bench/batches/latest")
    def latest_batch():
        return store.get("last_bench_batch")

    @app.get("/api/bench/batches/{ident}")
    def download_batch(ident: str):
        try:
            parsed = str(uuid.UUID(ident))
        except ValueError:
            raise HTTPException(404)
        path = captures / (parsed + ".zip")
        if not path.is_file() or batch["active"]:
            raise HTTPException(404)
        return FileResponse(path, media_type="application/zip", filename="camera-" + parsed + ".zip")

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

    @app.put("/api/bench/rfid/setup")
    async def rfid_setup(body: RFIDSetup, request: Request):
        actor = permitted(request, ("admin",))
        return await native(lambda: bench.save_rfid_setup(body.model_dump(), actor), allow_outputs=True)

    @app.post("/api/bench/io/disconnect")
    async def disconnect(request: Request):
        permitted(request)
        with bench.lock:
            if any(time.monotonic() < bench.next_output_at[target] for target in bench.runs):
                raise Conflict("신호 변경 후 1초 뒤 연결을 종료하세요. 긴급 상황은 시험 비상정지를 누르세요.")
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

    @app.post("/api/bench/error/clear")
    def clear_error(request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            available()
            return bench.clear_error()

    @app.post("/api/bench/heartbeat")
    def heartbeat(body: Heartbeat, request: Request):
        permitted(request)
        return bench.heartbeat(body.run_id)

    @app.post("/api/bench/led/off")
    def led_off(request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            editable()
            if production_busy() or maintenance_active.is_set():
                raise Conflict("작업 종료 후 LED를 시험하세요.")
            return bench.led_off()

    @app.post("/api/bench/motor/off")
    def motor_off(request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            editable()
            if production_busy() or maintenance_active.is_set():
                raise Conflict("작업 종료 후 모터를 시험하세요.")
            return bench.output_off("motor")

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
        return await native(bench.rfid_test, allow_outputs=True)

    @app.post("/api/bench/ocr")
    async def ocr(request: Request):
        permitted(request)
        def execute():
            try:
                app.state.vision.load()
            except ModuleNotFoundError as exc:
                return {"ok": False, "detail": "OCR 실행 패키지가 설치되지 않았습니다: " + str(exc.name)}
            return {"ok": app.state.vision.status()["loaded"], "detail": "OCR 모델 준비 완료"}
        return await native(execute, allow_led=True)

    @app.get("/api/bench/ocr/correction")
    def ocr_correction():
        return OCRCorrection.model_validate(store.get("ocr_correction", {})).model_dump()

    @app.put("/api/bench/ocr/correction")
    def save_ocr_correction(body: OCRCorrection, request: Request):
        actor = permitted(request, ("admin",))
        with controller.lock, bench.lock:
            available(allow_led=True)
            with store.transaction() as transaction:
                transaction.execute(
                    "INSERT OR REPLACE INTO meta VALUES(?,?)",
                    ("ocr_correction", dump(body.model_dump())),
                )
                store.event(
                    "OCR_CORRECTION_SAVED",
                    {"actor": actor, "correction": body.model_dump()},
                    transaction,
                )
        return body.model_dump()

    @app.post("/api/bench/ocr/read")
    async def read_ocr(body: OCRRead, request: Request):
        permitted(request)

        def execute():
            if not camera.status().get("connected"):
                raise Conflict("카메라를 먼저 연결하세요.")
            started = time.perf_counter()
            frame, timing = camera.after(time.monotonic_ns(), 10)
            capture_ms = (time.perf_counter() - started) * 1000
            result = app.state.vision.test_region(
                frame, body.box, body.correction.model_dump(), body.rotation
            )
            result["timing"] = timing
            result["capture_ms"] = round(capture_ms, 1)
            result["processing_ms"] = round(
                (time.perf_counter() - started) * 1000 - capture_ms, 1
            )
            return result

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
