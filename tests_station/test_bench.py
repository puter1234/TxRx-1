import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from fastapi.testclient import TestClient

from station.app import create_app
from station.bench import Bench, BenchSetup, BenchGPIO
from station.controller import Conflict
from station.usb_camera import CameraProfile, parse_controls, parse_modes


class FakeGPIO:
    def __init__(self, config, setup):
        self.raw = [1, 1, 1]
        self.permit = True
        self.motor = self.led = False
        self.calls = []
        self.stuck = False
        self.fail_off = False

    def snapshot(self):
        return {"connected": True, "di_raw": self.raw[:], "km2_on": self.raw[2] == 0,
                "physical_permit": self.permit, "motor_requested": self.motor,
                "led_requested": self.led}

    def set_output(self, target, on, allowed=lambda: True):
        if on and not allowed():
            raise Conflict("STOP")
        self.calls.append((target, on))
        if target == "motor":
            self.motor = on
            if not self.stuck:
                self.raw[2] = 0 if on else 1
        else:
            self.led = on

    def stop(self):
        if self.fail_off:
            raise IOError("wire")
        self.motor = self.led = False
        if not self.stuck:
            self.raw[2] = 1

    def close(self):
        self.stop()


class FakeBackend:
    def __init__(self):
        self.profile = CameraProfile(device="/dev/video0", width=640, height=480, fps=30,
                                     controls={"focus_absolute": 10})
        self.fail_value = 77

    def inspect(self, device):
        return {"device": device, "identity": "test UVC device",
                "modes": [{"width": 640, "height": 480, "fps": 30, "pixel_format": "YUYV"},
                          {"width": 8000, "height": 6000, "fps": 3, "pixel_format": "YUYV"}],
                "controls": [{"name": "focus_absolute", "type": "int", "min": 0, "max": 100,
                              "step": 1, "value": self.profile.controls["focus_absolute"],
                              "flags": "", "menu": {}}],
                "current": self.profile.model_dump()}

    def apply(self, profile):
        self.profile = profile
        if profile.controls.get("focus_absolute") == self.fail_value:
            raise ValueError("camera rejected focus")
        return self.inspect(profile.device)

    def devices(self):
        return {"devices": [{"device": "/dev/video0", "name": "Test UVC"}], "error": None}


class FakeStream:
    def __init__(self, profile):
        self.profile = profile
        self.closed = False
        self.error = None

    def status(self):
        return {"connected": not self.closed, "frames": 100, "width": self.profile.width,
                "height": self.profile.height, "mean_received_fps": self.profile.fps, "error": None}

    def read_latest(self):
        return np.zeros((self.profile.height, self.profile.width, 3), np.uint8), {
            "seq": 101, "host_received_ns": time.monotonic_ns(), "sensor_timestamp": None}

    def after(self, minimum_ns, timeout):
        return self.read_latest()

    def close(self):
        self.closed = True


@pytest.fixture
def rig(tmp_path):
    app = create_app(tmp_path, bench_factory=lambda c, io, s: Bench(c, io, s, gpio_factory=FakeGPIO))
    camera = app.state.camera
    camera.backend = FakeBackend()
    camera.stream_factory = FakeStream
    with TestClient(app) as client:
        client.post("/api/auth/setup", json={"password": "123456"})
        yield client, app


def setup(client, **extra):
    body = BenchSetup(do_on_raw=1, permit_line=107, permit_active_raw=1,
                      feedback_timeout_ms=100, output_wiring_confirmed=True,
                      stop_circuit_confirmed=True, sensor_active_raw=[0, 0]).model_dump()
    body.update(extra)
    response = client.put("/api/bench/setup", json=body)
    assert response.status_code == 200, response.text
    return body


def pulse(client, target="led", seconds=5, **extra):
    body = {"target": target, "seconds": seconds,
            "generation": client.get("/api/bench").json()["generation"],
            "request_id": "test-" + str(uuid.uuid4()), "issued_at": time.time()}
    body.update(extra)
    return client.post("/api/bench/output", json=body)


def test_inputs_independent_of_output_setup_and_production_config(rig):
    c, app = rig
    assert c.post("/api/bench/io/connect", json={}).status_code == 200
    b = app.state.bench
    assert b.io.calls == []
    assert pulse(c, "motor", 1).status_code == 422  # Document wiring permits only 0.5-second tests.
    b.io.raw[0] = 0
    b._tick()
    sensor = c.get("/api/bench").json()["sensors"][0]
    assert sensor["raw"] == 0 and sensor["changes"] == 1 and sensor["active"] is None
    recipe = {"kind": "simple", "brand_id": "__simple__", "brand_revision": 1, "targets": {}, "channels": []}
    assert c.post("/api/sessions", json=recipe).status_code == 409
    assert c.post("/api/bench/io/disconnect", json={}).status_code == 200
    assert c.post("/api/sessions", json=recipe).status_code == 200
    assert c.post("/api/bench/io/connect", json={}).status_code == 409


def test_led_deadline_and_screen_loss_drop_outputs_without_counts(rig):
    c, app = rig
    setup(c)
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    assert pulse(c).status_code == 200
    assert b.io.led and not b.io.motor
    b.run["last_heartbeat"] -= 2
    b._tick()
    assert not b.io.led and b.run is None
    b.next_output_at["led"] = time.monotonic() - 1
    assert pulse(c, seconds=0.1).status_code == 200
    time.sleep(0.16)
    assert not b.io.led
    assert c.get("/api/status").json()["session"] is None
    assert c.get("/api/history").json()["inspections"] == []


def test_stop_invalidates_delayed_on_and_duplicate_does_not_reenergize(rig):
    c, app = rig
    setup(c)
    c.post("/api/bench/io/connect", json={})
    generation = c.get("/api/bench").json()["generation"]
    c.post("/api/bench/stop", json={})
    assert pulse(c, generation=generation).status_code == 409
    assert pulse(c, request_id="one-logical-test").status_code == 200
    c.post("/api/bench/stop", json={})
    assert pulse(c, request_id="one-logical-test").status_code == 200
    assert not app.state.bench.io.led
    assert pulse(c, issued_at=time.time() - 20).status_code == 409


def test_stop_during_pending_output_write_prevents_on(rig):
    c, app = rig
    setup(c)
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    entered, release = threading.Event(), threading.Event()
    original = b.store.event
    def delayed(kind, *args, **kwargs):
        if kind == "BENCH_OUTPUT_START":
            entered.set()
            assert release.wait(3)
        return original(kind, *args, **kwargs)
    b.store.event = delayed
    with ThreadPoolExecutor() as pool:
        start = pool.submit(pulse, c)
        assert entered.wait(2)
        stopping = pool.submit(c.post, "/api/bench/stop", json={})
        deadline = time.monotonic() + 2
        while b.stop_serial == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert b.stop_serial > 0
        release.set()
        assert start.result().status_code == 409
        assert stopping.result().status_code == 200
    assert not b.io.led and not any(on for _, on in b.io.calls)


def test_motor_permit_loss_feedback_failure_and_led_cross_output(rig):
    c, app = rig
    setup(c)
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    assert pulse(c, "motor", 1).status_code == 200
    b.io.permit = False
    b._tick()
    assert not b.io.motor and b.error == "운전 허가 끊김"
    assert pulse(c).status_code == 409
    c.post("/api/bench/io/disconnect", json={})
    c.post("/api/bench/io/connect", json={})
    b.io.stuck = True
    b.next_output_at["motor"] = time.monotonic() - 1
    assert pulse(c, "motor", 1).status_code == 200
    b.run["started"] -= 1
    b._tick()
    assert not b.io.motor and b.error == "접촉기 가동 응답 없음"


def test_short_motor_pulse_requires_feedback_before_completion(rig):
    c, app = rig
    setup(c, feedback_timeout_ms=1000)
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    b.io.stuck = True
    assert pulse(c, "motor", 0.5).status_code == 200
    with b.lock:
        b.run["deadline"] = time.monotonic() - 0.01
        b._tick()
    assert b.run is None and not b.io.motor
    assert b.error == "접촉기 가동 응답 없음"
    assert pulse(c).status_code == 409


@pytest.mark.parametrize("target", ["motor", "led"])
def test_output_requires_ten_seconds_after_stop_and_reconnect(rig, target):
    c, app = rig
    setup(c)
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    assert pulse(c, target, 1).status_code == 200
    assert c.post("/api/bench/stop", json={}).status_code == 200
    assert b.run is None and not b.io.motor and not b.io.led
    assert 9000 < b.status()["cooldown_ms"][target] <= 10000
    assert pulse(c, target, 1).status_code == 409
    c.post("/api/bench/io/disconnect", json={})
    c.post("/api/bench/io/connect", json={})
    assert pulse(c, target, 1).status_code == 409
    b.next_output_at[target] = time.monotonic() - 0.01
    assert pulse(c, target, 1).status_code == 200


def test_di3_reports_raw_feedback_and_transitions(rig):
    c, app = rig
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    b.io.raw[2] = 0
    b._tick()
    value = c.get("/api/bench").json()["feedback"]
    assert value["raw"] == 0 and value["active"] is True
    assert value["line"] == b.config.di_lines[2]
    assert value["changes"] == 1 and value["changed_at"] is not None
    c.post("/api/bench/io/disconnect", json={})
    value = c.get("/api/bench").json()["feedback"]
    assert value["raw"] is None and value["active"] is None


def test_led_off_first_and_led_on_without_motor_commissioning(rig):
    c, app = rig
    assert c.post("/api/bench/led/off", json={}).status_code == 200
    b = app.state.bench
    assert b.setup.do_on_raw is None
    assert b.io.calls == [("led", False)]
    assert pulse(c).status_code == 409  # Ten-second wait after OFF.
    b.next_output_at["led"] = time.monotonic() - 1
    b.io.permit = None
    assert pulse(c).status_code == 200
    b._tick()
    assert b.io.led and not b.io.motor
    assert c.post("/api/bench/led/off", json={}).status_code == 200
    assert not b.io.led and b.run is None
    assert pulse(c, "motor", 1).status_code == 422


def test_document_motor_test_without_extra_permit_has_feedback_and_time_limits(rig):
    c, app = rig
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    b.io.permit = None
    assert b.status()["output_blockers"] == []
    assert pulse(c, "motor", 1).status_code == 422
    assert pulse(c, "motor", 0.5).status_code == 200
    b._tick()
    assert b.run["feedback_seen"] is True
    b.io.raw[2] = 1
    b._tick()
    assert not b.io.motor and b.run is None
    assert b.error == "접촉기 가동 응답 끊김"


def test_document_motor_test_stops_when_start_power_is_absent(rig):
    c, app = rig
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    b.io.stuck = True
    assert pulse(c, "motor", 0.5).status_code == 200
    with b.lock:
        b.run["deadline"] = time.monotonic() - 1
        b._tick()
    assert not b.io.motor and b.run is None
    assert b.error == "접촉기 가동 응답 없음"


def test_real_gpio_led_off_requests_only_do2():
    from types import SimpleNamespace
    from enum import Enum
    from station.schema import StationConfig
    class Value(Enum):
        INACTIVE = 0
        ACTIVE = 1
    calls = []
    class Request:
        def set_value(self, line, value): calls.append(("set", line, value.value))
    def request(chip, consumer, config):
        calls.append(("request", chip, {line: setting.output_value.value for line, setting in config.items()}))
        return Request()
    gpio = BenchGPIO.__new__(BenchGPIO)
    gpio.config = StationConfig()
    gpio.setup = BenchSetup()
    gpio.outputs = {}
    gpio.Value = Value
    gpio.Direction = SimpleNamespace(OUTPUT="out")
    gpio.gpiod = SimpleNamespace(request_lines=request, LineSettings=lambda **kw: SimpleNamespace(**kw))
    gpio.set_output("led", False)
    assert calls == [("request", "/dev/gpiochip0", {52: 0}), ("set", 52, 0)]
    gpio.stop()
    assert all(call[1] == 52 for call in calls if call[0] == "set")


def test_ocr_reports_missing_runtime_package(rig):
    c, app = rig
    def missing():
        raise ModuleNotFoundError("No module named torch", name="torch")
    app.state.vision.load = missing
    response = c.post("/api/bench/ocr", json={})
    assert response.status_code == 200
    assert response.json() == {"ok": False, "detail": "OCR 실행 패키지가 설치되지 않았습니다: torch"}
    assert not app.state.bench.native_busy


def test_unconfirmed_off_remains_blocked(rig):
    c, app = rig
    setup(c)
    c.post("/api/bench/io/connect", json={})
    b = app.state.bench
    pulse(c, "motor", 2)
    b.io.stuck = True
    c.post("/api/bench/stop", json={})
    assert b.stop_wait_until
    b.stop_wait_until -= 1
    b._tick()
    assert b.error == "접촉기 정지 응답 없음"
    assert c.post("/api/bench/io/disconnect", json={}).status_code == 409
    b.io.raw[2] = 1
    b.io.stuck = False
    b._tick()
    assert c.post("/api/bench/io/disconnect", json={}).status_code == 200


def test_settings_require_existing_password_gate_and_pin_collision_rejected(rig):
    c, app = rig
    body = setup(c)
    body["permit_line"] = 51
    assert c.put("/api/bench/setup", json=body).status_code == 422
    c.post("/api/auth/logout", json={})
    assert c.put("/api/bench/setup", json=body).status_code == 403
    assert c.post("/api/bench/io/connect", json={}).status_code == 200
    assert c.post("/api/bench/stop", json={}).status_code == 200


def test_camera_controls_save_restore_and_real_capture_path(rig):
    c, app = rig
    profile = app.state.camera.backend.profile.model_dump()
    profile["controls"]["focus_absolute"] = 20
    result = c.post("/api/bench/camera/apply", json={"profile": profile, "save": True, "expected_revision": 0})
    assert result.status_code == 200, result.text
    assert result.json()["saved_profile"]["controls"]["focus_absolute"] == 20
    assert c.get("/api/camera/frame").headers["content-type"] == "image/jpeg"
    capture = c.post("/api/bench/camera/capture", json={})
    assert capture.status_code == 200, capture.text
    photo = capture.json()
    assert photo["width"] == 640 and photo["height"] == 480
    assert c.get(photo["url"]).content.startswith(b"\x89PNG")
    assert c.get("/api/bench/captures/latest").json()["id"] == photo["id"]
    assert c.get("/api/status").json()["session"] is None
    assert c.get("/api/history").json()["inspections"] == []
    profile["controls"]["focus_absolute"] = 77
    result = c.post("/api/bench/camera/apply", json={"profile": profile, "save": True, "expected_revision": 1})
    assert result.status_code == 422
    assert app.state.camera.status()["connected"]
    assert app.state.camera.backend.profile.controls["focus_absolute"] == 20
    assert app.state.store.get("usb_camera_profile")["controls"]["focus_absolute"] == 20
    assert c.post("/api/bench/camera/apply", json={"profile": profile, "save": True, "expected_revision": 0}).status_code == 409


def test_native_camera_setup_blocks_production_but_not_stop(rig):
    c, app = rig
    entered, release = threading.Event(), threading.Event()
    backend = app.state.camera.backend
    original = backend.inspect
    def delayed(device):
        entered.set()
        assert release.wait(3)
        return original(device)
    backend.inspect = delayed
    with ThreadPoolExecutor() as pool:
        reading = pool.submit(c.post, "/api/bench/camera/inspect", json={"device": "/dev/video0"})
        assert entered.wait(2)
        recipe = {"kind": "simple", "brand_id": "__simple__", "brand_revision": 1, "targets": {}, "channels": []}
        assert c.post("/api/sessions", json=recipe).status_code == 409
        assert c.post("/api/bench/stop", json={}).status_code == 200
        release.set()
        assert reading.result().status_code == 200


def test_v4l2_capabilities_parser_and_full_48mp_schema():
    modes = parse_modes("""
[0]: 'YUYV' (YUYV 4:2:2)
    Size: Discrete 8000x6000
        Interval: Discrete 0.333s (3.000 fps)
    Size: Discrete 1920x1080
        Interval: Discrete 0.017s (60.000 fps)
""")
    assert modes[0] == {"width": 8000, "height": 6000, "fps": 3.0, "pixel_format": "YUYV"}
    controls = parse_controls("""
          exposure_auto 0x009a0901 (menu) : min=0 max=3 default=3 value=3
                  1: Manual Mode
                  3: Aperture Priority Mode
         focus_absolute 0x009a090a (int) : min=0 max=1023 step=1 default=20 value=20 flags=inactive
""")
    assert controls["exposure_auto"]["menu"][1] == "Manual Mode"
    assert controls["focus_absolute"]["flags"] == "inactive"
    assert CameraProfile(device="/dev/video0", **modes[0]).width == 8000
    with pytest.raises(ValueError):
        CameraProfile(device="/dev/video0", width=640, height=480, fps=30, controls={"focus; touch": 1})


def test_input_adapter_never_acquires_output_until_test(monkeypatch):
    import enum
    import sys
    import types
    class Direction(enum.Enum):
        INPUT = 1
        OUTPUT = 2
    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1
    calls = []
    class Request:
        def get_values(self, lines):
            return [Value.ACTIVE] * len(lines)
        def get_value(self, line):
            return Value.ACTIVE
        def release(self):
            pass
    fake = types.SimpleNamespace(LineSettings=lambda **kw: kw,
                                 request_lines=lambda chip, **kw: (calls.append(kw) or Request()))
    monkeypatch.setitem(sys.modules, "gpiod", fake)
    monkeypatch.setitem(sys.modules, "gpiod.line", types.SimpleNamespace(Direction=Direction, Value=Value))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from station.schema import StationConfig
    gpio = BenchGPIO(StationConfig(), BenchSetup())
    try:
        assert gpio.snapshot()["di_raw"] == [1, 1, 1]
        assert len(calls) == 1
        assert set(calls[0]["config"]) == {105, 144, 106}
        assert all(v["direction"] == Direction.INPUT for v in calls[0]["config"].values())
    finally:
        gpio.close()
