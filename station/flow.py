"""DI1-triggered moving inspection. Timers share one monotonic origin."""
from __future__ import annotations
import asyncio
import time
import uuid

from .runtime import HardwareCycle
from .schema import FlowSettings, Recipe, loose
from .rules import decode_epc, judge, RuleError
from .counting import ObjectCounter, file_sha256
from .storage import utc


RFID_RECONNECT_GAP_S = 0.5

class SensorEdge:
    """Require a stable clear input to arm; one event until the next clear."""
    def __init__(self):
        self.value = None
        self.changed = 0.0
        self.armed = False
        self.fired = False

    def update(self, raw, now, debounce_ms, gap_ms=0):
        if raw != self.value:
            self.value, self.changed = raw, now
        if now - self.changed + 1e-9 < debounce_ms / 1000:
            return False
        if raw == 1:
            # Only a clear lasting the sensor gap ends a product; a shorter one
            # followed by a new detection is still the same product.
            if now - self.changed + 1e-9 >= gap_ms / 1000:
                self.armed, self.fired = True, False
        elif raw == 0 and self.armed and not self.fired:
            self.fired, self.armed = True, False
            return True
        return False


class FlowCycle(HardwareCycle):
    def __init__(self, controller, camera, detector, vision):
        super().__init__(controller, camera, detector, vision)
        self.pending = None
        self.session_id = None
        self.edges = [SensorEdge(), SensorEdge()]
        self.raw_previous = None
        self.counter = None
        self.counter_error = None
        self.counter_key = None
        self.camera_task = None
        self.rfid_task = None
        self.rfid_reconnect = None
        self.rfid_misses = 0
        self.track_task = None
        self.reconnect_task = None
        self.finish_task = None
        self.next_retry = 0
        self.reconnect_ok = False
        self.wait_started = None
        self.resume_serial = None
        self.last_sequence = None
        self.speed_deadline = None
        self.speed_serial = 0
        self.bulk_started = False

    def flow(self):
        return FlowSettings.model_validate(self.c.session["recipe"]["flow"])

    def camera_required(self):
        recipe = (self.c.session or {}).get("recipe", {})
        return bool(set(recipe.get("channels", [])) & {"ocr", "barcode"}) or (recipe.get("flow") or {}).get("counter", "sensor") != "sensor"

    def prepare(self, recipe):
        cfg = FlowSettings.model_validate(recipe["flow"])
        key = cfg.model_dump_json()
        if cfg.counter == "yolo":
            from .schema import wappen_model_path
            path = wappen_model_path(cfg.model_path)
            if not path.is_file():
                raise ValueError("YOLO 모델 파일을 확인하세요: " + str(path))
            key += file_sha256(path)
        if key != self.counter_key:
            self.counter = None
            self.counter_key = None
            self.counter_error = None
            try:
                if cfg.counter != "sensor":
                    self.counter = ObjectCounter(cfg)
                self.counter_key = key
            except Exception as exc:
                self.counter_error = str(exc)
                raise

    def blockers(self):
        recipe = (self.c.session or {}).get("recipe", {})
        if not recipe.get("flow"):
            return super().blockers()
        reasons = []
        session = self.c.session
        if session["phase"] in ("READY", "PAUSED") and recipe.get("kind") != "vision" and (
                self.session_id != session["id"] or
                not all(edge.armed and edge.value == 1 for edge in self.edges)):
            reasons.append("DI1과 DI2의 해제 신호를 확인 중입니다.")
        if self.worker_busy():
            reasons.append("장비 처리 종료 대기")
        if self.camera_required() and (not self.camera or not self.camera.status().get("connected")):
            reasons.append("카메라 연결을 확인하세요.")
        if self.counter_error:
            reasons.append(self.counter_error)
        if recipe["flow"]["counter"] != "sensor" and self.counter is None:
            reasons.append("계수 모델을 불러오세요.")
        # A reader that is not ready never blocks a start; the job reopens it and reads.
        if "ocr" in recipe["channels"] and not self.vision.status().get("local_assets_present"):
            reasons.append("OCR 모델을 확인하세요.")
        if set(recipe.get("channels", [])) & {"ocr", "barcode"} and self.camera and hasattr(self.vision, "source_error"):
            error = self.vision.source_error(self.camera.status())
            if error:
                reasons.append(error)
        return reasons

    def event(self, kind, body=None):
        with self.c.lock:
            self.c.changed(kind, body)

    def live(self):
        p = self.pending
        return p and p["epoch"] == self.c.epoch and not self.cancel.is_set()

    def fail(self, code, detail=""):
        if self.pending:
            self.pending["failures"].append({"code": code, "detail": detail})
        self.c.stop_outputs()

    async def tick(self):
        s = self.c.session
        if not s or not s["recipe"].get("flow"):
            return await super().tick()
        now = time.monotonic()
        tick_serial = self.c.stop_serial
        cfg = self.flow()
        # Wappens are poured onto the belt in bulk: the camera counts every
        # line crossing while the belt runs, and the sensors play no part.
        bulk = s["recipe"].get("kind") == "vision"
        if self.session_id != s["id"]:
            self.session_id = s["id"]
            self.speed_deadline = None
            self.resume_serial = None
            self.edges = [SensorEdge(), SensorEdge()]
            self.raw_previous = None
            self.last_sequence = None
            self.c.tracking = None
            self.bulk_started = False
            if self.counter:
                from .counting import CrossingTracker
                self.counter.tracker = CrossingTracker(cfg)
        if self.finish_task and self.finish_task.done():
            finished, self.finish_task = self.finish_task, None
            finished.result()
        snap = self.io.snapshot()
        raw = snap.get("di_raw")
        hits = [False, False]
        if raw:
            # The same gap between products takes longer to pass the sensor at low speed.
            gap = cfg.sensor_gap_low_ms if snap.get("speed_requested") is False else cfg.sensor_gap_ms
            hits = [self.edges[i].update(raw[i], now, getattr(cfg, f"di{i + 1}_debounce_ms"), gap)
                    for i in range(2)]
            # Light is controlled by raw sensor edges, independent of inference/debounce.
            # Plain sensor counting reads nothing on the belt: no light, no slow-down.
            inspects = self.camera_required() or "rfid" in s["recipe"].get("channels", [])
            if s["phase"] in ("FEEDING", "CAMERA_WAIT") and inspects and not bulk:
                if raw[0] == 0 and self.raw_previous and self.raw_previous[0] != 0:
                    self.io.light(True, allowed=lambda: tick_serial == self.c.stop_serial and not self.c.pending_stops)
                    self.io.speed(False)
                    self.speed_deadline = now + cfg.low_speed_ms / 1000
                    self.speed_serial = tick_serial
                if raw[1] == 0 and self.raw_previous and self.raw_previous[1] != 0:
                    self.io.light(False)
            self.raw_previous = list(raw)
        if bulk:
            hits = [False, False]
        run_out = self.c.run_out
        if run_out is not None:
            # The target's last product passed DI2 on a moving belt; carry it off,
            # but stop at once for anything new at DI1 or any other change.
            run_out.setdefault("until", now + run_out["ms"] / 1000)
            if s["phase"] != "DONE" or hits[0] or now >= run_out["until"]:
                self.c.stop_outputs()
                if self.c.stop_fault and s["phase"] == "DONE":
                    with self.c.lock:
                        s.update(phase="FAULT", fault="IO_STOP_UNCONFIRMED")
                        self.c.changed("FAULT", {"reason": "IO_STOP_UNCONFIRMED"})
        if s["phase"] not in ("FEEDING", "CAMERA_WAIT"):
            self.cancel.set()
            self.resume_serial = None
            self.speed_deadline = None
            self.bulk_started = False
            if bulk and self.track_task:
                # Frames read before the stop never count after it.
                self.track_task.cancel()
                await asyncio.gather(self.track_task, return_exceptions=True)
                self.track_task = None
            if self.pending and self.finish_task is None:
                self.pending["failures"].append({"code": "INSPECTION_CANCELLED"})
                if self.pending["frames"]:
                    self.finish_task = asyncio.create_task(self.finish(cancelled=True))
                else:
                    await self.finish(cancelled=True)
            return
        if snap.get("fault") or not snap.get("connected"):
            self.c.fault(snap.get("fault") or "IO_DISCONNECTED")
            return
        if "rfid" in s["recipe"]["channels"]:
            # A lost reader is reopened while the belt runs, again and again; it never
            # stops the line. A product read while it is gone is judged on what was read.
            task = self.rfid_reconnect
            if task and task.done():
                self.rfid_reconnect = None
            if not snap.get("rfid_ready") and hasattr(self.io, "ensure_rfid"):
                if self.rfid_reconnect is None:
                    self.rfid_reconnect = asyncio.create_task(self.reconnect_rfid())
        if (s["phase"] == "FEEDING" and self.speed_deadline is not None and now >= self.speed_deadline and not bulk
                and (not self.camera_required() or self.camera.status().get("connected"))):
            serial = self.speed_serial
            self.io.speed(True, allowed=lambda: serial == self.c.stop_serial and not self.c.pending_stops)
            self.speed_deadline = None
            self.event("HIGH_SPEED_SELECTED")
        if self.finish_task:
            if hits[0]:
                self.event("DI1_DETECTED")
                self.c.fault("EARLY_DI1_UNRESOLVED")
            elif hits[1]:
                self.event("DI2_DETECTED")
                self.c.fault("QUANTITY_MISMATCH")
            elif self.camera_required() and not self.camera.status().get("connected"):
                await self.reconnect(now, cfg)
            return
        if hits[0]:
            self.event("DI1_DETECTED")
            if self.pending:
                self.fail("EARLY_DI1_UNRESOLVED")
            else:
                if s["phase"] == "FEEDING":
                    self.cancel.clear()
                inspection, epoch, brand = self.c.begin(str(uuid.uuid4()), physical=True, moving=True)
                self.pending = {"inspection": inspection, "epoch": epoch, "brand": brand,
                    "start": self.edges[0].changed, "di2": False, "high": False,
                    "observations": {}, "failures": [], "frames": [], "crossings": 0, "tracking_started": False,
                    "camera_done": not self.camera_required(), "rfid_done": "rfid" not in s["recipe"]["channels"]}
                # The raw DI1 edge already started the low-speed timer. A
                # debounced acceptance must not undo an expired timer's return
                # to high speed, including a configured zero-length hold.
        if hits[1]:
            self.event("DI2_DETECTED")
            self.io.light(False)
            if not self.pending:
                self.c.fault("DI2_WITHOUT_DI1")
                return
            if self.pending["di2"]:
                self.fail("QUANTITY_MISMATCH")
            self.pending["di2"] = True
            self.pending["inspection"]["di2_at"] = utc()
        # A product failure takes priority over camera recovery. Never briefly
        # restart the conveyor before processing an already known mismatch.
        if self.pending and self.pending["failures"]:
            if self.pending["frames"]:
                self.finish_task = asyncio.create_task(self.finish())
            else:
                await self.finish()
            return
        if self.camera_required() and (not self.camera.status().get("connected") or (s["phase"] == "CAMERA_WAIT" and not self.reconnect_ok)):
            await self.reconnect(now, cfg)
            if s["phase"] not in ("FEEDING", "CAMERA_WAIT") or not self.camera.status().get("connected") or not self.reconnect_ok:
                return
        if s["phase"] == "CAMERA_WAIT":
            if self.reconnect_task and not self.reconnect_task.done():
                return
            # Only the camera interruption may resume. Manual stop/fault invalidates it.
            if self.resume_serial != self.c.stop_serial:
                return
            if self.worker_busy():
                return
            if self.io.snapshot().get("motor_restart_ms", 0):
                return
            if self.pending:
                p = self.pending
                if p["di2"] and not p["camera_done"]:
                    self.fail("CAMERA_CAPTURE_MISSED")
                    if p["frames"]:
                        self.finish_task = asyncio.create_task(self.finish())
                    else:
                        await self.finish()
                    return
                paused_for = now - max(self.wait_started, p["start"])
                p["start"] += paused_for
                if "rfid_next_at" in p:
                    p["rfid_next_at"] += paused_for
                # Resume incomplete channels from the stopped position. Completed
                # inspection results remain attached to the same product ID.
                if not p["camera_done"]:
                    p["frames"].clear()
                    p["inspection"].pop("captures", None)
            self.cancel.clear()
            if self.speed_deadline is None:
                self.speed_deadline = now
            else:
                paused_at = max(self.wait_started, self.speed_deadline - cfg.low_speed_ms / 1000)
                self.speed_deadline += now - paused_at
            self.speed_serial = self.resume_serial
            with self.c.lock:
                if s["phase"] != "CAMERA_WAIT" or self.resume_serial != self.c.stop_serial:
                    return
                self.c._motor_on(self.resume_serial)
                s.update(phase="FEEDING", fault=None)
                self.event("CAMERA_RECONNECTED", {"automatic_restart": True})
            self.resume_serial = None
        if bulk:
            await self.count_bulk(now, snap, tick_serial)
            return
        p = self.pending
        if not p:
            return
        elapsed = (now - p["start"]) * 1000
        if not p["camera_done"] and self.camera_task is None and elapsed >= cfg.capture_delay_ms:
            self.camera_task = asyncio.create_task(self.capture(p, cfg))
        if not p["rfid_done"] and self.rfid_task is None and elapsed >= cfg.rfid_delay_ms:
            self.rfid_task = asyncio.create_task(self.read_rfid(p))
        for name, done_key in (("camera_task", "camera_done"), ("rfid_task", "rfid_done")):
            task = getattr(self, name)
            if task and task.done():
                try:
                    task.result()
                except Exception as exc:
                    self.fail("CAMERA_ERROR" if name == "camera_task" else "RFID_ERROR", str(exc))
                p[done_key] = True
                setattr(self, name, None)
        if self.counter and elapsed >= cfg.capture_delay_ms:
            if not p["tracking_started"]:
                # Accepted DI1 starts a new product, so a previous product's
                # counted ID cannot suppress this product's crossing.
                from .counting import CrossingTracker
                self.counter.tracker = CrossingTracker(cfg)
                self.last_sequence = None
                self.c.tracking = None
                p["tracking_started"] = True
            if self.track_task and self.track_task.done():
                try:
                    result = self.track_task.result()
                    if result is not None:
                        p["crossings"] += len(result["crossed"])
                        p["inspection"]["tracking"] = result
                        self.c.tracking = result
                        if result["crossed"]:
                            self.event("VISION_CROSSING", {"count": len(result["crossed"])})
                        if p["crossings"] > 1:
                            self.fail("QUANTITY_MISMATCH")
                except Exception as exc:
                    self.fail("VISION_ERROR", str(exc))
                self.track_task = None
            if self.track_task is None and not p["failures"]:
                self.track_task = asyncio.create_task(self.offload(self.track_frame, now))
        if elapsed >= cfg.result_timeout_ms and (not p["camera_done"] or not p["rfid_done"] or (self.counter and p["crossings"] != 1)):
            self.fail("INSPECTION_TIMEOUT")
        if elapsed >= cfg.departure_timeout_ms and not p["di2"]:
            self.fail("PRODUCT_DEPARTURE_TIMEOUT")
        complete = p["di2"] and p["camera_done"] and p["rfid_done"] and (not self.counter or p["crossings"] == 1)
        if p["failures"] or complete:
            if p["frames"]:
                self.finish_task = asyncio.create_task(self.finish())
            else:
                await self.finish()

    async def count_bulk(self, now, snap, tick_serial):
        s = self.c.session
        if s["phase"] != "FEEDING" or self.counter is None:
            return
        if not self.bulk_started:
            # A new run (start, restart or camera recovery) begins with no
            # tracks, so nothing seen before the belt stopped counts again.
            from .counting import CrossingTracker
            self.counter.tracker = CrossingTracker(self.flow())
            self.last_sequence = None
            self.c.tracking = None
            self.bulk_started = True
        if not snap.get("led_requested"):
            self.io.light(True, allowed=lambda: tick_serial == self.c.stop_serial and not self.c.pending_stops)
        if self.track_task and self.track_task.done():
            task, self.track_task = self.track_task, None
            try:
                result = task.result()
            except Exception as exc:
                self.c.fault("VISION_ERROR: " + str(exc))
                return
            if result is not None:
                self.c.tracking = result
                if result["crossed"]:
                    self.c.vision_counted(len(result["crossed"]))
        if self.track_task is None and s["phase"] == "FEEDING":
            self.track_task = asyncio.create_task(self.offload(self.track_frame, now))

    def track_frame(self, now):
        # CameraManager may hold its lock while waiting for a fresh capture.
        # Both frame acquisition and inference must stay off the I/O monitor.
        frame, metadata = self.camera.read_latest()
        if metadata["seq"] == self.last_sequence:
            return None
        self.last_sequence = metadata["seq"]
        return self.counter.update(frame, now)

    async def capture(self, p, cfg):
        from .usb_camera import frame_at

        self.event("CAPTURE_STARTED")
        # Once per job, as the process test does. Querying and setting camera controls
        # for every product while the belt runs stalled the 48MP stream into reconnects.
        session_id = (self.c.session or {}).get("id")
        if getattr(self, "controls_checked", None) != session_id:
            self.controls_checked = session_id
            await self.offload(self.camera.verify_fixed_controls)
        recipe = Recipe.model_validate(p["inspection"]["recipe"])
        for i in range(cfg.capture_count):
            due = p["start"] + (cfg.capture_delay_ms + i * cfg.capture_interval_ms) / 1000
            await asyncio.sleep(max(0, due - time.monotonic()))
            previous_seq = p["frames"][-1][1]["seq"] if p["frames"] else -1
            frame, meta = await self.offload(frame_at, self.camera, int(due * 1e9),
                                             cfg.result_timeout_ms / 1000, previous_seq, self.cancel)
            if not self.live():
                return
            if i == 0:
                p["inspection"]["capture_delay_actual_ms"] = (meta["host_received_ns"] / 1e9 - p["start"]) * 1000
            import psutil
            budget = p.setdefault("frame_budget", min(1024**3, int(psutil.virtual_memory().available * .25)))
            if sum(f.nbytes for f, _ in p["frames"]) + frame.nbytes > budget:
                raise RuntimeError("촬영 장수 또는 해상도를 줄이세요. 영상 메모리 한도를 초과했습니다.")
            p["frames"].append((frame, meta))
        for frame_index, (frame, meta) in enumerate(p["frames"]):
            if set(recipe.channels) & {"ocr", "barcode"}:
                result = await self.offload(self.vision.inspect_frame, frame, p["brand"], recipe)
                if not self.live():
                    return
                p["observations"].update(result["observations"])
                failures = result["failures"] + judge(recipe.model_copy(update={"channels": [v for v in recipe.channels if v != "rfid"]}), result["observations"])
                p["inspection"].setdefault("captures", []).append({"timing": meta, "result": result})
                if failures:
                    p["evidence_index"] = frame_index
                    p["failures"].extend(failures)
                    self.c.stop_outputs()
                    return
            else:
                p["inspection"].setdefault("captures", []).append({"timing": meta})
        self.event("CAPTURE_FINISHED", {"count": len(p["frames"])})

    @staticmethod
    def rfid_match(brand, epc, recipe):
        try:
            fields = decode_epc(brand, epc)
        except RuleError:
            return False
        # A registered tag may still hold a value the option has since changed loosely (NS for N5).
        return all(fields.get(k) and loose(fields[k]) == loose(v) for k, v in recipe.targets.items())

    async def reconnect_rfid(self):
        if not hasattr(self.io, "ensure_rfid"):
            return False
        self.event("RFID_RETRY")
        try:
            await self.offload(self.io.ensure_rfid)
        except Exception as exc:
            self.event("RFID_RETRY_FAILED", {"error": str(exc)})
            await asyncio.sleep(RFID_RECONNECT_GAP_S)
            return False
        self.event("RFID_RECONNECTED")
        return True

    async def read_rfid(self, p):
        recipe = Recipe.model_validate(p["inspection"]["recipe"])
        cfg = recipe.flow
        self.event("RFID_STARTED")
        unique = {}
        while p.get("rfid_attempts", 0) < cfg.rfid_attempts:
            due = p.get("rfid_next_at", p["start"] + cfg.rfid_delay_ms / 1000)
            await asyncio.sleep(max(0, due - time.monotonic()))
            if not self.live():
                return
            started = time.monotonic()
            p["rfid_next_at"] = started + cfg.rfid_interval_ms / 1000
            p["rfid_attempts"] = p.get("rfid_attempts", 0) + 1
            p["inspection"]["rfid_attempts"] = p["rfid_attempts"]
            actual_delay = (started - p["start"]) * 1000
            if p["rfid_attempts"] == 1:
                p["inspection"]["rfid_delay_actual_ms"] = actual_delay
            attempt = {"attempt": p["rfid_attempts"], "after_trigger_ms": actual_delay, "status": "reading"}
            p["inspection"].setdefault("rfid_reads", []).append(attempt)
            try:
                # Several rounds over the whole interval, as the device test reads: one
                # round alone often answers "no tag" when two tags reply at once.
                result = await self.offload(self.io.inventory, cfg.rfid_interval_ms, self.cancel)
            except asyncio.CancelledError:
                attempt["status"] = "cancelled"
                raise
            except Exception as exc:
                attempt.update(status="error", error=str(exc))
                # The reader dropped mid-read: reopen it and spend the next attempt.
                if not await self.reconnect_rfid():
                    raise
                continue
            if not self.live():
                return
            for r in result:
                unique.setdefault(r["epc"], r)
            attempt.update(status="read" if result else "missing", tags=list(result))
            if any(self.rfid_match(p["brand"], epc, recipe) for epc in unique):
                break
        # Preserve both the attempt budget and a completed read through camera
        # reconnection.
        p["rfid_done"] = True
        p["inspection"]["rfid"] = list(unique.values())
        # Any tag that is the target product passes, whatever else was read with it.
        match = next((epc for epc in unique if self.rfid_match(p["brand"], epc, recipe)), None)
        if match:
            p["observations"]["rfid"] = dict(recipe.targets)
            p["inspection"]["rfid_match"] = match
        elif not unique:
            self.fail("RFID_MISSING")
        else:
            decoded = []
            for epc in unique:
                try:
                    decoded.append(decode_epc(p["brand"], epc))
                except RuleError:
                    pass
            if not decoded:
                self.fail("RFID_UNREGISTERED", ", ".join(unique))
            else:
                p["observations"]["rfid"] = decoded[0]
                failures = judge(recipe.model_copy(update={"channels": ["rfid"]}), p["observations"])
                p["failures"].extend(failures or [{"code": "TARGET_MISMATCH", "channel": "rfid"}])
                self.c.stop_outputs()
        self.event("RFID_FINISHED", {"tags": len(unique), "attempts": p.get("rfid_attempts", 0)})

    async def finish(self, cancelled=False):
        p = self.pending
        self.cancel.set()
        for name in ("camera_task", "rfid_task", "track_task"):
            task = getattr(self, name)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                setattr(self, name, None)
        if cancelled:
            # complete() detects invalidated epoch and records ABORTED without counts.
            epoch = -1
        else:
            epoch = p["epoch"]
        evidence = None
        writer = None
        if p["frames"]:
            from .evidence import save_frame
            index = p.get("evidence_index", len(p["frames"]) - 1)
            frame, meta = p["frames"][index]
            evidence = {"source": "USB_CAMERA", "timing": meta, "retained": False}
            retain = cancelled or p["failures"] or self.c.session.get("save_pass_photos", True)
            if retain:
                def write_images():
                    captures = p["inspection"].setdefault("captures", [])
                    while len(captures) < len(p["frames"]):
                        captures.append({})
                    primary = None
                    for i, (image, timing) in enumerate(p["frames"]):
                        ident = p["inspection"]["id"] if i == index else str(uuid.uuid4())
                        _, saved = save_frame(self.c.store.root, ident, image, timing, None)
                        saved["source"] = "USB_CAMERA"
                        captures[i]["evidence"] = saved
                        if i == index:
                            primary = saved
                    return primary
                try:
                    evidence = await self.offload(write_images)
                except Exception as exc:
                    p["failures"].append({"code": "EVIDENCE_ERROR", "detail": str(exc)})
                    self.c.stop_outputs()
        p["inspection"]["di2_count"] = int(p["di2"])
        p["inspection"]["vision_count"] = p["crossings"] if self.counter else None
        try:
            self.c.complete(p["inspection"], epoch, p["observations"], p["failures"], evidence, writer, moving=True)
        finally:
            self.pending = None
        self.cancel.clear()

    async def reconnect(self, now, cfg):
        s = self.c.session
        generation = self.c.stop_serial
        if s["phase"] != "CAMERA_WAIT":
            # Publish the interruption before awaiting cancelled workers. A STOP
            # received during their cleanup must remain PAUSED afterward.
            with self.c.lock:
                if s["phase"] != "FEEDING" or generation != self.c.stop_serial or self.c.pending_stops:
                    return
                self.io.motor(False)
                self.io.speed(False)
                if s["recipe"].get("kind") == "vision":
                    self.io.light(False)
                self.bulk_started = False
                self.cancel.set()
                self.wait_started = now
                self.reconnect_ok = False
                self.resume_serial = generation
                s.update(phase="CAMERA_WAIT", fault="CAMERA_STALE")
                self.event("CAMERA_DISCONNECTED")
                self.next_retry = now + cfg.reconnect_interval_ms / 1000
            if self.reconnect_task:
                self.reconnect_task.cancel()
                await asyncio.gather(self.reconnect_task, return_exceptions=True)
                self.reconnect_task = None
            for name in ("camera_task", "rfid_task", "track_task"):
                task = getattr(self, name)
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    setattr(self, name, None)
        if s["phase"] != "CAMERA_WAIT" or self.resume_serial != self.c.stop_serial:
            return
        if self.reconnect_task and self.reconnect_task.done():
            try:
                self.reconnect_task.result()
                self.reconnect_ok = bool(self.camera.status().get("connected"))
                if not self.reconnect_ok:
                    self.event("CAMERA_RETRY_FAILED", {"error": "카메라 영상이 수신되지 않았습니다."})
            except Exception as exc:
                self.reconnect_ok = False
                self.event("CAMERA_RETRY_FAILED", {"error": str(exc)})
            self.reconnect_task = None
            self.next_retry = now + cfg.reconnect_interval_ms / 1000
        status = self.camera.status()
        # Frames coming in again is what counts, whenever they arrive: a 48MP stream
        # can take longer than one retry interval to deliver its first frame.
        self.reconnect_ok = bool(status.get("connected"))
        if not self.reconnect_ok and self.reconnect_task is None and now >= self.next_retry and not self.worker_busy():
            if status.get("process_alive") and (status.get("capture_stage_ms") or 0) < 10000:
                # The capture is starting or briefly stalled: leave it to deliver. Restarting
                # it every interval killed each new 48MP stream before its first frame, so the
                # job never came back. Its reader ends it by itself after 2 s without frames.
                self.next_retry = now + cfg.reconnect_interval_ms / 1000
                return
            self.event("CAMERA_RETRY")
            self.reconnect_task = asyncio.create_task(self.offload(self.camera.connect))
            # The serial and phase guards still reject a manual stop during connect.

    async def close(self):
        await super().close()
        for task in (self.camera_task, self.rfid_task, self.track_task, self.reconnect_task, self.finish_task,
                     self.rfid_reconnect):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
