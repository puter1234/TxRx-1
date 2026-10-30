"""Routes for local component commissioning, separate from production inspections."""
import asyncio
import threading
import time
import uuid
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import Field, model_validator
from .schema import Model
from .controller import Conflict
from .bench import BenchSetup, serial_ports
from .usb_camera import CameraProfile
from .sensor_ocr import SensorOcrTest, SensorOcrSettings


class Pulse(Model):
    target: str = Field(pattern="^(motor|led|speed)$")
    seconds: float | None = Field(default=None, ge=0.1, le=60)
    generation: int = Field(ge=0)
    request_id: str = Field(min_length=8, max_length=100)
    issued_at: float


class Heartbeat(Model):
    run_id: str = Field(min_length=1, max_length=100)


class RFIDSetup(Model):
    rfid_port: str = Field(default="", max_length=200)
    rfid_window_ms: int = Field(default=5000, ge=100, le=10000)
    rfid_power: int = Field(default=2600, ge=0, le=2600)
    rfid_protocol_confirmed: bool = False


class Device(Model):
    device: str = Field(min_length=1, max_length=240)


class OcrRead(Model):
    locator: Literal["yolo26", "stripes", "opencv"] = "yolo26"


class CameraApply(Model):
    profile: CameraProfile
    save: bool = True
    # Omitted by the settings screen, which saves every change as it is made.
    expected_revision: int | None = Field(default=None, ge=0)


class VisionStart(Model):
    preset_id: str = Field(min_length=1, max_length=48)


class BatchCapture(Model):
    count: int = Field(ge=1, le=500)
    interval_ms: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def duration(self):
        if (self.count - 1) * self.interval_ms >= 300000:
            raise ValueError("촬영 간격과 장수를 줄여 총 촬영 시간이 5분 미만이 되게 하세요.")
        return self


def install(app, controller, bench, camera, permitted, editable, production_busy, maintenance_active, workers):
    from .inspection_views import inspection_view, view_options

    store = controller.store
    captures = store.root / "device-tests"
    batch = {"active": False, "completed": 0, "target": 0}
    batch_cancel = threading.Event()
    ocr_frame = {"id": None, "image": None, "diagnostics": {}}
    ocr_frame_lock = threading.Lock()
    sensor_ocr = SensorOcrTest(bench, camera, app.state.vision)
    app.state.sensor_ocr = sensor_ocr
    from .vision_trial import VisionTrial
    vision_trial = VisionTrial(camera, store)
    app.state.vision_trial = vision_trial
    # The test emergency stop also ends a wappen counting trial.
    bench.stop_listeners.append(lambda reason: vision_trial.cancel.set())

    def models_ready():
        # Waiting here would hold the screen for the whole load; say so at once instead.
        if getattr(app.state.vision, "loading", lambda: False)():
            raise Conflict("검사 모델을 불러오는 중입니다. 잠시 후 다시 시도하세요.")

    def available(allow_led=False, allow_outputs=False, camera_only=False, allow_test=False):
        state = controller.snapshot()
        session = state["session"]
        # Camera adjustment is allowed before the first product without ending
        # and recreating the job. Other job/configuration contracts stay intact.
        ready_camera = camera_only and not state["busy"] and session and session["phase"] == "READY" and not session["active_product"]
        if not ready_camera:
            editable()
        else:
            io_state = controller.io.snapshot()
            if io_state.get("motor_requested") is True or io_state.get("km2_on") is True:
                raise Conflict("컨베이어를 정지한 뒤 카메라를 조정하세요.")
        if sensor_ocr.busy() and not allow_test:
            raise Conflict("공정 시험을 먼저 정지하세요.")
        if production_busy() or maintenance_active.is_set() or bench.native_busy or bench.rfid_busy:
            raise Conflict("진행 중인 점검이 끝난 후 다시 시도하세요.")
        if bench.runs and not allow_outputs and not (allow_led and set(bench.runs) == {"led"}):
            raise Conflict("출력 시험을 먼저 정지하세요.")

    async def native(function, *, allow_led=False, allow_outputs=False, camera_only=False, allow_test=False):
        busy_field = "rfid_busy" if allow_outputs and not camera_only else "native_busy"
        generation = bench.stop_serial

        def run():
            # Waiting for a start/configuration lock must not block HTTP STOP.
            with controller.lock, bench.lock:
                if generation != bench.stop_serial:
                    raise Conflict("정지 요청 이후에는 다시 실행하세요.")
                available(allow_led, allow_outputs, camera_only, allow_test)
                setattr(bench, busy_field, True)
                bench.cancel.clear()
            try:
                return function()
            except (Conflict, ValueError, HTTPException):
                raise
            except Exception as exc:
                raise ValueError(str(exc)) from exc
            finally:
                setattr(bench, busy_field, False)
        future = asyncio.get_running_loop().run_in_executor(None, run)
        workers.add(future)

        def completed(f):
            workers.discard(f)
            if not f.cancelled():
                f.exception()
        future.add_done_callback(completed)
        return await asyncio.shield(future)

    @app.get("/api/bench")
    def state():
        bench.watched()
        trial = vision_trial.status()
        return {**bench.status(), "camera": camera.status(), "batch": dict(batch),
                "sensor_ocr": sensor_ocr.status(details=False),
                "vision_trial": {k: trial[k] for k in ("active", "total", "error")}}

    @app.get("/api/bench/vision")
    def vision_state():
        return vision_trial.status()

    @app.post("/api/bench/vision/start")
    async def vision_start(body: VisionStart, request: Request):
        permitted(request)
        return await native(lambda: vision_trial.start(body.preset_id), allow_outputs=True, camera_only=True)

    @app.post("/api/bench/vision/stop")
    def vision_stop(request: Request):
        permitted(request)
        return vision_trial.stop()

    @app.get("/api/bench/pipeline")
    def pipeline_state():
        return sensor_ocr.status()

    @app.put("/api/bench/pipeline/settings")
    async def pipeline_settings(body: SensorOcrSettings, request: Request):
        permitted(request)
        return await native(lambda: sensor_ocr.save_settings(body))

    @app.post("/api/bench/pipeline/start")
    async def start_pipeline(body: SensorOcrSettings, request: Request):
        permitted(request)
        models_ready()
        def execute():
            app.state.vision.load()
            sensor_ocr.save_settings(body)
            sensor_ocr.start(body)
            return {**bench.status(), "sensor_ocr": sensor_ocr.status(details=False)}
        return await native(execute, allow_outputs=True)

    @app.post("/api/bench/pipeline/stop")
    def stop_pipeline(request: Request):
        permitted(request)
        bench.stop("공정 시험 중지")
        return sensor_ocr.status()

    @app.get("/api/bench/pipeline/frames/{job_id}/{sequence}")
    def pipeline_image(job_id: str, sequence: int, request: Request, crop: int | None = None, original: bool = False, view: str = "original", region: int = 0):
        permitted(request)
        image = sensor_ocr.image(job_id, sequence, crop)
        if image is None:
            raise HTTPException(410, "이 프레임은 메모리에서 정리되었습니다.")
        if view != "original":
            if crop is not None:
                raise HTTPException(422, "문자 크롭에서는 원본 보기를 사용하세요.")
            diagnostics = sensor_ocr.diagnostics(job_id, sequence)
            image = inspection_view(image, diagnostics, view, region)
        import cv2
        ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise HTTPException(500, "프레임을 표시하지 못했습니다.")
        headers = {"Cache-Control": "no-store"}
        if original:
            suffix = f"-crop-{crop}" if crop is not None else ""
            headers["Content-Disposition"] = f'attachment; filename="sensor-frame-{sequence}{suffix}.png"'
        return Response(encoded.tobytes(), media_type="image/png", headers=headers)

    @app.post("/api/bench/camera/batch/cancel")
    def cancel_batch(request: Request):
        permitted(request)
        batch_cancel.set()
        return {"ok": True}

    @app.post("/api/bench/camera/batch")
    async def batch_capture(body: BatchCapture, request: Request):
        actor = permitted(request)
        # Clear cancellation before scheduling the worker, never after a slow
        # driver query: leaving the workspace during that query must cancel it.
        with controller.lock, bench.lock:
            available(allow_outputs=True, camera_only=True)
            batch_cancel.clear()
        def execute():
            from .camera_batch import capture_batch
            camera.verify_fixed_controls()
            ident = str(uuid.uuid4())
            captures.mkdir(exist_ok=True)
            batch.update(active=True, completed=0, target=body.count)
            try:
                result = capture_batch(camera, captures / (ident + ".zip"), body.count,
                    lambda: batch_cancel.is_set() or bench.cancel.is_set(), controller.check_disk,
                    lambda completed: batch.update(completed=completed), interval_ms=body.interval_ms)
                result.update(id=ident, url="/api/bench/batches/" + ident)
                store.event("BENCH_CAMERA_BATCH", {**result, "actor": actor})
                store.put("last_bench_batch", result)
                return result
            finally:
                batch["active"] = False
        return await native(execute, allow_outputs=True, camera_only=True)

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
        if bench.runs:
            # Wiring changes need the outputs off; turn them off instead of refusing.
            bench.stop("연결 설정 저장")
        return await native(lambda: bench.save_setup(body, actor))

    @app.post("/api/bench/io/connect")
    async def connect(request: Request):
        permitted(request)
        return await native(bench.connect)

    @app.put("/api/bench/rfid/setup")
    async def rfid_setup(body: RFIDSetup, request: Request):
        actor = permitted(request, ("admin",))
        return await native(lambda: bench.save_rfid_setup(body.model_dump(exclude_unset=True), actor), allow_outputs=True)

    @app.post("/api/bench/io/disconnect")
    async def disconnect(request: Request):
        permitted(request)
        with bench.lock:
            if any(time.monotonic() < bench.next_output_at[target] for target in bench.runs):
                raise Conflict("신호 변경 후 1초 뒤 연결을 종료하세요. 긴급 상황은 시험 비상정지를 누르세요.")
        bench.stop("점검 종료")
        return await native(bench.disconnect)

    @app.post("/api/bench/close")
    async def close_workspace(request: Request):
        permitted(request)
        # Normal workspace exit releases the commissioning GPIO owner. Keeping
        # its input handle open would block the next production job. Unlike the
        # emergency stop route, this must not fault a prepared READY job.
        vision_trial.stop()
        return await native(bench.disconnect, allow_outputs=True, camera_only=True)

    @app.post("/api/bench/output")
    def pulse(body: Pulse, request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            editable()
            if sensor_ocr.busy():
                raise Conflict("공정 시험 중입니다. 정지는 언제든 가능합니다.")
            if production_busy() or maintenance_active.is_set() or bench.native_busy:
                raise Conflict("진행 중인 점검이 끝난 후 다시 시도하세요.")
            return bench.pulse(**body.model_dump())

    @app.post("/api/bench/error/clear")
    def clear_error(request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            available()
            return bench.clear_error()

    @app.post("/api/bench/speed/off")
    def speed_off(request: Request):
        permitted(request)
        if sensor_ocr.busy():
            return bench.stop("저속 수동 선택으로 연동 시험 중지")
        return bench.output_off("speed")

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
                return bench.stop("LED 끄기로 공정 시험 중지")
            return bench.led_off()

    @app.post("/api/bench/motor/off")
    def motor_off(request: Request):
        permitted(request)
        with controller.lock, bench.lock:
            editable()
            if production_busy() or maintenance_active.is_set():
                raise Conflict("작업 종료 후 모터를 시험하세요.")
            if sensor_ocr.busy():
                return bench.stop("모터 끄기로 공정 시험 중지")
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
                app.state.vision.prepare_locator()
            except ModuleNotFoundError as exc:
                return {"ok": False, "detail": "OCR 실행 패키지가 설치되지 않았습니다: " + str(exc.name)}
            status = app.state.vision.status()
            device = str(status.get("device") or "")
            return {"ok": status["loaded"], "detail":
                    "OCR GPU 사용: " + str(status.get("gpu_name") or device)
                    if device.startswith("cuda") else "OCR CPU 사용 중"}
        return await native(execute, allow_led=True)

    @app.post("/api/bench/ocr/read")
    async def read_ocr(request: Request, body: OcrRead | None = None):
        permitted(request)
        models_ready()

        def execute():
            if not camera.status().get("connected"):
                raise Conflict("카메라를 먼저 연결하세요.")
            camera.verify_fixed_controls()
            with ocr_frame_lock:
                ocr_frame.update(id=None, image=None, diagnostics={})
            started = time.perf_counter()
            # The live test uses the frame already arriving from the camera.
            # Waiting for two more frames adds hundreds of milliseconds at low FPS.
            frame, timing = camera.read_latest()
            capture_ms = (time.perf_counter() - started) * 1000
            result = app.state.vision.test_auto(frame, locator=body.locator if body else "yolo26")
            result["timing"] = timing
            result["capture_ms"] = round(capture_ms, 1)
            result["processing_ms"] = round(
                (time.perf_counter() - started) * 1000 - capture_ms, 1
            )
            ident = str(uuid.uuid4())
            with ocr_frame_lock:
                ocr_frame.update(id=ident, image=frame, diagnostics=result.get("barcode_diagnostics", {}))
            result["image_views"] = view_options(result.get("barcode_diagnostics", {}))
            result["preview_url"] = "/api/bench/ocr/frames/" + ident
            result["original_url"] = result["preview_url"] + "?original=true"
            return result

        return await native(execute, allow_outputs=True, camera_only=True)

    @app.get("/api/bench/ocr/frames/{ident}")
    def ocr_image(ident: str, request: Request, original: bool = False, view: str = "original", region: int = 0):
        permitted(request)
        import cv2

        with ocr_frame_lock:
            if ident != ocr_frame["id"] or ocr_frame["image"] is None:
                raise HTTPException(410, "이전 검사 사진은 다음 검사에서 교체됩니다.")
            image = ocr_frame["image"]
            diagnostics = ocr_frame["diagnostics"]
        if view != "original":
            image = inspection_view(image, diagnostics, view, region)
        headers = {"Cache-Control": "no-store"}
        ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if original:
            headers["Content-Disposition"] = f'attachment; filename="ocr-frame-{ident}.png"'
        if not ok:
            raise HTTPException(500, "검사 사진을 표시하지 못했습니다.")
        return Response(encoded.tobytes(), media_type="image/png", headers=headers)

    @app.get("/api/bench/camera/devices")
    async def cameras():
        return await asyncio.to_thread(camera.backend.devices)

    @app.post("/api/bench/camera/inspect")
    async def inspect(body: Device, request: Request):
        permitted(request)
        # Reading the camera's controls is allowed during a trial so it can be tuned live.
        return await native(lambda: {**camera.inspect(body.device), "revision": camera.revision,
                                     "saved_profile": camera.saved}, allow_outputs=True, camera_only=True,
                            allow_test=True)

    @app.post("/api/bench/camera/apply")
    async def apply(body: CameraApply, request: Request):
        actor = permitted(request, ("admin",))
        def execute():
            if body.expected_revision is not None and body.expected_revision != camera.revision:
                raise Conflict("다른 화면에서 카메라 설정을 변경했습니다. 다시 불러오세요.")
            return camera.apply(body.profile, persist=body.save, actor=actor)
        current = camera.profile or {}
        # Control changes keep the capture running, so they are allowed during a
        # pipeline trial; a resolution or device change waits until it stops.
        same_mode = bool(current) and all(current.get(k) == getattr(body.profile, k)
                                          for k in ("device", "width", "height", "pixel_format")) \
            and abs(current.get("fps", 0) - body.profile.fps) < 0.05
        return await native(execute, allow_outputs=True, camera_only=True, allow_test=same_mode)

    @app.post("/api/bench/camera/connect")
    async def camera_connect(request: Request):
        permitted(request)
        return await native(camera.connect, allow_outputs=True, camera_only=True)

    @app.post("/api/bench/camera/disconnect")
    async def camera_disconnect(request: Request):
        permitted(request)
        def execute():
            camera.close()
            # Switched off on purpose: stay off after a restart too.
            store.put("camera_wanted", False)
            return camera.status()
        return await native(execute, allow_outputs=True, camera_only=True)

    @app.post("/api/bench/camera/capture")
    async def capture(request: Request):
        actor = permitted(request)
        def execute():
            import cv2
            controller.check_disk()
            camera.verify_fixed_controls()
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
        return await native(execute, allow_outputs=True, camera_only=True)

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
