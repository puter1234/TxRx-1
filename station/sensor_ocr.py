"""Moving-conveyor OCR trial: sensor edges, independent capture, serial OCR.

Images stay in RAM. This trial never writes production inspection counts.
Frame identity uses camera sequence and host receipt time, not pixel equality.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Literal

import psutil
from pydantic import Field, model_validator

from .controller import Conflict
from .schema import Model


class SensorOcrSettings(Model):
    conveyor_sync: bool = False
    low_speed_ms: int = Field(default=500, ge=0, le=60000)
    capture_delay_ms: int = Field(default=100, ge=0, le=60000)
    capture_interval_ms: int = Field(default=100, ge=0, le=10000)
    departure_timeout_ms: int = Field(default=10000, ge=100, le=120000)
    frame_count: int = Field(default=3, ge=1, le=100)
    sensor_channel: int = Field(default=1, ge=1, le=2)
    active_raw: int = Field(default=0, ge=0, le=1)
    pattern: str = Field(default="", max_length=160)
    locator: Literal["yolo26", "stripes", "opencv"] = "yolo26"

    @model_validator(mode="after")
    def valid_pattern(self):
        if self.conveyor_sync:
            if self.sensor_channel != 1 or self.active_raw != 0:
                raise ValueError("컨베이어 연동은 DI1의 입력 0에서 시작합니다.")
            last_capture = self.capture_delay_ms + (self.frame_count - 1) * self.capture_interval_ms
            if last_capture >= self.departure_timeout_ms:
                raise ValueError("마지막 촬영은 DI2 도착 제한 시간보다 빨라야 합니다.")
        # Only fixed-length character classes/literals are accepted. No nested
        # quantifiers, lookarounds, or unbounded expressions in the OCR worker.
        if self.pattern:
            token = r"(?:\[[A-Za-z0-9\-]+\]|[A-Za-z0-9])(?:\{[1-9][0-9]?\})?"
            if not re.fullmatch(f"(?:{token})+", self.pattern):
                raise ValueError("형식은 영문, 숫자, [A-Z], [0-9], [A-Z0-9], {글자 수}로 지정하세요.")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError("상품코드 형식을 확인하세요.") from exc
        return self


class SensorOcrTest:
    def __init__(self, bench, camera, vision):
        self.bench, self.camera, self.vision = bench, camera, vision
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.cancel = threading.Event()
        self.active = False
        self.error = None
        self.settings = SensorOcrSettings()
        if hasattr(bench, "store"):
            self.settings = SensorOcrSettings.model_validate(
                bench.store.get("sensor_ocr_settings", {"conveyor_sync": True}))
            # Upgrade the existing trial to the installed models once. Later
            # explicit comparisons with the older locators remain saved.
            if not bench.store.get("sensor_ocr_yolo26_enabled", False):
                self.settings = self.settings.model_copy(update={"locator": "yolo26"})
                bench.store.put("sensor_ocr_settings", self.settings.model_dump())
                bench.store.put("sensor_ocr_yolo26_enabled", True)
        self.jobs = []
        self.detected = self.count = self.passed = self.failed = 0
        self.bytes_used = self.budget = 0
        self.physical = None
        self.await_clear = False
        self.sensor_raw = None
        self.capture_thread = self.ocr_thread = None
        self.latest_seq = 0
        self.run_id = ""
        self.raw_inputs = None
        self.speed_deadline_ns = None
        self.output_serial = None
        bench.input_listeners.append(self.edge)
        bench.stop_listeners.append(self.cancel_run)
        if hasattr(bench, "tick_listeners"):
            bench.tick_listeners.append(self.control_tick)

    def save_settings(self, settings):
        with self.bench.lock:
            if self.busy():
                raise Conflict("시험을 정지한 뒤 설정을 저장하세요.")
            self.bench.store.put("sensor_ocr_settings", settings.model_dump())
            self.settings = settings
            return settings.model_dump()

    def busy(self):
        return self.active or any(t and t.is_alive() for t in (self.capture_thread, self.ocr_thread))

    def start(self, settings):
        serial = getattr(self.bench, "stop_serial", None)
        if hasattr(self.camera, "verify_fixed_controls"):
            self.camera.verify_fixed_controls()
        status = self.camera.status()
        if not status.get("connected"):
            raise Conflict("카메라를 먼저 연결하세요.")
        profile = status.get("profile") or {}
        width, height = status.get("width") or profile.get("width"), status.get("height") or profile.get("height")
        if not width or not height:
            raise Conflict("카메라 해상도를 확인할 수 없습니다.")
        if hasattr(self.vision, "prepare_capture"):
            self.vision.prepare_capture(status, settings.locator)
        budget = min(1024**3, int(psutil.virtual_memory().available * 0.25))
        maximum = min(100, budget // (int(width) * int(height) * 3))
        if settings.frame_count > maximum:
            raise Conflict(f"현재 해상도와 메모리에서는 최대 {maximum}프레임까지 지정할 수 있습니다.")
        with self.bench.lock:
            if self.busy():
                raise Conflict("이전 파이프라인 시험이 끝나는 중입니다.")
            if self.bench.cancel.is_set():
                raise Conflict("시험 시작이 취소되었습니다.")
            if not self.bench.io:
                raise Conflict("센서 입력 연결을 먼저 시작하세요.")
            raw = self.bench.io.snapshot().get("di_raw")
            if not raw or len(raw) < 2:
                raise Conflict("센서 입력값을 읽을 수 없습니다.")
            if settings.conveyor_sync:
                if self.bench.config.speed_line is None:
                    raise Conflict("이 장비의 DO4 연결 정보가 없습니다.")
                if raw[:2] != [1, 1]:
                    raise Conflict("DI1과 DI2 앞의 제품을 정리한 뒤 시작하세요.")
                if self.bench.runs:
                    raise Conflict("수동 출력 시험을 정지한 뒤 연동 시험을 시작하세요.")
            try:
                for target in (("motor",) if settings.conveyor_sync else ("motor", "led")):
                    if target not in self.bench.runs:
                        self.bench.pulse(target, None, self.bench.generation, str(uuid.uuid4()), time.time(), expected_serial=serial)
                with self.lock:
                    self.settings = settings
                    self.raw_inputs = list(raw)
                    self.speed_deadline_ns = None
                    self.output_serial = serial
                    if settings.conveyor_sync:
                        self.bench.sequence_output("led", False, self.output_serial)
                        self.bench.sequence_output("speed", True, self.output_serial)
                    self.pattern = re.compile(settings.pattern) if settings.pattern else None
                    self.jobs = []
                    self.bytes_used, self.budget = 0, budget
                    self.detected = self.count = self.passed = self.failed = 0
                    self.physical = None
                    self.sensor_raw = raw[settings.sensor_channel - 1]
                    self.await_clear = self.sensor_raw == settings.active_raw
                    self.latest_seq = int(status.get("frames", 0))
                    self.frame_bytes = int(width) * int(height) * 3
                    self.fps = float(profile.get("fps") or status.get("requested_fps") or 10)
                    self.run_id = str(uuid.uuid4())
                    self.error = None
                    self.cancel.clear()
                    self.active = True
                    self.capture_thread = threading.Thread(target=self._capture, daemon=True, name="sensor-frame-capture")
                    self.ocr_thread = threading.Thread(target=self._ocr, daemon=True, name="sensor-frame-ocr")
                    self.capture_thread.start()
                    self.ocr_thread.start()
            except Exception:
                self.bench.stop("파이프라인 시험 시작 실패")
                raise
        return self.status()

    def edge(self, channel, raw, observed_ns):
        # Called from the existing input watchdog. Never copy images or run OCR here.
        if self.settings.conveyor_sync:
            with self.bench.lock:
                with self.lock:
                    self._conveyor_edge(channel, raw, observed_ns)
            return
        with self.lock:
            if not self.active or channel != self.settings.sensor_channel:
                return
            self.sensor_raw = raw
            if raw != self.settings.active_raw:
                self.await_clear = False
                if self.physical is not None:
                    self.physical["counted"] = True
                    self.physical["released_ns"] = observed_ns
                    self.count += 1
                    self.physical = None
                return
            if self.await_clear or self.physical is not None:
                return
            for prior in self.jobs:
                if prior["collecting"]:
                    prior["collecting"] = False
                    prior["capture_error"] = "다음 제품 감지로 프레임 수집 종료"
            self.detected += 1
            job = {"id": str(uuid.uuid4()), "number": self.detected,
                   "trigger_ns": observed_ns, "released_ns": None, "counted": False,
                   "collecting": True, "state": "waiting", "frames": [],
                   "baseline_seq": int(self.camera.status().get("frames", self.latest_seq)), "missed_frames": 0,
                   "capture_error": None, "matched_text": None}
            self.jobs.append(job)
            self.physical = job
            self.wake.set()

    def _conveyor_edge(self, channel, raw, observed_ns):
        if not self.active or channel not in (1, 2):
            return
        previous = self.raw_inputs[channel - 1]
        self.raw_inputs[channel - 1] = raw
        self.sensor_raw = self.raw_inputs[0]
        if raw != 0 or previous == 0:
            return
        if channel == 2:
            self.bench.sequence_output("led", False, self.output_serial)
            if self.physical is None:
                self._fail("DI1 감지 없이 DI2가 감지됐습니다.")
                return
            job = self.physical
            job.update(counted=True, released_ns=observed_ns)
            last_due_ms = (self.settings.capture_delay_ms
                           + (self.settings.frame_count - 1) * self.settings.capture_interval_ms)
            job["capture_timing"] = {
                "planned_last_ms": last_due_ms,
                "di2_after_trigger_ms": round((observed_ns - job["trigger_ns"]) / 1e6, 2),
            }
            self.count += 1
            self.physical = None
            if job["collecting"] and observed_ns < job["trigger_ns"] + last_due_ms * 1_000_000:
                job["capture_error"] = "DI2가 촬영 예정 시각보다 먼저 감지됐습니다."
                self._fail(job["capture_error"])
            # A frame received before DI2 can still be in the shared-memory
            # copy. The capture worker checks its receipt timestamp against
            # released_ns before accepting it. Never equate an unfinished copy
            # with a missed acquisition, or accept a frame received after DI2.
            self.wake.set()
            return
        self.bench.sequence_output("led", True, self.output_serial)
        self.bench.sequence_output("speed", False, self.output_serial)
        self.speed_deadline_ns = observed_ns + self.settings.low_speed_ms * 1_000_000
        if self.physical is not None:
            self._fail("이전 제품이 DI2를 통과하기 전에 다음 제품이 감지됐습니다.")
            return
        self.detected += 1
        job = {"id": str(uuid.uuid4()), "number": self.detected,
               "trigger_ns": observed_ns, "released_ns": None, "counted": False,
               "collecting": True, "state": "waiting", "frames": [],
               "baseline_seq": self.latest_seq, "missed_frames": 0,
               "capture_error": None, "matched_text": None}
        self.jobs.append(job)
        self.physical = job
        self.wake.set()

    def control_tick(self, now_ns):
        # Called by Bench under its I/O lock, independent of capture and OCR.
        with self.lock:
            if not self.active or not self.settings.conveyor_sync:
                return
            if self.speed_deadline_ns is not None and now_ns >= self.speed_deadline_ns:
                self.bench.sequence_output("speed", True, self.output_serial)
                self.speed_deadline_ns = None
            if self.physical and now_ns - self.physical["trigger_ns"] >= self.settings.departure_timeout_ms * 1_000_000:
                self._fail("설정한 시간 안에 DI2가 감지되지 않았습니다.")

    def cancel_run(self, reason="시험 중지"):
        with self.lock:
            self.active = False
            self.cancel.set()
            self.speed_deadline_ns = None
            for job in self.jobs:
                job["collecting"] = False
                if job["state"] in ("waiting", "reading"):
                    job["state"] = "cancelled"
            self.wake.set()

    def _fail(self, message):
        with self.lock:
            self.error = str(message)
        self.bench.stop(str(message))

    def _make_space(self, size):
        # Evict finished images, keeping their results. Never evict a queued or
        # currently processed frame to make a backlog appear successful.
        for old in self.jobs:
            if self.bytes_used + size <= self.budget:
                break
            if old["collecting"] or old["state"] in ("waiting", "reading"):
                continue
            for frame in old["frames"]:
                if frame["image"] is not None:
                    self.bytes_used -= frame["image"].nbytes
                    frame["image"] = None
                    frame["crops"] = []
        if self.bytes_used + size > self.budget:
            raise RuntimeError("OCR 대기 프레임이 메모리 한도를 넘었습니다. 프레임 수나 투입 속도를 줄이세요.")

    def _capture(self):
        last_delivered = self.latest_seq
        last_checked = last_delivered
        try:
            while not self.cancel.wait(0.002):
                status = self.camera.status()
                if not status.get("connected"):
                    raise RuntimeError("파이프라인 시험 중 카메라 연결 끊김")
                with self.lock:
                    self.latest_seq = int(status.get("frames", self.latest_seq))
                    job = next((j for j in self.jobs if j["collecting"]), None)
                    if job is None:
                        continue
                    delay_ms = (self.settings.capture_delay_ms + len(job["frames"]) * self.settings.capture_interval_ms
                                if self.settings.conveyor_sync else 0)
                    due_ns = job["trigger_ns"] + delay_ms * 1_000_000
                    last_delay_ms = (self.settings.capture_delay_ms + (self.settings.frame_count - 1) * self.settings.capture_interval_ms
                                     if self.settings.conveyor_sync else 0)
                    limit = last_delay_ms / 1000 + max(2.0, 2 * self.settings.frame_count / self.fps + 1)
                    if (time.monotonic_ns() - job["trigger_ns"]) / 1e9 > limit:
                        job["collecting"] = False
                        job["capture_error"] = "새 프레임 수집 시간 초과"
                        self.wake.set()
                        continue
                    if self.latest_seq <= max(last_checked, job["baseline_seq"]) or time.monotonic_ns() < due_ns:
                        continue
                copy_started = time.monotonic_ns()
                image, meta = self.camera.read_latest()
                copy_finished = time.monotonic_ns()
                seq, received = int(meta["seq"]), int(meta["host_received_ns"])
                # A rejected pre-due frame must not be copied again every 2 ms.
                # At 48MP that repeatedly copies 144 MB while waiting for the
                # next camera publication and competes with the capture writer.
                last_checked = max(last_checked, seq)
                # A newer sequence is mandatory even on hosts whose monotonic
                # clock gives two receipts the same timestamp.
                if seq <= max(last_delivered, job["baseline_seq"]) or received < due_ns:
                    continue
                with self.lock:
                    if not self.active or not job["collecting"]:
                        continue
                    if self.settings.conveyor_sync and job["released_ns"] is not None and received > job["released_ns"]:
                        job["collecting"] = False
                        job["capture_error"] = "DI2 도착 전 촬영 프레임을 확보하지 못했습니다."
                        job["capture_timing"].update(
                            rejected_frame_after_trigger_ms=round((received - job["trigger_ns"]) / 1e6, 2))
                        raise RuntimeError(job["capture_error"])
                    self._make_space(image.nbytes)
                    previous = job["frames"][-1]["seq"] if job["frames"] else job["baseline_seq"]
                    if not self.settings.conveyor_sync:
                        job["missed_frames"] += max(0, seq - previous - 1)
                    job["frames"].append({"seq": seq, "received_ns": received,
                        "camera_settings_revision": meta.get("camera_settings_revision"),
                        "camera_profile": meta.get("camera_profile"),
                        "after_trigger_ms": round((received - job["trigger_ns"]) / 1e6, 2),
                        "copy_ms": round((copy_finished - copy_started) / 1e6, 2),
                        "registered_after_trigger_ms": round((time.monotonic_ns() - job["trigger_ns"]) / 1e6, 2),
                        "image": image, "crops": [], "result": None,
                        "state": "skipped" if job["state"] == "passed" else "waiting"})
                    self.bytes_used += image.nbytes
                    last_delivered = seq
                    if len(job["frames"]) == self.settings.frame_count:
                        job["collecting"] = False
                    self.wake.set()
        except Exception as exc:
            self._fail(exc)

    def _ocr(self):
        try:
            while not self.cancel.is_set():
                selected = None
                capture_failure = None
                with self.lock:
                    for job in self.jobs:
                        if job["state"] not in ("waiting", "reading"):
                            continue
                        frame = next((f for f in job["frames"] if f["state"] == "waiting"), None)
                        if frame is not None:
                            frame["state"] = job["state"] = "reading"
                            selected = job, frame
                            break
                        if not job["collecting"]:
                            # A completed OCR miss is a trial result, not a motor
                            # stop. Acquisition failures still stop linked runs.
                            job["state"] = "failed"
                            self.failed += 1
                            if job["capture_error"]:
                                capture_failure = job["capture_error"]
                    # Bound result history as well as image memory.
                    while len(self.jobs) > 20 and self.jobs[0] is not self.physical:
                        first = self.jobs[0]
                        if first["collecting"] or first["state"] in ("waiting", "reading"):
                            break
                        for f in first["frames"]:
                            if f["image"] is not None:
                                self.bytes_used -= f["image"].nbytes
                        self.jobs.pop(0)
                if capture_failure and self.settings.conveyor_sync:
                    self._fail(capture_failure)
                    return
                if selected is None:
                    self.wake.wait(0.05)
                    self.wake.clear()
                    continue
                job, frame = selected
                crops = []
                result = self.vision.test_auto(frame["image"], include_previews=False, crop_images=crops,
                                               locator=self.settings.locator)
                texts = [line["text"] for read in result["reads"] for line in read["lines"] if line["text"].strip()]
                matched = next((text for text in texts if self.pattern is None or
                                self.pattern.fullmatch(re.sub(r"\s+", "", text))), None)
                with self.lock:
                    if self.cancel.is_set():
                        break
                    frame.update(result=result, crops=crops, state="passed" if matched is not None else "no_match")
                    if matched is not None:
                        job.update(state="passed", matched_text=matched)
                        self.passed += 1
                        for pending in job["frames"]:
                            if pending["state"] == "waiting":
                                pending["state"] = "skipped"
                    else:
                        job["state"] = "waiting"
        except Exception as exc:
            self._fail(exc)

    def status(self, details=True):
        with self.lock:
            result = {"active": self.active, "busy": self.busy(), "error": self.error,
                      "run_id": self.run_id, "settings": self.settings.model_dump(),
                      "detected": self.detected, "count": self.count, "passed": self.passed,
                      "failed": self.failed, "sensor_raw": self.sensor_raw,
                      "await_clear": self.await_clear, "memory_bytes": self.bytes_used,
                      "memory_limit_bytes": self.budget,
                      "di_raw": self.raw_inputs}
            if details:
                result["jobs"] = [{k: v for k, v in job.items() if k not in ("frames", "baseline_seq")} |
                    {"frames": [{k: v for k, v in frame.items() if k not in ("image", "crops")} |
                     {"image_available": frame["image"] is not None, "crop_count": len(frame["crops"])}
                     for frame in job["frames"]]} for job in reversed(self.jobs)]
            return result

    def diagnostics(self, job_id, sequence):
        with self.lock:
            for job in self.jobs:
                if job["id"] == job_id:
                    for frame in job["frames"]:
                        if frame["seq"] == sequence:
                            return (frame["result"] or {}).get("barcode_diagnostics", {})
        return {}

    def image(self, job_id, sequence, crop=None):
        with self.lock:
            for job in self.jobs:
                if job["id"] == job_id:
                    for frame in job["frames"]:
                        if frame["seq"] == sequence:
                            if crop is None:
                                return frame["image"]
                            if 0 <= crop < len(frame["crops"]):
                                return frame["crops"][crop]
            return None

    def close(self):
        self.cancel_run()
        for thread in (self.capture_thread, self.ocr_thread):
            if thread:
                thread.join(timeout=5)
