"""Serialized product lifecycle. Stop requests never wait for OCR or disk I/O."""

from __future__ import annotations

import copy
import hashlib
import shutil
import threading
import time
import uuid

from .schema import Brand, Recipe, Command, Adjustment, StationConfig
from .rules import validate_recipe, judge
from .storage import Store, dump, utc


class Conflict(ValueError):
    pass


class Controller:
    def __init__(self, store: Store, io, config: StationConfig):
        self.store, self.io, self.config = store, io, config
        self.lock = threading.RLock()
        self.session = store.get("last_session")
        self.epoch = 0
        self.revision = 0
        self.busy = False
        self.last_result = None
        self.stop_fault = None
        self.boot_id = str(uuid.uuid4())
        self.last_client = time.monotonic()
        self.stop_serial = 0
        self.pending_stops = 0
        self.stop_lock = threading.Lock()
        self.runtime_blockers = lambda: []
        self.external_busy = lambda: False
        self.stop_outputs()
        with store.transaction() as c:
            for row in c.execute(
                "SELECT id,body FROM inspections WHERE status='PENDING'"
            ).fetchall():
                import json

                body = json.loads(row["body"])
                body.update(
                    status="ABORTED", failure="PROCESS_RESTART", finished_at=utc()
                )
                body["failures"] = [
                    *body.get("failures", []),
                    {"code": "PROCESS_RESTART"},
                ]
                c.execute(
                    "UPDATE inspections SET status=?,body=? WHERE id=?",
                    ("ABORTED", dump(body), row["id"]),
                )
            if self.session and self.session["phase"] not in (
                "DONE",
                "FINISHED",
                "ABORTED",
            ):
                self.session.update(phase="ABORTED", fault="PROCESS_RESTART")
                store.session(self.session, c)
                store.event("PROCESS_RESTART", {"session_id": self.session["id"]}, c)

    def stop_outputs(self):
        try:
            self.io.stop()
        except Exception as exc:
            self.stop_fault = f"IO_STOP_UNCONFIRMED: {exc}"
        # OFF requested is not proof of mechanical stop. Adapter reports DI3 independently.

    def snapshot(self):
        with self.lock:
            blockers = self.start_blockers()
            session = None
            if self.session:
                brand = self.session["brand"]
                session = copy.deepcopy(
                    {
                        **self.session,
                        "brand": {
                            **brand,
                            "decoder": {**brand["decoder"], "records": {}},
                            "barcode_records": {},
                        },
                    }
                )
            return {
                "boot_id": self.boot_id,
                "revision": self.revision,
                "mode": self.config.mode,
                "session": session,
                "can_start": not blockers,
                "blockers": blockers,
                "observed_at": utc(),
                "busy": self.busy,
                "last_result": copy.deepcopy(self.last_result),
                "stop_fault": self.stop_fault,
                "io": self.io.snapshot(),
            }

    def start_blockers(self):
        blockers = []
        if not self.session:
            blockers.append("검사 작업을 먼저 생성하세요.")
        elif self.session["phase"] not in ("READY", "PAUSED"):
            blockers.append("현재 상태에서는 운전 준비가 불가능합니다.")
        if self.busy or self.external_busy():
            blockers.append("검사 처리 종료 대기")
        if self.stop_fault:
            blockers.append(self.stop_fault)
        disk = shutil.disk_usage(self.store.root)
        if (
            disk.free < self.config.disk_min_free_mb * 1024**2
            or disk.free / disk.total < 0.1
        ):
            blockers.append("저장 공간 부족: 10% 및 최소 여유 용량 필요")
        if self.config.mode == "HARDWARE":
            blockers += self.hardware_blockers()
        return blockers

    def hardware_blockers(self):
        reasons = (
            self.config.commissioning.blockers()
            + self.io.blockers()
            + self.runtime_blockers()
        )
        if (
            self.session
            and self.session["recipe"].get("kind", "condition") != "simple"
            and not {"ocr", "rfid"} <= set(self.session["recipe"]["channels"])
        ):
            reasons.append(
                "실물 운전은 OCR과 RFID 대조가 모두 필요합니다. 바코드만 선택 항목입니다."
            )
        return reasons

    def check_disk(self):
        disk = shutil.disk_usage(self.store.root)
        if (
            disk.free < self.config.disk_min_free_mb * 1024**2
            or disk.free / disk.total < 0.1
        ):
            self.stop_outputs()
            raise Conflict("저장 공간이 부족합니다. 검사를 시작할 수 없습니다.")

    def changed(self, kind, body=None, c=None):
        self.revision += 1
        if self.session:
            self.store.session(self.session, c)
        self.store.event(kind, body or {}, c)

    def new_session(self, recipe: Recipe, actor="local-operator"):
        with self.lock:
            if (
                self.busy
                or self.external_busy()
                or (
                    self.session
                    and self.session["phase"] not in ("FINISHED", "DONE", "ABORTED")
                )
            ):
                raise Conflict("현재 작업을 종료한 후 새 작업을 만드세요.")
            self.stop_outputs()
            self.check_disk()
            if recipe.kind == "simple":
                brand = Brand(id="simple-count", name="단순 계수")
            else:
                brand = Brand.model_validate(self.store.brand(recipe.brand_id))
                validate_recipe(recipe, brand)
            self.session = {
                "id": str(uuid.uuid4()),
                "created_at": utc(),
                "mode": self.config.mode,
                "phase": "READY",
                "recipe": recipe.model_dump(),
                "brand": brand.model_dump(),
                "brand_hash": hashlib.sha256(
                    dump(brand.model_dump()).encode()
                ).hexdigest(),
                "count": 0,
                "passed": 0,
                "failed": 0,
                "adjustments": 0,
                "active_product": None,
                "fault": None,
                "save_pass_photos": self.store.get(
                    "save_pass_photos", self.config.mode != "HARDWARE"
                ),
                "ocr_correction": self.store.get("ocr_correction", {}),
            }
            self.session["software_version"] = "0.3.0"
            self.session["created_by"] = actor
            self.last_result = None
            self.epoch += 1
            self.changed(
                "SESSION_CREATED",
                {
                    "session_id": self.session["id"],
                    "actor": actor,
                    "recipe": recipe.model_dump(),
                },
            )
            return self.snapshot()

    def command(self, cmd: Command, actor: str):
        # A STOP is always applied before any validation/lock/database work.
        stop_action = cmd.action in ("stop", "pause", "finish")
        with self.stop_lock:
            generation = self.stop_serial
            if stop_action:
                self.stop_serial += 1
                self.pending_stops += 1
        if stop_action:
            self.stop_outputs()
        try:
            return self._command(cmd, actor, generation, stop_action)
        finally:
            if stop_action:
                with self.stop_lock:
                    self.pending_stops -= 1

    def _motor_on(self, generation):
        def allowed():
            with self.stop_lock:
                return self.stop_serial == generation and self.pending_stops == 0

        if not allowed():
            raise Conflict("정지 요청이 우선합니다. 새 운전 명령이 필요합니다.")
        self.io.motor(True, allowed=allowed)

    def _command(self, cmd, actor, generation, stop_action):
        fingerprint = hashlib.sha256(dump(cmd.model_dump()).encode()).hexdigest()
        with self.lock:
            expected_revision_valid = cmd.expected_revision == self.revision
            if stop_action:
                self.stop_outputs()
            stopped_phase = False
            if stop_action and self.session:
                self.epoch += 1
                if self.session["phase"] not in (
                    "HOLD",
                    "FAULT",
                    "DONE",
                    "FINISHED",
                    "ABORTED",
                    "PAUSED",
                ):
                    self.session["phase"] = "PAUSED"
                    stopped_phase = True
            if stopped_phase:
                self.changed(
                    "STOP_REQUESTED", {"request_id": cmd.request_id, "actor": actor}
                )
            cached = self.store.command_result(cmd.request_id, fingerprint)
            if cached is not None:
                return {"duplicate": True, "result": cached, "state": self.snapshot()}
            s = self.session
            if not s or s["id"] != cmd.session_id:
                raise Conflict("작업이 변경되었습니다. 다시 불러오세요.")
            if cmd.action not in ("stop", "pause") and not expected_revision_valid:
                raise Conflict("상태가 변경되었습니다. 명령을 다시 확인하세요.")
            if cmd.action in ("start", "release") and self.config.mode == "HARDWARE":
                if cmd.issued_at is None or not 0 <= time.time() - cmd.issued_at <= 3:
                    raise Conflict("운전 명령이 만료되었습니다. 새 명령을 요청하세요.")
            if cmd.action == "start":
                if (
                    s["phase"] not in ("READY", "PAUSED")
                    or self.busy
                    or self.external_busy()
                    or self.stop_fault
                ):
                    raise Conflict("지금은 운전을 시작할 수 없습니다.")
                self.check_disk()
                counted = False
                if s["active_product"]:
                    with self.store.lock:
                        counted = bool(
                            self.store.conn.execute(
                                "SELECT 1 FROM counts WHERE session_id=? AND product_id=?",
                                (s["id"], s["active_product"]),
                            ).fetchone()
                        )
                if self.config.mode == "HARDWARE":
                    blockers = self.hardware_blockers()
                    if blockers:
                        raise Conflict("현장 확인 필요: " + ", ".join(blockers))
                    raw = self.io.snapshot().get("di_raw")
                    cfg = self.config.commissioning
                    if not counted and (
                        s["active_product"]
                        or (
                            raw and raw[cfg.product_sensor - 1] == cfg.sensor_active_raw
                        )
                    ):
                        if (
                            not raw
                            or raw[cfg.product_sensor - 1] != cfg.sensor_active_raw
                        ):
                            raise Conflict("재검사할 제품 위치를 확인하세요.")
                        self.stop_outputs()
                        s["phase"] = "RETRY_PENDING"
                    else:
                        self._motor_on(generation)
                        s["phase"] = "EJECTING" if counted else "FEEDING"
                else:
                    s["phase"] = "PASSED" if counted else "READY"
            elif cmd.action in ("stop", "pause"):
                self.epoch += 1
                if s["phase"] in ("HOLD", "FAULT"):
                    pass  # Never clear a latched fault by pressing pause.
                elif s["phase"] not in ("DONE", "FINISHED", "ABORTED"):
                    s["phase"] = "PAUSED"
            elif cmd.action == "reset":
                if s["phase"] not in ("HOLD", "FAULT", "PAUSED") or self.busy:
                    raise Conflict("진행 중인 검사를 마친 후 복구하세요.")
                if len(cmd.reason) < 3:
                    raise Conflict("작업자 확인 및 조치 내용을 입력하세요.")
                self.stop_outputs()
                if self.config.mode == "HARDWARE" and hasattr(self.io, "reset"):
                    self.io.reset()
                    self.stop_fault = None
                if self.stop_fault or self.io.snapshot().get("km2_on") is True:
                    raise Conflict("출력 정지를 확인할 수 없습니다.")
                # Reset clears the fault only. It never energizes the motor.
                s.update(phase="READY", fault=None)
                self.epoch += 1
            elif cmd.action == "release":
                if s["phase"] != "PASSED" or self.busy:
                    raise Conflict("합격한 제품만 배출할 수 있습니다.")
                if self.config.mode == "HARDWARE":
                    if self.hardware_blockers():
                        raise Conflict("운전 허가를 확인할 수 없습니다.")
                    self._motor_on(generation)
                    s["phase"] = "EJECTING"
                else:
                    self.departed()
            elif cmd.action == "discard":
                if s["phase"] != "HOLD" or self.busy or len(cmd.reason) < 3:
                    raise Conflict("불합격 제품 제거 및 조치 내용을 먼저 확인하세요.")
                self.stop_outputs()
                if self.stop_fault or self.io.snapshot().get("km2_on") is True:
                    raise Conflict("장비 정지를 확인할 수 없습니다.")
                if self.config.mode == "HARDWARE":
                    raw = self.io.snapshot().get("di_raw")
                    if not raw or any(
                        v == self.config.commissioning.sensor_active_raw
                        for v in raw[:2]
                    ):
                        raise Conflict(
                            "제품 제거 후 두 제품 센서가 해제되었는지 확인하세요."
                        )
                s.update(phase="READY", active_product=None, fault=None)
                self.epoch += 1
            elif cmd.action == "finish":
                if self.busy:
                    self.epoch += 1
                    raise Conflict("검사 중단 처리 후 작업을 종료하세요.")
                if s["phase"] in ("HOLD", "FAULT") and len(cmd.reason) < 3:
                    raise Conflict("미해결 검사 조치 내용을 입력하세요.")
                if s["active_product"] and len(cmd.reason) < 3:
                    raise Conflict("남아 있는 제품의 처리 내용을 입력하세요.")
                s["phase"] = "FINISHED"
                s["active_product"] = None
                self.epoch += 1
            result = {"action": cmd.action, "phase": s["phase"], "at": utc()}
            try:
                with self.store.transaction() as c:
                    self.changed(
                        "COMMAND",
                        {**cmd.model_dump(), "actor": actor, "result": result},
                        c,
                    )
                    c.execute(
                        "INSERT INTO commands VALUES(?,?,?)",
                        (cmd.request_id, fingerprint, dump(result)),
                    )
            except Exception:
                self.stop_outputs()
                s.update(phase="FAULT", fault="DATABASE_WRITE_FAILED")
                raise
            return {"duplicate": False, "result": result, "state": self.snapshot()}

    def departed(self):
        with self.lock:
            if not self.session or self.session["phase"] not in ("PASSED", "EJECTING"):
                raise Conflict("배출 확인 상태가 아닙니다.")
            self.stop_outputs()
            target = self.session["recipe"]["target_count"]
            done = target is not None and self.session["count"] >= target
            self.session.update(active_product=None, phase="DONE" if done else "READY")
            self.changed("PRODUCT_DEPARTED")

    def begin(self, product_id: str, physical=False, actor="physical-cycle"):
        # Capture/OCR occurs only after this OFF, feedback confirmation, and settle gate.
        self.stop_outputs()
        with self.lock:
            s = self.session
            if (
                not s
                or self.busy
                or self.external_busy()
                or s["phase"] not in ("READY", "FEEDING", "RETRY_PENDING")
                or self.stop_fault
            ):
                raise Conflict("검사를 시작할 수 없는 상태입니다.")
            if self.config.mode == "HARDWARE" and not physical:
                raise Conflict("실물 모드에서는 현장 제품 검출 이벤트만 허용합니다.")
            if s["active_product"] not in (None, product_id):
                raise Conflict("이전 제품의 배출·조치가 확인되지 않았습니다.")
            with self.store.lock:
                counted = self.store.conn.execute(
                    "SELECT 1 FROM counts WHERE session_id=? AND product_id=?",
                    (s["id"], product_id),
                ).fetchone()
                attempt = (
                    self.store.conn.execute(
                        "SELECT COUNT(*) FROM inspections WHERE session_id=? AND product_id=?",
                        (s["id"], product_id),
                    ).fetchone()[0]
                    + 1
                )
            if counted:
                raise Conflict("이미 계수한 제품입니다.")
            self.check_disk()
            self.busy = True
            s.update(phase="STOPPING", active_product=product_id)
            inspection = {
                "id": str(uuid.uuid4()),
                "session_id": s["id"],
                "product_id": product_id,
                "attempt": attempt,
                "status": "PENDING",
                "mode": self.config.mode,
                "created_at": utc(),
                "recipe": copy.deepcopy(s["recipe"]),
                "created_mono_ns": time.monotonic_ns(),
                "brand_hash": s["brand_hash"],
                "observations": {},
                "failures": [],
                "evidence": None,
            }
            inspection.update(actor=actor, software_version="0.3.0")
            try:
                with self.store.transaction() as c:
                    c.execute(
                        "INSERT INTO inspections VALUES(?,?,?,?,?,?,?)",
                        (
                            inspection["id"],
                            s["id"],
                            product_id,
                            attempt,
                            "PENDING",
                            dump(inspection),
                            inspection["created_at"],
                        ),
                    )
                    self.changed(
                        "INSPECTION_BEGIN",
                        {"id": inspection["id"], "product_id": product_id},
                        c,
                    )
            except Exception:
                self.busy = False
                s.update(phase="FAULT", fault="DATABASE_WRITE_FAILED")
                raise
            return inspection, self.epoch, Brand.model_validate(s["brand"])

    def inspecting(self, epoch):
        with self.lock:
            if (
                epoch != self.epoch
                or not self.session
                or self.session["phase"] != "STOPPING"
            ):
                raise Conflict("검사가 중단되었습니다.")
            if self.io.snapshot().get("km2_on") is True:
                raise Conflict("KM2_FEEDBACK_STUCK")
            self.session["phase"] = "INSPECTING"
            self.changed("CAPTURE_READY")

    def complete(
        self, inspection, epoch, observations, failures=None, evidence=None,
        evidence_writer=None,
    ):
        self.stop_outputs()
        with self.lock:
            s = self.session
            failures = list(failures or [])
            cancelled = (
                epoch != self.epoch or s is None or s["id"] != inspection["session_id"]
            )
            if cancelled:
                failures.append({"code": "INSPECTION_CANCELLED"})
            else:
                failures.extend(judge(Recipe.model_validate(s["recipe"]), observations))
            failures = list({dump(item): item for item in failures}.values())
            status = "ABORTED" if cancelled else ("FAIL" if failures else "PASS")
            before = copy.deepcopy(s)
            if self.stop_fault:
                failures.append({"code": "IO_STOP_UNCONFIRMED"})
                status = "FAIL"
            if evidence_writer is not None:
                if status == "PASS" and not s.get("save_pass_photos", True):
                    evidence = {**evidence, "retained": False}
                else:
                    try:
                        _, evidence = evidence_writer()
                    except Exception as exc:
                        failures.append({"code": "EVIDENCE_ERROR", "detail": str(exc)})
                        if status == "PASS":
                            status = "FAIL"
            inspection.update(
                status=status,
                finished_at=utc(),
                observations=observations,
                failures=failures,
                evidence=evidence,
            )
            inspection["finished_mono_ns"] = time.monotonic_ns()
            inspection["elapsed_ms"] = (
                inspection["finished_mono_ns"] - inspection["created_mono_ns"]
            ) / 1e6
            try:
                with self.store.transaction() as c:
                    c.execute(
                        "UPDATE inspections SET status=?,body=? WHERE id=?",
                        (status, dump(inspection), inspection["id"]),
                    )
                    if not cancelled and s:
                        if status == "PASS":
                            c.execute(
                                "INSERT INTO counts VALUES(?,?,?)",
                                (s["id"], inspection["product_id"], inspection["id"]),
                            )
                            s["passed"] += 1
                            s["count"] += 1
                            s.update(phase="PASSED", fault=None)
                        else:
                            s["failed"] += 1
                            s.update(phase="HOLD", fault=failures[0]["code"])
                        self.changed(
                            "INSPECTION_FINAL",
                            {"id": inspection["id"], "status": status},
                            c,
                        )
                    else:
                        self.store.event(
                            "INSPECTION_ABORTED", {"id": inspection["id"]}, c
                        )
                self.last_result = inspection
            except Exception:
                if before:
                    self.session = before
                    self.session.update(phase="FAULT", fault="DATABASE_WRITE_FAILED")
                raise
            finally:
                self.busy = False
            if (
                status == "PASS"
                and s
                and not s.get("save_pass_photos", True)
                and evidence
                and evidence.get("retained") is not False
            ):
                self._apply_photo_policy(inspection)
            return copy.deepcopy(inspection)

    def _apply_photo_policy(self, inspection):
        # Counts are already committed. Cleanup must never turn a committed
        # product into a failed/retryable inspection.
        try:
            ident = str(uuid.UUID(inspection["id"]))
            directory = (self.store.root / "evidence").resolve()
            paths = [
                (directory / (ident + ext)).resolve()
                for ext in (".png", ".jpg", ".original")
            ]
            if any(path.parent != directory for path in paths):
                raise ValueError("Evidence path outside data directory")
            updated = copy.deepcopy(inspection)
            updated["evidence"].pop("url", None)
            updated["evidence"]["retained"] = False
            with self.store.transaction() as c:
                c.execute(
                    "UPDATE inspections SET body=? WHERE id=?", (dump(updated), ident)
                )
                self.store.event("PASS_PHOTO_NOT_RETAINED", {"id": ident}, c)
            inspection.update(updated)
            for path in paths:
                path.unlink(missing_ok=True)
        except Exception as exc:
            try:
                self.store.event(
                    "PHOTO_POLICY_FAILED", {"id": inspection["id"], "error": str(exc)}
                )
            except Exception:
                pass

    def adjust(self, item: Adjustment, actor):
        fingerprint = hashlib.sha256(dump(item.model_dump()).encode()).hexdigest()
        with self.lock:
            cached = self.store.command_result(item.request_id, fingerprint)
            if cached is not None:
                return cached
            s = self.session
            if (
                not s
                or item.session_id != s["id"]
                or self.busy
                or s["phase"]
                in (
                    "FEEDING",
                    "EJECTING",
                    "INSPECTING",
                    "STOPPING",
                    "RETRY_PENDING",
                    "FINISHED",
                )
            ):
                raise Conflict("정지 상태에서 현재 작업의 수량만 보정할 수 있습니다.")
            if s["count"] + item.delta < 0:
                raise Conflict("수량은 0보다 작을 수 없습니다.")
            before = copy.deepcopy(s)
            s["count"] += item.delta
            s["adjustments"] += item.delta
            result = {
                "count": s["count"],
                "delta": item.delta,
                "reason": item.reason,
                "actor": actor,
            }
            try:
                with self.store.transaction() as c:
                    self.changed("MANUAL_ADJUSTMENT", result, c)
                    c.execute(
                        "INSERT INTO commands VALUES(?,?,?)",
                        (item.request_id, fingerprint, dump(result)),
                    )
            except Exception:
                self.stop_outputs()
                self.session = before
                raise
            return result

    def fault(self, reason):
        with self.stop_lock:
            self.stop_serial += 1
        self.stop_outputs()
        with self.lock:
            self.epoch += 1
            if self.session and self.session["phase"] not in (
                "DONE",
                "FINISHED",
                "ABORTED",
            ):
                self.session.update(phase="FAULT", fault=reason)
                self.changed("FAULT", {"reason": reason})
