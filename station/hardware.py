"""Single I/O owner for J2 and USB-TTL. No hardware is opened in REPLAY."""

from __future__ import annotations
import hashlib
import importlib
import importlib.util
import platform
import threading
import time
from pathlib import Path

from .rfid import Reader


class GpioIO:
    def __init__(self, config):
        if platform.system() != "Linux":
            raise RuntimeError("J2 실물 I/O는 Jetson Linux에서만 사용합니다.")
        if (
            config.do_on_raw is None
            or config.permit_line is None
            or config.permit_active_raw is None
        ):
            raise RuntimeError("출력 극성과 물리 운전 허가 관측 입력이 미확정입니다.")
        if config.permit_line in (*config.di_lines, *config.do_lines):
            raise RuntimeError("운전 허가 입력을 기존 DI/DO에 중복 배정할 수 없습니다.")
        if not config.commissioning.feedback_timeout_ms:
            raise RuntimeError("접촉기 응답 시간을 먼저 실측하세요.")
        import gpiod
        from gpiod.line import Direction, Value

        if not hasattr(gpiod, "request_lines"):
            raise RuntimeError("libgpiod Python 2.x API가 필요합니다.")
        self.config = config
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.Value = Value
        self.req = None
        self.reader = None
        self.thread = None
        self.fault = None
        self.requested = False
        self.led_requested = False
        self.changed = time.monotonic()
        self.last_lease = time.monotonic()
        self.permit_epoch = 0
        self.prior_permit = None
        self.latest = {}
        off = Value.ACTIVE if config.do_on_raw == 0 else Value.INACTIVE
        mapping = {
            line: gpiod.LineSettings(direction=Direction.INPUT)
            for line in (*config.di_lines, config.permit_line)
        }
        mapping.update(
            {
                line: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=off)
                for line in config.do_lines
            }
        )
        try:
            self.req = gpiod.request_lines(
                config.gpio_chip, consumer="inspection-io", config=mapping
            )
            self._read()
            if config.rfid_port:
                self.reader = Reader(config.rfid_port)
                if config.commissioning.rfid_protocol_verified:
                    self.reader.initialize()
            self.thread = threading.Thread(
                target=self._poll, daemon=True, name="inspection-io"
            )
            self.thread.start()
        except Exception:
            self.close()
            raise

    def _value(self, on):
        raw = self.config.do_on_raw if on else 1 - self.config.do_on_raw
        return self.Value.ACTIVE if raw else self.Value.INACTIVE

    def _outputs(self, motor, led):
        self.req.set_values(
            {
                self.config.do_lines[0]: self._value(motor),
                self.config.do_lines[1]: self._value(led),
            }
        )
        if motor != self.requested:
            self.changed = time.monotonic()
        self.requested = motor
        self.led_requested = led

    def _read(self):
        raw = [v.value for v in self.req.get_values(list(self.config.di_lines))]
        permit = (
            self.req.get_value(self.config.permit_line).value
            == self.config.permit_active_raw
        )
        if self.prior_permit is True and not permit:
            self.permit_epoch += 1
            self.fault = "MOTOR_PERMIT_LOST"
            self._outputs(False, False)
        self.prior_permit = permit
        self.latest = {
            "source": "HARDWARE",
            "connected": True,
            "motor_requested": self.requested,
            "led_requested": self.led_requested,
            "led_confirmed": None,
            "km2_on": raw[2] == 0,
            "di_raw": raw,
            "physical_permit": permit,
            "permit_epoch": self.permit_epoch,
            "observed_at": time.time(),
            "supports_en_reset": False,
            "fault": self.fault,
        }
        return self.latest

    def _poll(self):
        while not self.closed.wait(0.01):
            try:
                with self.lock:
                    snap = self._read()
                    if (
                        self.requested
                        and time.monotonic() - self.last_lease
                        > self.config.io_lease_ms / 1000
                    ):
                        self.fault = "IO_LEASE_EXPIRED"
                        self._outputs(False, False)
                    if (
                        time.monotonic() - self.changed
                        > self.config.commissioning.feedback_timeout_ms / 1000
                    ):
                        if self.requested and not snap["km2_on"]:
                            self.fault = "MOTOR_PERMIT_LOST"
                            self._outputs(False, False)
                        elif not self.requested and snap["km2_on"]:
                            self.fault = "KM2_FEEDBACK_STUCK"
                            self._outputs(False, False)
                    self.latest.update(
                        fault=self.fault,
                        motor_requested=self.requested,
                        led_requested=self.led_requested,
                    )
            except Exception as exc:
                self.fault = "IO_ACCESS_ERROR: " + str(exc)
                try:
                    self.stop()
                except Exception:
                    pass
                with self.lock:
                    self.latest.update(connected=False, fault=self.fault, km2_on=None)
                break

    def renew(self):
        self.last_lease = time.monotonic()

    def stop(self):
        with self.lock:
            if self.req:
                self._outputs(False, False)

    def motor(self, on, allowed=None):
        with self.lock:
            snap = self._read()
            if on and (self.fault or not snap["physical_permit"]):
                raise RuntimeError(self.fault or "물리 START 허가 없음")
            if on and allowed is not None and not allowed():
                raise RuntimeError("STOP_REQUEST_HAS_PRIORITY")
            self.last_lease = time.monotonic()
            self._outputs(on, self.led_requested)

    def light(self, on):
        with self.lock:
            snap = self._read()
            if on and (self.fault or not snap["physical_permit"]):
                raise RuntimeError("조명 운전 허가 없음")
            self._outputs(self.requested, on)

    def reset(self):
        with self.lock:
            self._outputs(False, False)
            snap = self._read()
            if snap["km2_on"] or not snap["physical_permit"]:
                raise RuntimeError("현장 정지/새 START 상태를 확인하세요.")
            if not self.snapshot().get("rfid_ready"):
                if self.reader:
                    try:
                        self.reader.close()
                    except Exception:
                        pass  # The unplugged descriptor may reject STOP.
                self.reader = Reader(self.config.rfid_port)
                if not self.config.commissioning.rfid_protocol_verified:
                    raise RuntimeError("RFID 프로토콜 실기 검증이 필요합니다.")
                self.reader.initialize()
            self.fault = None

    def snapshot(self):
        with self.lock:
            snap = dict(self.latest)
        if time.time() - snap.get("observed_at", 0) > 0.5:
            snap.update(connected=False, fault="IO_STALE")
        snap["rfid_connected"] = bool(
            self.reader
            and self.reader.port.is_open
            and Path(self.config.rfid_port).exists()
        )
        snap["rfid_ready"] = bool(snap["rfid_connected"] and self.reader.initialized)
        snap["rfid_error"] = self.reader.last_error if self.reader else None
        return snap

    def blockers(self):
        s = self.snapshot()
        return (
            (
                [s.get("fault") or "J2 연결 없음"]
                if not s.get("connected") or s.get("fault")
                else []
            )
            + ([] if s.get("physical_permit") else ["물리 START 허가 확인 필요"])
            + ([] if s.get("rfid_ready") else ["RFID 초기화·프로토콜 검증 필요"])
        )

    def inventory(self, window_ms, cancel):
        if not self.reader:
            raise RuntimeError("RFID 포트 없음")
        try:
            return self.reader.inventory(window_ms, cancel)
        except Exception as exc:
            self.reader.initialized = False
            self.reader.last_error = str(exc)
            raise

    def close(self):
        self.closed.set()
        try:
            self.stop()
        finally:
            if self.thread:
                self.thread.join(timeout=1)
            if self.reader:
                self.reader.close()
            if self.req:
                self.req.release()
                self.req = None


class Camera:
    def __init__(self, config):
        import cv2

        self.cv2 = cv2
        self.config = config
        self.lock = threading.Condition()
        self.closed = threading.Event()
        self.frame = None
        self.received_ns = 0
        self.seq = 0
        self.error = None
        self.started_ns = time.monotonic_ns()
        if not all((config.camera_width, config.camera_height, config.camera_fps)):
            raise RuntimeError("카메라 해상도·FPS 실측 설정이 필요합니다.")
        if config.camera_source not in ("CSI0", "CSI1"):
            raise RuntimeError("IMX219 카메라 실제 CSI0/CSI1 포트를 지정하세요.")
        pipeline = (
            f"nvarguscamerasrc sensor-id={config.camera_source[-1]} ! "
            f"video/x-raw(memory:NVMM),width={config.camera_width},height={config.camera_height},"
            f"framerate={config.camera_fps}/1,format=NV12 ! nvvidconv ! video/x-raw,format=BGRx ! "
            "videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false"
        )
        self.capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError("CSI 카메라를 열 수 없습니다.")
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="inspection-camera"
        )
        self.thread.start()

    def _run(self):
        while not self.closed.is_set():
            ok, img = self.capture.read()
            with self.lock:
                if not ok:
                    self.error = "CAMERA_DISCONNECTED"
                    self.lock.notify_all()
                    break
                self.frame = img
                self.seq += 1
                self.received_ns = time.monotonic_ns()
                self.lock.notify_all()

    def after(self, minimum_ns, timeout):
        deadline = time.monotonic() + timeout
        with self.lock:
            baseline = self.seq
            while self.received_ns <= minimum_ns or self.seq < max(10, baseline + 2):
                if self.closed.is_set():
                    raise RuntimeError("CAMERA_CLOSED")
                if self.error:
                    raise RuntimeError(self.error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("CAMERA_TIMEOUT")
                self.lock.wait(min(remaining, 0.1))
            return self.frame.copy(), {
                "seq": self.seq,
                "host_received_ns": self.received_ns,
                "sensor_timestamp": None,
            }

    def status(self):
        age = (
            (time.monotonic_ns() - self.received_ns) / 1e6 if self.received_ns else None
        )
        return {
            "connected": self.frame is not None
            and self.error is None
            and age < max(2000, 5000 / self.config.camera_fps),
            "frames": self.seq,
            "last_frame_age_ms": age,
            "error": self.error,
            "width": self.config.camera_width,
            "height": self.config.camera_height,
            "requested_fps": self.config.camera_fps,
            "mean_received_fps": self.seq
            / ((time.monotonic_ns() - self.started_ns) / 1e9),
            "dropped_frames": None,
            "source": self.config.camera_source,
        }

    def close(self):
        self.closed.set()
        with self.lock:
            self.lock.notify_all()
        self.capture.release()
        self.thread.join(timeout=1)


class ProductDetector:
    """Adapter contract for the user's existing product detector; never swaps models."""

    def __init__(self, module_name, expected_sha256):
        if not module_name or not expected_sha256:
            raise RuntimeError("제품 검출 라이브러리 연결이 필요합니다.")
        spec = importlib.util.find_spec(module_name)
        if not spec or not spec.origin:
            raise RuntimeError("제품 검출 모듈 없음")
        if (
            hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
            != expected_sha256
        ):
            raise RuntimeError("제품 검출 모듈 해시 불일치")
        self.module = importlib.import_module(module_name)
        if not callable(getattr(self.module, "detect_products", None)):
            raise RuntimeError("제품 검출기 detect_products(frame) 연결이 필요합니다.")

    def one(self, frame):
        products = self.module.detect_products(frame)
        if not isinstance(products, list) or len(products) != 1:
            raise RuntimeError("PRODUCT_COUNT_NOT_ONE")
        product = products[0]
        if not isinstance(product, dict) or product.get("present") is not True:
            raise RuntimeError("PRODUCT_DETECTION_INVALID")
        return product
