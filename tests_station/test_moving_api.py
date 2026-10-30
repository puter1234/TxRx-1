"""Exercise real API, monitor, GPIO adapter and SQLite with synthetic devices."""
import enum
import json
import sys
import threading
import time
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from station.app import create_app
from station.flow import FlowCycle
from station.schema import FlowSettings, StationConfig, WorkPreset
from test_api import EPC, login


@pytest.fixture
def line(tmp_path, monkeypatch, brand):
    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1
    class Direction(enum.Enum):
        INPUT = 1
        OUTPUT = 2
    class GPIO:
        def __init__(self):
            self.values = {105: 1, 144: 1, 106: 1, 107: 1}
            self.lock = threading.RLock()
        def get_values(self, lines):
            with self.lock:
                return [Value(self.values.get(line, 0)) for line in lines]
        def get_value(self, line): return self.get_values([line])[0]
        def set_values(self, values):
            with self.lock:
                self.values.update({k: v.value for k, v in values.items()})
                if 51 in values:
                    self.values[106] = 1 - values[51].value
        def set_value(self, line, value): self.set_values({line: value})
        def sensor(self, number, raw): self.set_value((105, 144)[number - 1], Value(raw))
        def release(self): pass
    gpio = GPIO()
    fake = SimpleNamespace(LineSettings=lambda **kw: kw, request_lines=lambda *a, **kw: gpio)
    monkeypatch.setitem(sys.modules, "gpiod", fake)
    monkeypatch.setitem(sys.modules, "gpiod.line", SimpleNamespace(Direction=Direction, Value=Value))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    class Reader:
        def __init__(self, *args):
            self.port = SimpleNamespace(is_open=True)
            self.initialized = False
            self.last_error = None
        def initialize(self, power=2600): self.power = power; self.initialized = True
        def set_power(self, power): self.power = power
        def inventory(self, *args): return [{"epc": EPC}, {"epc": EPC}]
        def inventory_bench(self, *args): return self.inventory(*args)
        def inventory_once(self, *args): return self.inventory(*args)
        def close(self): self.port.is_open = False
    monkeypatch.setattr("station.hardware.Reader", Reader)
    class Camera:
        def __init__(self):
            self.connected = True
            self.retries = 0
            self.seq = 1
            self.frame = np.zeros((64, 64, 3), np.uint8)
        def status(self): return {"connected": self.connected, "frames": self.seq}
        def connect(self): self.retries += 1; self.connected = True
        def close(self): self.connected = False
        def verify_fixed_controls(self): pass
        def read_latest(self):
            return self.frame.copy(), {"seq": self.seq, "host_received_ns": time.monotonic_ns()}
        def after(self, *args): return self.read_latest()
        def object_at(self, center):
            frame = np.zeros((64, 64, 3), np.uint8)
            y = int(center * 64)
            frame[y-3:y+3, 27:35] = 255
            self.frame = frame
            self.seq += 1
    class Vision:
        def status(self): return {"busy": False, "local_assets_present": True}
        def load(self): pass
        def inspect_frame(self, frame, brand, recipe):
            return {"observations": {"ocr": dict(recipe.targets)}, "failures": []}
    # These values are test fixtures, not field commissioning evidence.
    reader_path = tmp_path / "reader"
    reader_path.touch()
    config = StationConfig(mode="HARDWARE", do_on_raw=1, permit_line=107, permit_active_raw=1,
                           speed_line=108, rfid_port=str(reader_path), rfid_window_ms=100,
                           commissioning={"feedback_timeout_ms": 100, "signed_by": "TEST ONLY",
                            "evidence_reference": "SYNTHETIC", "physical_permit_observed": True,
                            "power_cycle_off_verified": True, "process_kill_off_verified": True,
                            "os_hang_off_verified": True, "stop_chain_verified": True,
                            "rfid_protocol_verified": True})
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    monkeypatch.setenv("TXRX_CONFIG", str(config_path))
    camera, vision = Camera(), Vision()
    app = create_app(tmp_path / "data", camera=camera, vision=vision)
    # Most cases begin after startup. Startup protection has a dedicated case below.
    app.state.controller.io.motor_ready_at = time.monotonic() - 1
    app.state.store.save_brand(brand.model_dump(), None, "test")
    with TestClient(app) as client:
        login(client)
        yield SimpleNamespace(client=client, app=app, gpio=gpio, camera=camera, vision=vision,
                              io=app.state.controller.io)


def wait_state(line, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = line.client.get("/api/status")
        assert response.status_code == 200, response.text
        state = response.json()
        if predicate(state): return state
        time.sleep(.01)
    raise AssertionError(json.dumps(state, ensure_ascii=False))


def issue(line, action, expected=200):
    state = line.client.get("/api/status").json()
    response = line.client.post("/api/commands", json={"request_id": str(uuid.uuid4()),
        "session_id": state["session"]["id"], "action": action, "reason": "제품 상태 확인 완료",
        "expected_revision": state["revision"], "issued_at": time.time()})
    assert response.status_code == expected, response.text
    return response


def prepare(line, channels=(), target=2, **flow):
    kind = "condition" if channels else "vision" if flow.get("counter", "sensor") != "sensor" else "simple"
    preset = WorkPreset(id="test-work", name="공정 시험", kind=kind,
        brand_id="hazzys" if channels else "__simple__", channels=list(channels),
        flow=FlowSettings(capture_delay_ms=0, rfid_delay_ms=0, di1_debounce_ms=5, di2_debounce_ms=5,
                          result_timeout_ms=1000, departure_timeout_ms=2000, **flow))
    response = line.client.post("/api/presets", json={"preset": preset.model_dump()})
    assert response.status_code == 200, response.text
    response = line.client.post("/api/presets/test-work/start", json={"preset_revision": 1,
        "brand_revision": 1, "targets": {"style": "HUTS6C612", "color": "N3", "size": "095"} if channels else {},
        "target_count": target})
    assert response.status_code == 200, response.text
    return wait_state(line, lambda s: s["can_start"])


@pytest.mark.parametrize("channels", [(), ("rfid",), ("ocr", "rfid")])
def test_preset_to_target_completion_with_real_gpio_adapter(line, channels):
    prepare(line, channels, low_speed_ms=80)
    if not channels:
        line.camera.connected = False
        line.io.reader.port.is_open = False
    issue(line, "start")
    assert line.io.snapshot()["speed_requested"]
    for count in (1, 2):
        line.gpio.sensor(1, 0)
        wait_state(line, lambda s: s["session"]["active_product"] is not None)
        assert line.io.snapshot()["led_requested"]
        line.gpio.sensor(1, 1)
        line.gpio.sensor(2, 0)
        final = wait_state(line, lambda s: s["session"]["count"] == count)
        assert not line.io.snapshot()["led_requested"]
        line.gpio.sensor(2, 1)
        time.sleep(.03)
    assert final["session"]["phase"] == "DONE"
    assert not line.io.snapshot()["motor_requested"] and not line.io.snapshot()["speed_requested"]
    rows = line.app.state.store.inspection_rows()
    assert len(rows) == 2 and all(r["status"] == "PASS" and r["di2_count"] == 1 for r in rows)
    assert len({r["product_id"] for r in rows}) == 2
    issue(line, "start", 409)


def test_manual_restart_selects_high_speed_again(line):
    prepare(line)
    issue(line, "start")
    assert line.io.snapshot()["speed_requested"]
    issue(line, "stop")
    assert not line.io.snapshot()["motor_requested"]
    assert not line.io.snapshot()["speed_requested"]
    # Advance the synthetic hardware's restart deadline; the five-second
    # interlock has separate coverage for every motor-off path.
    line.io.motor_ready_at = time.monotonic() - 1
    wait_state(line, lambda s: s["can_start"])
    issue(line, "start")
    assert line.io.snapshot()["motor_requested"] and line.io.snapshot()["speed_requested"]


@pytest.mark.parametrize("target", ["speed", "motor"])
def test_failed_start_clears_motor_and_speed_outputs(line, monkeypatch, target):
    from test_controller import command

    prepare(line)
    original = getattr(line.io, target)

    def fail_on(value, *args, **kwargs):
        if value:
            raise RuntimeError("test output failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(line.io, target, fail_on)
    controller = line.app.state.controller
    with pytest.raises(RuntimeError, match="test output failure"):
        controller.command(command(controller, "start"), "test")
    assert not line.io.snapshot()["motor_requested"]
    assert not line.io.snapshot()["speed_requested"]


def test_rejected_direct_session_creation_cannot_replace_running_counter(line, monkeypatch):
    calls = []
    original = FlowCycle.prepare
    def record(self, recipe):
        calls.append(recipe["flow"]["counter"])
        return original(self, recipe)
    monkeypatch.setattr(FlowCycle, "prepare", record)
    prepare(line)
    issue(line, "start")
    response = line.client.post("/api/sessions", json={"kind": "vision", "brand_id": "__simple__",
        "brand_revision": 1, "targets": {}, "channels": [], "flow": {"counter": "cvzone"}})
    assert response.status_code == 409, response.text
    assert calls == ["sensor"]
    assert line.client.get("/api/status").json()["session"]["recipe"]["kind"] == "simple"


def test_adjustment_reaching_target_cannot_start_an_extra_product(line):
    state = prepare(line)
    response = line.client.post("/api/adjustments", json={"request_id": str(uuid.uuid4()),
        "session_id": state["session"]["id"], "delta": 2, "reason": "실제 수량 대조"})
    assert response.status_code == 200, response.text
    state = line.client.get("/api/status").json()
    assert state["session"]["phase"] == "DONE" and not state["can_start"]
    issue(line, "start", 409)
    assert not line.io.snapshot()["motor_requested"]


def test_gpio_reset_reports_cleared_fault_immediately(line):
    line.io.fault = "IO_LEASE_EXPIRED"
    line.io._read()
    line.io.reset()
    assert line.io.snapshot()["fault"] is None


@pytest.mark.parametrize("stop_method", ["stop", "motor_off", "reset", "permit_loss"])
def test_gpio_enforces_five_seconds_on_every_off_path(line, monkeypatch, stop_method):
    io = line.io
    clock = [time.monotonic()]
    monkeypatch.setattr("station.hardware.time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    with io.lock:
        io.motor(True)
        io.light(True)
        io.speed(True)
        io.speed(False)
        assert io.snapshot()["motor_requested"]  # DO4 does not stop DO1.
        if stop_method == "motor_off":
            io.motor(False)
        elif stop_method == "permit_loss":
            line.gpio.values[107] = 0
            io._read()
            line.gpio.values[107] = 1
            io.reset()
        else:
            getattr(io, stop_method)()
        assert not io.snapshot()["motor_requested"]
        assert io.snapshot()["motor_restart_ms"] == 5000
        clock[0] += 4.999
        with pytest.raises(RuntimeError, match="모터 정지 후 5초"):
            io.motor(True)
        assert line.gpio.values[51] == 0
        io.reset()
        assert 0 < io.snapshot()["motor_restart_ms"] <= 2
        clock[0] += .002
        io.motor(True)
        assert line.gpio.values[51] == 1
        io.stop()


def test_gpio_snapshot_reports_current_output_requests_without_waiting_for_poll(line):
    with line.io.lock:
        line.io.motor(True)
        assert line.io.snapshot()["motor_requested"]
        line.io.light(True)
        assert line.io.snapshot()["led_requested"]
        line.io.speed(True)
        assert line.io.snapshot()["speed_requested"]
        line.io.stop()
        snapshot = line.io.snapshot()
        assert not any(snapshot[key] for key in ("motor_requested", "led_requested", "speed_requested"))


def test_two_separate_vision_products_do_not_share_counted_track(line):
    pytest.importorskip("cvzone")
    prepare(line, counter="cvzone", min_area=10, match_distance=.3, track_lost_ms=10000)
    issue(line, "start")
    time.sleep(.03)
    for count in (1, 2):
        line.camera.object_at(.4)
        line.gpio.sensor(1, 0)
        wait_state(line, lambda s: bool(s["session"]["active_product"]))
        wait_state(line, lambda s: bool((s.get("tracking") or {}).get("boxes")) and
                   s["tracking"]["boxes"][0][1] < .5)
        line.gpio.sensor(1, 1)
        line.camera.object_at(.6)
        wait_state(line, lambda s: bool((s.get("tracking") or {}).get("crossed")))
        line.gpio.sensor(2, 0)
        wait_state(line, lambda s: s["session"]["count"] == count)
        line.gpio.sensor(2, 1)
        time.sleep(.03)
    assert line.client.get("/api/status").json()["session"]["phase"] == "DONE"


def test_late_native_tracking_blocks_next_product_without_adding_count(line, monkeypatch):
    pytest.importorskip("cvzone")
    from station.counting import ObjectCounter
    entered, release, overlapped = threading.Event(), threading.Event(), threading.Event()
    original = ObjectCounter.detect
    calls = [0]
    def detect(self, frame):
        calls[0] += 1
        if calls[0] == 3:
            entered.set()
            if not release.wait(3): raise TimeoutError("test did not release detector")
        elif calls[0] > 3 and not release.is_set():
            overlapped.set()
        return original(self, frame)
    monkeypatch.setattr(ObjectCounter, "detect", detect)
    prepare(line, counter="cvzone", min_area=10, match_distance=.3, track_lost_ms=10000)
    issue(line, "start")
    try:
        line.camera.object_at(.4)
        line.gpio.sensor(1, 0)
        wait_state(line, lambda s: bool((s.get("tracking") or {}).get("boxes")))
        line.gpio.sensor(1, 1)
        line.camera.object_at(.6)
        wait_state(line, lambda s: bool((s.get("tracking") or {}).get("crossed")))
        line.camera.object_at(.62)
        assert entered.wait(2)
        line.gpio.sensor(2, 0)
        wait_state(line, lambda s: s["session"]["count"] == 1)
        line.gpio.sensor(2, 1)
        time.sleep(.03)
        line.camera.object_at(.4)
        line.gpio.sensor(1, 0)
        state = wait_state(line, lambda s: s["session"]["phase"] == "FAULT")
        assert state["session"]["count"] == 1 and not state["session"]["active_product"]
        assert not line.io.snapshot()["motor_requested"]
        assert not overlapped.is_set()
        release.set()
        wait_state(line, lambda s: "장비 처리 종료 대기" not in s["blockers"])
        time.sleep(.05)
        state = line.client.get("/api/status").json()
        assert state["session"]["count"] == 1 and state["session"]["phase"] == "FAULT"
        assert not line.io.snapshot()["motor_requested"]
        assert len(line.app.state.store.inspection_rows()) == 1
    finally:
        release.set()


def test_target_correction_waits_for_removal_of_an_interrupted_product(line):
    state = prepare(line)
    issue(line, "start")
    time.sleep(.03)
    line.gpio.sensor(1, 0)
    wait_state(line, lambda s: bool(s["session"]["active_product"]))
    issue(line, "stop")
    wait_state(line, lambda s: not s["busy"])
    response = line.client.post("/api/adjustments", json={"request_id": str(uuid.uuid4()),
        "session_id": state["session"]["id"], "delta": 2, "reason": "실제 수량 대조"})
    assert response.status_code == 200, response.text
    assert line.client.get("/api/status").json()["session"]["phase"] == "PAUSED"
    line.gpio.sensor(1, 1)
    time.sleep(.03)
    issue(line, "discard")
    state = line.client.get("/api/status").json()
    assert state["session"]["phase"] == "DONE" and not state["session"]["active_product"]
    assert not line.io.snapshot()["motor_requested"]


@pytest.mark.parametrize("phase", ["DONE", "FINISHED", "ABORTED"])
def test_finished_work_rejects_new_adjustments(controller, recipe, phase):
    from station.controller import Conflict
    from station.schema import Adjustment
    controller.new_session(recipe)
    controller.session["phase"] = phase
    controller.changed("TEST_ENDED")
    with pytest.raises(Conflict):
        controller.adjust(Adjustment(request_id=str(uuid.uuid4()), session_id=controller.session["id"],
                                     delta=1, reason="실제 수량 대조"), "test")
    assert controller.session["count"] == 0


def test_stop_write_failure_at_target_remains_faulted_until_reset(line, monkeypatch):
    prepare(line, target=1)
    issue(line, "start")
    line.gpio.sensor(1, 0)
    wait_state(line, lambda s: bool(s["session"]["active_product"]))
    line.gpio.sensor(1, 1)
    original = line.io.stop
    failing = [True]
    def stop():
        if failing[0]: raise OSError("output write failed")
        original()
    monkeypatch.setattr(line.io, "stop", stop)
    try:
        line.gpio.sensor(2, 0)
        state = wait_state(line, lambda s: s["session"]["count"] == 1)
        assert state["session"]["phase"] == "FAULT"
        assert state["session"]["fault"] == "IO_STOP_UNCONFIRMED"
        assert state["last_result"]["status"] == "PASS" and not state["can_start"]
        failing[0] = False
        line.gpio.sensor(2, 1)
        issue(line, "reset")
        state = line.client.get("/api/status").json()
        assert state["session"]["phase"] == "DONE" and state["session"]["count"] == 1
        assert not line.io.snapshot()["motor_requested"]
    finally:
        failing[0] = False


def test_missing_setup_records_are_one_reason_for_the_worker(line):
    prepare(line)
    line.app.state.controller.config.commissioning.signed_by = ""
    blockers = line.client.get("/api/status").json()["blockers"]
    assert blockers == ["설치 점검 기록 없음"]


def test_reset_during_a_held_field_stop_says_why_and_keeps_the_fault(line):
    prepare(line, target=2)
    issue(line, "start")
    line.gpio.values[107] = 0
    fault = wait_state(line, lambda s: s["session"]["phase"] == "FAULT")["session"]["fault"]
    response = issue(line, "reset", expected=409)
    assert response.json()["detail"] == "현장 정지/새 START 상태를 확인하세요."
    session = line.client.get("/api/status").json()["session"]
    assert (session["phase"], session["fault"]) == ("FAULT", fault)
    line.gpio.values[107] = 1
    issue(line, "reset")
    assert line.client.get("/api/status").json()["session"]["fault"] is None


@pytest.mark.parametrize("manual_stop", [False, True])
def test_camera_reconnect_preserves_product_and_obeys_manual_stop(line, monkeypatch, manual_stop):
    prepare(line, ("ocr", "rfid"), target=1, reconnect_interval_ms=100)
    initial_connections = line.camera.retries
    issue(line, "start")
    line.gpio.sensor(1, 0)
    state = wait_state(line, lambda s: bool(s["session"]["active_product"]))
    product = state["session"]["active_product"]
    line.gpio.sensor(1, 1)
    connecting, release, returned = threading.Event(), threading.Event(), threading.Event()
    original = line.camera.connect
    def connect():
        connecting.set()
        if not release.wait(3): raise TimeoutError("test did not release camera connection")
        original()
        returned.set()
    monkeypatch.setattr(line.camera, "connect", connect)
    try:
        line.camera.connected = False
        state = wait_state(line, lambda s: s["session"]["phase"] == "CAMERA_WAIT")
        assert state["session"]["active_product"] == product
        assert not line.io.snapshot()["motor_requested"]
        assert connecting.wait(2)
        if manual_stop:
            # The HTTP stop must return while the native connection call is blocked.
            issue(line, "stop")
            assert not returned.is_set()
            assert not line.io.snapshot()["motor_requested"]
        release.set()
        assert returned.wait(2)
        if manual_stop:
            wait_state(line, lambda s: s["session"]["phase"] == "PAUSED" and not s["busy"])
            # Allow several watch cycles after the late connection result.
            time.sleep(.15)
            state = line.client.get("/api/status").json()
            assert state["session"]["phase"] == "PAUSED" and state["session"]["count"] == 0
            assert state["session"]["active_product"] == product
            assert not line.io.snapshot()["motor_requested"]
            issue(line, "discard")
            state = line.client.get("/api/status").json()
            assert state["session"]["phase"] == "READY" and not state["session"]["active_product"]
        else:
            # A successful reconnection must still wait out the motor OFF interval.
            time.sleep(.15)
            assert not line.io.snapshot()["motor_requested"]
            assert line.io.snapshot()["motor_restart_ms"] > 0
            state = wait_state(line, lambda s: s["session"]["phase"] == "FEEDING", timeout=6)
            assert state["session"]["active_product"] == product
            assert line.io.snapshot()["motor_requested"]
            line.gpio.sensor(2, 0)
            state = wait_state(line, lambda s: s["session"]["phase"] == "DONE")
            assert state["session"]["count"] == 1
            rows = line.app.state.store.inspection_rows()
            assert len(rows) == 1 and rows[0]["product_id"] == product and rows[0]["status"] == "PASS"
        assert line.camera.retries == initial_connections + 1
    finally:
        release.set()
