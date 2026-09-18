"""Independent device tests. Test outputs never create production counts."""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from pathlib import Path

from pydantic import Field, model_validator
from .schema import Model
from .controller import Conflict


class BenchSetup(Model):
    do_on_raw: int | None = Field(default=None, ge=0, le=1)
    permit_line: int | None = Field(default=None, ge=0, le=1023)
    permit_active_raw: int | None = Field(default=None, ge=0, le=1)
    feedback_timeout_ms: int | None = Field(default=None, ge=20, le=10000)
    sensor_active_raw: list[int | None] = Field(default_factory=lambda: [None, None], min_length=2, max_length=2)
    output_wiring_confirmed: bool = False
    stop_circuit_confirmed: bool = False
    rfid_port: str = Field(default="", max_length=200)
    rfid_window_ms: int = Field(default=500, ge=100, le=10000)
    rfid_protocol_confirmed: bool = False

    @model_validator(mode="after")
    def polarity(self):
        if any(v not in (None, 0, 1) for v in self.sensor_active_raw):
            raise ValueError("센서 감지값은 0 또는 1입니다.")
        return self


class BenchGPIO:
    """One read-only input request. Outputs are acquired only after verified setup."""
    def __init__(self, config, setup):
        import platform
        if platform.system() != "Linux":
            raise ValueError("GPIO 시험은 J4012에서 사용할 수 있습니다.")
        try:
            import gpiod
            from gpiod.line import Direction, Value
        except ImportError as exc:
            raise ValueError("libgpiod 2.x를 설치하세요.") from exc
        if not hasattr(gpiod, "request_lines"):
            raise ValueError("libgpiod 2.x가 필요합니다.")
        self.gpiod, self.Direction, self.Value = gpiod, Direction, Value
        self.config, self.setup = config, setup
        self.outputs = None
        self.motor_requested = self.led_requested = False
        pins = list(config.di_lines)
        if setup.permit_line is not None:
            pins.append(setup.permit_line)
        self.inputs = gpiod.request_lines(
            config.gpio_chip, consumer="txrx-input-test",
            config={p: gpiod.LineSettings(direction=Direction.INPUT) for p in pins},
        )

    def snapshot(self):
        raw = [v.value for v in self.inputs.get_values(list(self.config.di_lines))]
        permit = None
        if self.setup.permit_line is not None and self.setup.permit_active_raw is not None:
            permit = self.inputs.get_value(self.setup.permit_line).value == self.setup.permit_active_raw
        return {"connected": True, "di_raw": raw, "km2_on": raw[2] == 0,
                "physical_permit": permit, "motor_requested": self.motor_requested,
                "led_requested": self.led_requested, "led_confirmed": None}

    def set_output(self, target, on, allowed=lambda: True):
        if on and self.outputs is None:
            off = self.Value.ACTIVE if self.setup.do_on_raw == 0 else self.Value.INACTIVE
            self.outputs = self.gpiod.request_lines(
                self.config.gpio_chip, consumer="txrx-output-test",
                config={p: self.gpiod.LineSettings(direction=self.Direction.OUTPUT, output_value=off)
                        for p in self.config.do_lines},
            )
        if self.outputs is None:
            return
        if on and not allowed():
            raise Conflict("정지 요청이 우선합니다.")
        line = self.config.do_lines[0 if target == "motor" else 1]
        raw = self.setup.do_on_raw if on else 1 - self.setup.do_on_raw
        self.outputs.set_value(line, self.Value.ACTIVE if raw else self.Value.INACTIVE)
        if target == "motor":
            self.motor_requested = on
        else:
            self.led_requested = on

    def stop(self):
        if self.outputs:
            raw = 1 - self.setup.do_on_raw
            self.outputs.set_values({p: self.Value.ACTIVE if raw else self.Value.INACTIVE for p in self.config.do_lines})
        self.motor_requested = self.led_requested = False

    def close(self):
        try:
            self.stop()
        finally:
            if self.outputs:
                self.outputs.release()
            self.inputs.release()


class BorrowedGPIO:
    """Use the production owner's handles, never request the same GPIO twice."""
    def __init__(self, io):
        self.io = io

    def snapshot(self):
        return self.io.snapshot()

    def set_output(self, target, on, allowed=lambda: True):
        (self.io.motor if target == "motor" else self.io.light)(on, allowed=allowed)

    def stop(self):
        self.io.stop()

    def close(self):
        self.stop()


class Bench:
    def __init__(self, config, production_io, store, gpio_factory=BenchGPIO):
        self.config, self.production_io, self.store = config, production_io, store
        defaults = BenchSetup(
            do_on_raw=config.do_on_raw, permit_line=config.permit_line,
            permit_active_raw=config.permit_active_raw,
            feedback_timeout_ms=config.commissioning.feedback_timeout_ms,
            sensor_active_raw=[config.commissioning.sensor_active_raw] * 2,
            rfid_port=config.rfid_port,
            rfid_window_ms=config.rfid_window_ms or 500,
        )
        self.setup = BenchSetup.model_validate(store.get("bench_setup", defaults.model_dump()))
        self.gpio_factory = gpio_factory
        self.lock = threading.RLock()
        self.stop_lock = threading.Lock()
        self.stop_serial = 0
        self.stop_wait_until = None
        self.io = None
        self.last = {}
        self.error = None
        self.native_busy = False
        self.cancel = threading.Event()
        self.generation = 0
        self.run = None
        # Reconnection must not reset the interval. After a server restart,
        # previously used outputs wait a full interval before being enabled.
        used = store.get("bench_outputs_used", [])
        self.next_output_at = {target: time.monotonic() + (10 if target in used else 0)
                               for target in ("motor", "led")}
        self.seen = deque(maxlen=256)
        self.transitions = [0, 0, 0]
        self.changed_at = [None, None, None]
        self.events = deque(maxlen=50)
        self.last_rfid = None
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True, name="device-test-watchdog")
        self.thread.start()

    def busy(self):
        return self.io is not None or self.native_busy or self.run is not None or bool(self.error)

    def save_setup(self, setup, actor):
        pins = [*self.config.di_lines, *self.config.do_lines]
        if len(pins) != len(set(pins)) or setup.permit_line in pins:
            raise ValueError("입출력 핀을 중복 지정할 수 없습니다.")
        with self.lock:
            if self.io or self.run:
                raise Conflict("입력 연결을 종료한 후 저장하세요.")
            with self.store.transaction() as c:
                import json
                c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("bench_setup", json.dumps(setup.model_dump())))
                self.store.event("BENCH_SETUP_SAVED", {"actor": actor, "setup": setup.model_dump()}, c)
            self.setup = setup
            return self.status()

    def connect(self):
        with self.lock:
            if self.io:
                return self.status()
            self.cancel.clear()
            self.error = None
            if self.production_io.snapshot().get("connected"):
                # The production owner's verified polarity and permit mapping must agree.
                for key in ("do_on_raw", "permit_line", "permit_active_raw"):
                    if getattr(self.setup, key) != getattr(self.config, key):
                        raise Conflict("생산 설정과 시험 설정의 출력 및 허가 입력이 다릅니다.")
                self.io = BorrowedGPIO(self.production_io)
            else:
                if self.setup.permit_line in (*self.config.di_lines, *self.config.do_lines):
                    raise ValueError("운전 허가 입력이 다른 핀과 중복됩니다.")
                self.io = self.gpio_factory(self.config, self.setup)
            try:
                self.last = self.io.snapshot()
                self.transitions = [0, 0, 0]
                self.changed_at = [None, None, None]
                self.events.clear()
            except Exception:
                self.io.close()
                self.io = None
                raise
            self.generation += 1
            return self.status()

    def output_blockers(self):
        s = self.setup
        reasons = []
        if not self.io:
            reasons.append("입력 연결을 먼저 시작하세요.")
        if s.do_on_raw is None:
            reasons.append("출력 ON 값을 지정하세요.")
        if s.permit_line is None or s.permit_active_raw is None:
            reasons.append("운전 허가 입력을 지정하세요.")
        if not s.feedback_timeout_ms:
            reasons.append("접촉기 응답 시간을 지정하세요.")
        if not s.output_wiring_confirmed:
            reasons.append("출력 배선 확인이 필요합니다.")
        if not s.stop_circuit_confirmed:
            reasons.append("정지 회로 확인이 필요합니다.")
        if self.error:
            reasons.append(self.error)
        return reasons

    def pulse(self, target, seconds, generation, request_id, issued_at):
        serial = self.stop_serial
        with self.lock:
            if request_id in self.seen:
                return self.status()
            if generation != self.generation or abs(time.time() - issued_at) > 3:
                raise Conflict("이전 시험 요청입니다. 다시 눌러 주세요.")
            if self.native_busy or self.run:
                raise Conflict("현재 시험이 끝난 후 다시 시도하세요.")
            if target not in self.next_output_at:
                raise ValueError("모터 또는 LED를 선택하세요.")
            if time.monotonic() < self.next_output_at[target]:
                raise Conflict("출력 종료 후 10초가 지나야 다시 켤 수 있습니다.")
            blockers = self.output_blockers()
            if blockers:
                raise Conflict(" ".join(blockers))
            snap = self.io.snapshot()
            if not snap.get("connected") or snap.get("physical_permit") is not True or snap.get("km2_on") is not False or snap.get("fault") or self.stop_wait_until:
                raise Conflict("운전 허가와 접촉기 정지 상태를 확인하세요.")
            maximum = 5 if target == "motor" else 60
            if not 0.1 <= seconds <= maximum:
                raise ValueError(f"시험 시간은 0.1초부터 {maximum}초까지입니다.")
            self.cancel.clear()
            now = time.monotonic()
            run = {"id": str(uuid.uuid4()), "target": target, "deadline": now + seconds,
                   "last_heartbeat": now, "started": now, "feedback_seen": False}
            self.seen.append(request_id)
            # Record before energizing; disk failure must not leave an untracked output.
            self.store.event("BENCH_OUTPUT_START", {"target": target, "seconds": seconds, "id": run["id"]})
            used = set(self.store.get("bench_outputs_used", []))
            self.store.put("bench_outputs_used", sorted(used | {target}))
            self.next_output_at[target] = now + seconds + 10
            self.run = run
            try:
                self.io.set_output(target, True, allowed=lambda: serial == self.stop_serial)
                self.last = self.io.snapshot()
            except Exception:
                self.stop("출력 설정 실패")
                raise
            self.generation += 1
            return self.status()

    def heartbeat(self, run_id):
        with self.lock:
            if self.run and self.run["id"] == run_id:
                self.run["last_heartbeat"] = time.monotonic()
            return {"active": bool(self.run and self.run["id"] == run_id)}

    def stop(self, reason="정지"):
        # Invalidate pending ON before waiting for a database operation or GPIO lock.
        with self.stop_lock:
            self.stop_serial += 1
        with self.lock:
            self.generation += 1
            self.cancel.set()
            old, self.run = self.run, None
            if old:
                self.next_output_at[old["target"]] = time.monotonic() + 10
            try:
                if self.io:
                    self.io.stop()
                    self.last = self.io.snapshot()
                    if old and old["target"] == "motor" and self.last.get("km2_on") is not False:
                        self.stop_wait_until = time.monotonic() + (self.setup.feedback_timeout_ms or 1000) / 1000
            except Exception as exc:
                self.error = "출력 OFF 확인 실패: " + str(exc)
            if old:
                try:
                    self.store.event("BENCH_OUTPUT_STOP", {"id": old["id"], "reason": reason, "error": self.error})
                except Exception:
                    self.error = self.error or "시험 기록 저장 실패"
            return self.status()

    def disconnect(self):
        with self.lock:
            self.stop("점검 종료")
            if self.stop_wait_until and self.last.get("km2_on") is not False:
                raise Conflict("접촉기 정지 상태를 확인하세요.")
            if self.io:
                try:
                    self.io.close()
                except Exception as exc:
                    self.error = "입출력 종료 실패: " + str(exc)
                    raise Conflict(self.error) from exc
                self.io = None
            self.last = {}
            self.stop_wait_until = None
            self.error = None
            return self.status()

    def _tick(self):
        with self.lock:
            if not self.io:
                return
            snap = self.io.snapshot()
            if not snap.get("connected") or snap.get("fault"):
                raise RuntimeError(snap.get("fault") or "입력 연결 끊김")
            raw = snap.get("di_raw")
            if not isinstance(raw, list) or len(raw) != 3:
                raise RuntimeError("입력값을 읽을 수 없습니다.")
            prev = self.last.get("di_raw")
            for i, value in enumerate(raw):
                if prev is not None and prev[i] != value:
                    self.transitions[i] += 1
                    self.changed_at[i] = time.time()
                    self.events.append({"channel": i + 1, "raw": value, "time": self.changed_at[i]})
            self.last = snap
            if self.stop_wait_until:
                if snap.get("km2_on") is False:
                    self.stop_wait_until = None
                elif time.monotonic() >= self.stop_wait_until:
                    self.error = "접촉기 정지 응답 없음"
                    self.stop(self.error)
            run = self.run
            if run:
                now = time.monotonic()
                if snap.get("physical_permit") is not True:
                    self.error = "운전 허가 끊김"
                elif now - run["last_heartbeat"] > 1.5:
                    self.stop("화면 연결 끊김")
                    return
                elif now >= run["deadline"]:
                    if run["target"] == "motor" and not (run["feedback_seen"] or snap.get("km2_on") is True):
                        self.error = "접촉기 가동 응답 없음"
                    self.stop(self.error or "시험 시간 종료")
                    return
                elif run["target"] == "motor":
                    if snap.get("km2_on") is True:
                        run["feedback_seen"] = True
                    if now - run["started"] > self.setup.feedback_timeout_ms / 1000 and snap.get("km2_on") is not True:
                        self.error = "접촉기 가동 응답 없음"
                elif snap.get("km2_on") is not False:
                    self.error = "LED 시험 중 접촉기 켜짐"
                if self.error:
                    self.stop(self.error)

    def _watch(self):
        while not self.closed.wait(0.01):
            try:
                self._tick()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                    self.stop("입출력 오류")

    def status(self):
        with self.lock:
            run = None
            if self.run:
                run = {"id": self.run["id"], "target": self.run["target"],
                       "remaining_ms": max(0, round((self.run["deadline"] - time.monotonic()) * 1000))}
            raw = self.last.get("di_raw")
            return {"connected": self.io is not None and bool(self.last.get("connected")),
                    "cooldown_ms": {target: max(0, round((deadline - time.monotonic()) * 1000))
                                    for target, deadline in self.next_output_at.items()},
                    "feedback": {"channel": 3, "line": self.config.di_lines[2],
                                 "raw": raw[2] if raw else None,
                                 "active": self.last.get("km2_on") if raw else None,
                                 "changes": self.transitions[2], "changed_at": self.changed_at[2]},
                    "native_busy": self.native_busy, "generation": self.generation,
                    "run": run, "error": self.error, "io": dict(self.last),
                    "sensors": [{"channel": i + 1, "line": self.config.di_lines[i],
                                 "raw": raw[i] if raw else None,
                                 "active": (raw[i] == self.setup.sensor_active_raw[i]) if raw and self.setup.sensor_active_raw[i] is not None else None,
                                 "changes": self.transitions[i], "changed_at": self.changed_at[i]} for i in range(2)],
                    "events": list(self.events), "output_blockers": self.output_blockers(),
                    "pins": {"motor": self.config.do_lines[0], "led": self.config.do_lines[1],
                             "feedback": self.config.di_lines[2], "chip": self.config.gpio_chip},
                    "setup": self.setup.model_dump(), "rfid": self.last_rfid}

    def rfid_test(self):
        from .rfid import Reader
        s = self.setup
        if not s.rfid_port:
            raise Conflict("RFID 포트를 선택하세요.")
        if not s.rfid_protocol_confirmed:
            raise Conflict("리더의 명령 규격을 확인한 후 RFID 설정을 저장하세요.")
        if self.run:
            raise Conflict("출력 시험을 먼저 정지하세요.")
        reader = None
        try:
            if self.cancel.is_set():
                raise Conflict("RFID 시험을 중지했습니다.")
            prod = self.production_io.snapshot()
            if prod.get("rfid_connected"):
                if s.rfid_port != self.config.rfid_port:
                    raise Conflict("생산 설정과 RFID 포트가 다릅니다.")
                if not prod.get("rfid_ready"):
                    raise Conflict("RFID 초기화를 확인하세요.")
                tags = self.production_io.inventory(s.rfid_window_ms, self.cancel)
            else:
                reader = Reader(s.rfid_port)
                reader.initialize()
                if self.cancel.is_set():
                    raise Conflict("RFID 시험을 중지했습니다.")
                tags = reader.inventory(s.rfid_window_ms, self.cancel)
            if self.cancel.is_set():
                raise Conflict("RFID 시험을 중지했습니다.")
            result = {"ok": len(tags) == 1, "tags": tags, "time": time.time(),
                      "detail": f"읽은 태그 {len(tags)}개"}
            self.last_rfid = result
            self.store.event("BENCH_RFID_RESULT", result)
            return result
        finally:
            if reader:
                reader.close()

    def close(self):
        self.closed.set()
        try:
            self.stop("서비스 종료")
            if self.io:
                self.io.close()
        finally:
            self.io = None
            self.thread.join(timeout=1)


def serial_ports():
    from serial.tools.list_ports import comports
    return [{"device": p.device, "name": p.description} for p in comports()]
