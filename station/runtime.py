"""Stop -> settle -> fresh capture -> one product -> parallel OCR/RFID -> disposition."""

from __future__ import annotations
import asyncio
import threading
import time
import uuid

from .schema import Command, Recipe
from .rules import decode_epc, RuleError, judge


class HardwareCycle:
    def __init__(self, controller, camera, detector, vision):
        self.c = controller
        self.io = controller.io
        self.camera = camera
        self.detector = detector
        self.vision = vision
        self.task = None
        self.cancel = threading.Event()
        self.eject_started = None
        self.exit_seen = False
        self.clear_since = None
        self.workers = 0
        self.worker_lock = threading.Lock()

    def worker_busy(self):
        with self.worker_lock:
            return self.workers > 0

    async def offload(self, function, *args):
        with self.worker_lock:
            self.workers += 1

        def run():
            try:
                return function(*args)
            finally:
                with self.worker_lock:
                    self.workers -= 1

        # Cancellation does not free readiness while a native/library call still runs.
        future = asyncio.get_running_loop().run_in_executor(None, run)
        return await asyncio.shield(future)

    def blockers(self):
        cfg = self.c.config
        reasons = []
        if self.worker_busy():
            reasons.append("이전 장비/검출 라이브러리 작업 종료 대기")
        if self.camera is None:
            reasons.append("카메라 연결·실측 설정 필요")
        elif (
            not self.camera.status()["connected"] or self.camera.status()["frames"] < 10
        ):
            reasons.append("카메라 예열/연결 확인 필요")
        if self.detector is None:
            reasons.append("제품 검출 라이브러리 연결 필요")
        if self.vision.status().get("busy"):
            reasons.append("이전 영상 처리 종료 대기")
        if not cfg.rfid_window_ms:
            reasons.append("RFID 읽기 시간 실측 필요")
        if cfg.commissioning.product_sensor == cfg.commissioning.departure_sensor:
            reasons.append("검사/배출 센서 역할 구분 필요")
        s = self.c.session
        if s and "ocr" in s["recipe"]["channels"]:
            if not self.vision.status()["local_assets_present"]:
                reasons.append("로컬 OCR 모델 필요")
        return reasons

    async def tick(self):
        s = self.c.snapshot()["session"]
        if not s:
            return
        phase = s["phase"]
        cfg = self.c.config.commissioning
        snap = self.io.snapshot()
        active = phase not in (
            "READY",
            "PAUSED",
            "DONE",
            "FINISHED",
            "ABORTED",
            "FAULT",
            "HOLD",
        )
        if active and (snap.get("fault") or not snap.get("connected")):
            self.cancel.set()
            self.c.fault(snap.get("fault") or "IO_DISCONNECTED")
            return
        if active and (
            snap.get("rfid_connected") is False or snap.get("rfid_ready") is False
        ):
            self.cancel.set()
            self.c.fault("RFID_DISCONNECTED")
            return
        if self.camera and not self.camera.status()["connected"] and active:
            self.cancel.set()
            self.c.fault(self.camera.error or "CAMERA_STALE")
            return
        if phase in ("FAULT", "PAUSED", "HOLD", "ABORTED", "FINISHED"):
            self.cancel.set()
        if self.task and self.task.done():
            try:
                self.task.result()
            except Exception as exc:
                self.c.fault("INSPECTION_ERROR: " + str(exc))
            self.task = None
        raw = snap.get("di_raw")
        if raw is None or not cfg.product_sensor or not cfg.departure_sensor:
            return
        if (
            phase in ("FEEDING", "RETRY_PENDING")
            and self.task is None
            and raw[cfg.product_sensor - 1] == cfg.sensor_active_raw
        ):
            self.cancel.clear()
            self.task = asyncio.create_task(self.cycle())
        elif phase == "PASSED" and self.c.config.automatic_cycle and self.task is None:
            self.issue("release")
            self.eject_started = time.monotonic()
            self.exit_seen = False
            self.clear_since = None
        elif phase == "EJECTING":
            if self.eject_started is None:
                self.eject_started = time.monotonic()
            self.exit_seen = (
                self.exit_seen or raw[cfg.departure_sensor - 1] == cfg.sensor_active_raw
            )
            clear = all(v != cfg.sensor_active_raw for v in raw[:2])
            self.clear_since = (
                (self.clear_since or time.monotonic())
                if clear and self.exit_seen
                else None
            )
            if (
                self.clear_since
                and time.monotonic() - self.clear_since >= cfg.sensor_clear_ms / 1000
            ):
                self.c.departed()
                self.eject_started = None
                if self.c.session["phase"] == "READY" and self.c.config.automatic_cycle:
                    self.issue("start")
            elif time.monotonic() - self.eject_started > cfg.release_timeout_ms / 1000:
                self.c.fault("PRODUCT_DEPARTURE_TIMEOUT")
                self.eject_started = None
        else:
            self.eject_started = None
            self.exit_seen = False
            self.clear_since = None

    def issue(self, action):
        self.c.command(
            Command(
                request_id=str(uuid.uuid4()),
                session_id=self.c.session["id"],
                action=action,
                expected_revision=self.c.revision,
                issued_at=time.time(),
                reason="검사 주기 진행",
            ),
            "automatic-cycle",
        )

    def still_valid(self, epoch):
        if self.cancel.is_set() or self.c.epoch != epoch:
            raise RuntimeError("INSPECTION_CANCELLED")

    async def cycle(self):
        cfg = self.c.config.commissioning
        product_id = self.c.session["active_product"] or str(uuid.uuid4())
        inspection, epoch, brand = self.c.begin(product_id, physical=True)
        recipe = Recipe.model_validate(inspection["recipe"])
        observations = {}
        failures = []
        frame = timing = product = None

        async def inspect():
            nonlocal frame, timing, product
            off_deadline = time.monotonic() + cfg.feedback_timeout_ms / 1000
            while True:
                self.still_valid(epoch)
                snap = self.io.snapshot()
                if not snap.get("connected") or snap.get("fault"):
                    raise RuntimeError("IO_ACCESS_ERROR")
                if snap.get("km2_on") is False:
                    break
                if time.monotonic() > off_deadline:
                    raise RuntimeError("KM2_FEEDBACK_STUCK")
                await asyncio.sleep(0.01)
            self.io.light(True)
            await asyncio.sleep(cfg.settle_ms / 1000)
            self.still_valid(epoch)
            self.c.inspecting(epoch)
            frame, timing = await self.offload(
                self.camera.after, time.monotonic_ns(), cfg.inspection_timeout_ms / 1000
            )
            product = await self.offload(self.detector.one, frame)
            self.still_valid(epoch)
            jobs = []
            names = []
            if "rfid" in recipe.channels:
                jobs.append(
                    self.offload(
                        self.io.inventory, self.c.config.rfid_window_ms, self.cancel
                    )
                )
                names.append("rfid")
            if any(x in recipe.channels for x in ("ocr", "barcode")):
                jobs.append(
                    self.offload(
                        self.vision.inspect_frame, frame, brand, recipe,
                        self.c.session.get("ocr_correction", {}),
                    )
                )
                names.append("vision")
            tasks = {asyncio.create_task(job): name for name, job in zip(names, jobs)}
            pending = set(tasks)
            try:
                while pending:
                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                    self.still_valid(epoch)
                    for task in done:
                        name = tasks[task]
                        try:
                            result = task.result()
                        except Exception as exc:
                            failures.append(
                                {"code": name.upper() + "_ERROR", "detail": str(exc)}
                            )
                            continue
                        if name == "rfid":
                            inspection["rfid"] = result
                            if len(result) != 1:
                                failures.append(
                                    {
                                        "code": (
                                            "RFID_MISSING"
                                            if not result
                                            else "MULTIPLE_RFID_TAGS"
                                        )
                                    }
                                )
                            else:
                                try:
                                    observations["rfid"] = decode_epc(
                                        brand, result[0]["epc"]
                                    )
                                except RuleError as exc:
                                    failures.append({"code": str(exc)})
                            checked = ["rfid"]
                        else:
                            observations.update(result["observations"])
                            failures.extend(result["failures"])
                            inspection["vision"] = result
                            checked = [
                                c for c in recipe.channels if c in ("ocr", "barcode")
                            ]
                        failures.extend(
                            judge(
                                recipe.model_copy(update={"channels": checked}),
                                observations,
                            )
                        )
                    if failures:
                        # Motor is already OFF. Publish HOLD without waiting for a slower channel.
                        # A non-cancellable inference thread retains Vision's busy lock until it ends.
                        self.cancel.set()
                        break
            finally:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        try:
            await asyncio.wait_for(inspect(), timeout=cfg.inspection_timeout_ms / 1000)
        except asyncio.TimeoutError:
            self.cancel.set()
            failures.append({"code": "INSPECTION_TIMEOUT"})
        except BaseException as exc:
            self.cancel.set()
            failures.append({"code": "INSPECTION_ERROR", "detail": str(exc)})
        evidence = None
        writer = None
        if frame is not None:
            from .evidence import save_frame

            evidence = {
                "source": "CSI_CAMERA",
                "timing": timing,
                "product_detection": product,
            }

            def writer():
                return save_frame(
                    self.c.store.root, inspection["id"], frame, timing, product
                )

        await self.offload(
            self.c.complete, inspection, epoch, observations, failures, evidence, writer
        )

    async def close(self):
        self.cancel.set()
        self.c.stop_outputs()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
