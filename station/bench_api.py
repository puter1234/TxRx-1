"""Routes for local component commissioning, separate from production inspections."""
import asyncio
import threading
import time
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import Field
from .schema import Model
from .controller import Conflict
from .bench import BenchSetup, serial_ports
from .usb_camera import CameraProfile
from .sensor_ocr import SensorOcrTest, SensorOcrSettings


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


def install(app, controller, bench, camera, permitted, editable, production_busy, maintenance_active, workers):
    store = controller.store
    captures = store.root / "device-tests"
    batch = {"active": False, "completed": 0, "target": 0}
    batch_cancel = threading.Event()
    ocr_frame = {"id": None, "image": None}
    ocr_frame_lock = threading.Lock()
    sensor_ocr = SensorOcrTest(bench, camera, app.state.vision)
    app.state.sensor_ocr = sensor_ocr

    def available(allow_led=False, allow_outputs=False):
        editable()
        if sensor_ocr.busy():
            raise Conflict("파이프라인 시험을 먼저 정지하세요.")
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
        return {**bench.status(), "camera": camera.status(), "batch": dict(batch),
                "sensor_ocr": sensor_ocr.status(details=False)}

    @app.get("/api/bench/pipeline")
    def pipeline_state():
        return sensor_ocr.status()

    @app.post("/api/bench/pipeline/start")
    async def start_pipeline(body: SensorOcrSettings, request: Request):
        permitted(request)
        def execute():
            app.state.vision.load()
            sensor_ocr.start(body)
            return {**bench.status(), "sensor_ocr": sensor_ocr.status(details=False)}
        return await native(execute, allow_outputs=True)

    @app.post("/api/bench/pipeline/stop")
    def stop_pipeline(request: Request):
        permitted(request)
        bench.stop("파이프라인 시험 중지")
        return sensor_ocr.status()

    @app.get("/api/bench/pipeline/frames/{job_id}/{sequence}")
    def pipeline_image(job_id: str, sequence: int, request: Request, crop: int | None = None):
        permitted(request)
        image = sensor_ocr.image(job_id, sequence, crop)
        if image is None:
            raise HTTPException(410, "이 프레임은 메모리에서 정리되었습니다.")
        import cv2
        height, width = image.shape[:2]
        scale = min(1.0, 1280 / max(height, width))
        if scale < 1:
            image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))))
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise HTTPException(500, "프레임을 표시하지 못했습니다.")
        return Response(encoded.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

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
            if sensor_ocr.busy():
                raise Conflict("파이프라인 시험 중입니다. 정지는 언제든 가능합니다.")
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
            if sensor_ocr.busy():
                return bench.stop("LED 끄기로 파이프라인 시험 중지")
            return bench.led_off()

    @app.post("/api/bench/motor/off")
    def motor_off(request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            editable()
            if production_busy() or maintenance_active.is_set():
                raise Conflict("작업 종료 후 모터를 시험하세요.")
            if sensor_ocr.busy():
                return bench.stop("모터 끄기로 파이프라인 시험 중지")
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
            missing = app.state.vision.status()["missing_modules"]
            if missing:
                return {"ok": False, "detail": "OCR 실행 패키지 없음: " + ", ".join(missing)}
            try:
                app.state.vision.load()
            except ModuleNotFoundError as exc:
                return {"ok": False, "detail": "OCR 실행 패키지가 설치되지 않았습니다: " + str(exc.name)}
            status = app.state.vision.status()
            device = str(status.get("device") or "")
            return {"ok": status["loaded"], "detail":
                    "OCR GPU 사용: " + str(status.get("gpu_name") or device)
                    if device.startswith("cuda") else "OCR CPU 사용 중"}
        return await native(execute, allow_led=True)

    @app.post("/api/bench/ocr/read")
    async def read_ocr(request: Request):
        permitted(request)

        def execute():
            if not camera.status().get("connected"):
                raise Conflict("카메라를 먼저 연결하세요.")
            with ocr_frame_lock:
                ocr_frame.update(id=None, image=None)
            started = time.perf_counter()
            # The live test uses the frame already arriving from the camera.
            # Waiting for two more frames adds hundreds of milliseconds at low FPS.
            frame, timing = camera.read_latest()
            capture_ms = (time.perf_counter() - started) * 1000
            result = app.state.vision.test_auto(frame)
            result["timing"] = timing
            result["capture_ms"] = round(capture_ms, 1)
            result["processing_ms"] = round(
                (time.perf_counter() - started) * 1000 - capture_ms, 1
            )
            ident = str(uuid.uuid4())
            with ocr_frame_lock:
                ocr_frame.update(id=ident, image=frame)
            result["preview_url"] = "/api/bench/ocr/frames/" + ident
            result["original_url"] = result["preview_url"] + "?original=true"
            return result

        return await native(execute, allow_led=True)

    @app.get("/api/bench/ocr/frames/{ident}")
    def ocr_image(ident: str, request: Request, original: bool = False):
        permitted(request)
        import cv2

        with ocr_frame_lock:
            if ident != ocr_frame["id"] or ocr_frame["image"] is None:
                raise HTTPException(410, "이전 검사 사진은 다음 검사에서 교체됩니다.")
            image = ocr_frame["image"]
        headers = {"Cache-Control": "no-store"}
        if original:
            ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            headers["Content-Disposition"] = f'attachment; filename="ocr-frame-{ident}.png"'
            media_type = "image/png"
        else:
            height, width = image.shape[:2]
            scale = min(1.0, 1280 / max(width, height))
            if scale < 1:
                image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))))
            ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            media_type = "image/jpeg"
        if not ok:
            raise HTTPException(500, "검사 사진을 표시하지 못했습니다.")
        return Response(encoded.tobytes(), media_type=media_type, headers=headers)

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
