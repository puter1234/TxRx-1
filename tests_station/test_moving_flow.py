import asyncio
import time
from types import SimpleNamespace
import numpy as np
import pytest
from station.schema import Recipe, FlowSettings, StationConfig
from station.flow import FlowCycle, SensorEdge
from station.counting import CrossingTracker
from station.controller import Controller
from test_controller import command


class IO:
    def __init__(self):
        self.raw = [1, 1, 1]
        self.on = self.led = self.high = False
        self.log = []
    def stop(self):
        self.on = self.led = self.high = False
        self.log.append("stop")
    def motor(self, value, allowed=lambda: True):
        assert not value or allowed()
        self.on = value
        self.log.append(("motor", value))
    def light(self, value, allowed=lambda: True):
        self.led = value
        self.log.append(("led", value))
    def speed(self, value, allowed=lambda: True):
        assert not value or allowed()
        self.high = value
        self.log.append(("speed", value))
    def snapshot(self):
        return {"connected": True, "fault": None, "di_raw": self.raw.copy(), "km2_on": self.on, "physical_permit": True, "rfid_ready": True}
    def blockers(self): return []
    def inventory(self, *args):
        assert self.on
        self.log.append("rfid")
        return [{"epc": "1D44D280281B70D75A8DF0000E114D7A"}]
    def inventory_once(self, *args): return self.inventory(*args)


class Camera:
    def __init__(self, io): self.io, self.connected, self.retries = io, True, 0
    def status(self): return {"connected": self.connected, "frames": 20}
    def verify_fixed_controls(self): self.io.log.append("verify")
    def after(self, *args):
        self.io.log.append("capture")
        return np.zeros((50, 50, 3), dtype=np.uint8), {"seq": 10, "host_received_ns": time.monotonic_ns()}
    def read_latest(self): return self.after()
    def connect(self): self.retries += 1; self.connected = True


class Vision:
    def status(self): return {"busy": False, "local_assets_present": True}
    def inspect_frame(self, frame, brand, recipe): return {"observations": {"ocr": recipe.targets}, "failures": []}


def rig(controller, monkeypatch, recipe=None, **settings):
    io = IO()
    c = Controller(controller.store, io, StationConfig())
    # Steps sensors a few ms apart; the same-product gap is tested on its own.
    flow = FlowSettings(**{"di1_debounce_ms": 0, "di2_debounce_ms": 0, "sensor_gap_ms": 0, **settings})
    r = recipe or Recipe(kind="simple", brand_id="__simple__", brand_revision=1, targets={}, channels=[])
    r.flow = flow
    c.new_session(r)
    c.session["phase"] = "FEEDING"
    io.on = True
    camera = Camera(io)
    cycle = FlowCycle(c, camera, None, Vision())
    clock = [100.0]
    monkeypatch.setattr("station.flow.time", SimpleNamespace(monotonic=lambda: clock[0]))
    return c, io, camera, cycle, clock


def test_sensor_debounce_requires_clear_and_counts_once():
    edge = SensorEdge()
    assert not edge.update(0, 0, 20)
    assert not edge.update(0, 1, 20)
    assert not edge.update(1, 2, 20)
    assert not edge.update(1, 2.02, 20)
    assert not edge.update(0, 3, 20)
    assert not edge.update(1, 3.01, 20)
    assert not edge.update(0, 3.015, 20)
    assert edge.update(0, 3.04, 20)
    assert not edge.update(0, 4, 20)


def test_sensor_clear_shorter_than_the_gap_keeps_the_same_product():
    edge = SensorEdge()
    assert not edge.update(1, 0, 0, 300)
    assert not edge.update(1, .31, 0, 300)
    assert edge.update(0, .4, 0, 300)
    assert not edge.update(1, .5, 0, 300)
    assert not edge.update(1, .6, 0, 300)
    assert not edge.update(0, .7, 0, 300)
    assert not edge.update(1, 1, 0, 300)
    assert not edge.update(1, 1.31, 0, 300)
    assert edge.update(0, 1.4, 0, 300)


def test_di1_flicker_within_one_product_counts_once(controller, monkeypatch):
    c, io, _, cycle, clock = rig(controller, monkeypatch, sensor_gap_ms=300)
    async def run():
        await cycle.tick()
        clock[0] += .31
        await cycle.tick()
        for raw in (0, 1, 0):
            io.raw[0] = raw
            clock[0] += .05
            await cycle.tick()
        assert io.on and c.session["fault"] is None
        io.raw[0] = 1
        clock[0] += .05
        await cycle.tick()
        io.raw[1] = 0
        clock[0] += .05
        await cycle.tick()
        assert c.session["count"] == 1 and c.session["fault"] is None
    asyncio.run(run())


def test_simple_count_ignores_camera_and_waits_for_di2(controller, monkeypatch):
    c, io, camera, cycle, clock = rig(controller, monkeypatch, low_speed_ms=200)
    camera.connected = False
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        assert io.on and io.led and not io.high and c.session["count"] == 0
        clock[0] += .21
        await cycle.tick()
        assert io.high and io.on
        io.raw[1] = 0
        await cycle.tick()
        assert not io.led and io.on and c.session["count"] == 1
        await cycle.tick()
        assert c.session["count"] == 1
        assert "capture" not in io.log and camera.retries == 0
    asyncio.run(run())


@pytest.mark.parametrize("low_speed_ms,debounce_ms", [(0, 0), (0, 20), (10, 20), (20, 20), (50, 20)])
def test_short_low_speed_hold_is_not_restarted_by_debounced_di1(controller, monkeypatch, low_speed_ms, debounce_ms):
    c, io, _, cycle, clock = rig(controller, monkeypatch, low_speed_ms=low_speed_ms)
    c.session["recipe"]["flow"]["di1_debounce_ms"] = debounce_ms
    io.log.clear()

    async def run():
        await cycle.tick()
        clock[0] = 100.1
        await cycle.tick()
        assert cycle.edges[0].armed
        clock[0] = 100.2
        io.raw[0] = 0
        await cycle.tick()
        assert io.on and io.led
        assert io.high is (low_speed_ms == 0)
        clock[0] = 100.221
        await cycle.tick()
        assert cycle.pending is not None
        assert io.high is (low_speed_ms <= 20)
        clock[0] = 100.3
        await cycle.tick()
        assert io.high and io.on
        io.raw[1] = 0
        await cycle.tick()
        assert c.session["count"] == 1 and io.high and io.on
        assert "stop" not in io.log

    asyncio.run(run())


def test_independent_camera_rfid_and_speed_deadlines(controller, recipe, monkeypatch):
    recipe.channels = ["ocr", "rfid"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, capture_delay_ms=0, rfid_delay_ms=100, low_speed_ms=200)
    async def spin():
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        await spin()
        assert "capture" in io.log and "rfid" not in io.log and not io.high
        clock[0] += .11
        await spin()
        assert "rfid" in io.log and not io.high and c.session["count"] == 0
        clock[0] += .1
        await cycle.tick()
        assert io.high
        io.raw[1] = 0
        await spin()
        assert c.session["count"] == 1 and c.last_result["di2_count"] == 1
        assert c.last_result["status"] == "PASS" and io.on
    asyncio.run(run())


def test_moving_capture_uses_available_due_frames_without_settling_wait(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, _ = rig(controller, monkeypatch, recipe, capture_count=2, capture_interval_ms=0)
    frames = [np.full((50, 50, 3), value, np.uint8) for value in (12, 34)]
    sequence = [10]
    camera.status = lambda: {"connected": True, "frames": sequence[0]}

    def latest():
        seq = sequence[0]
        sequence[0] += 1
        return frames[seq - 10], {"seq": seq, "host_received_ns": time.monotonic_ns()}

    def forbidden(*args):
        raise AssertionError("Moving capture must not wait for two additional frames")

    camera.read_latest = latest
    camera.after = forbidden

    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        p = cycle.pending
        assert cycle.camera_task is None
        p["start"] = 0
        await cycle.capture(p, cycle.flow())
        assert [meta["seq"] for _, meta in p["frames"]] == [10, 11]
        assert p["inspection"]["capture_delay_actual_ms"] == pytest.approx(p["frames"][0][1]["host_received_ns"] / 1e6)
        assert all(actual is expected for (actual, _), expected in zip(p["frames"], frames))
        assert p["observations"]["ocr"] == recipe.targets and not p["failures"]
        assert io.on

    asyncio.run(run())


@pytest.mark.parametrize("manual_stop", [False, True])
def test_camera_reconnect_interval_and_stop_priority(controller, recipe, monkeypatch, manual_stop):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, reconnect_interval_ms=200)
    async def run():
        await cycle.tick()
        camera.connected = False
        await cycle.tick()
        assert c.session["phase"] == "CAMERA_WAIT" and not io.on
        clock[0] += .1
        await cycle.tick()
        assert camera.retries == 0
        clock[0] += .11
        await cycle.tick()
        if manual_stop:
            c.command(command(c, "stop"), "test")
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert camera.retries == 1
        assert io.on is (not manual_stop)
        assert c.session["phase"] == ("PAUSED" if manual_stop else "FEEDING")
    asyncio.run(run())


def test_di2_without_product_stops(controller, monkeypatch):
    c, io, _, cycle, _ = rig(controller, monkeypatch)
    async def run():
        await cycle.tick()
        io.raw[1] = 0
        await cycle.tick()
        assert c.session["fault"] == "DI2_WITHOUT_DI1" and not io.on
    asyncio.run(run())


def test_early_di1_is_preserved_as_unresolved(controller, monkeypatch):
    c, io, _, cycle, _ = rig(controller, monkeypatch)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        io.raw[0] = 1
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        assert not io.on and c.session["count"] == 0
        assert c.session["fault"] == "EARLY_DI1_UNRESOLVED"
    asyncio.run(run())


def test_directional_tracks_never_count_jitter_twice():
    cfg = FlowSettings(counter="cvzone", match_distance=.5, hysteresis=.02)
    tracker = CrossingTracker(cfg)
    box = lambda y: [[.4, y-.02, .6, y+.02]]
    assert tracker.update(box(.2), 0) == []
    assert tracker.update(box(.49), .1) == []
    assert tracker.update(box(.51), .2) == []
    assert tracker.update(box(.6), .3) == [1]
    assert tracker.update(box(.3), .4) == []
    assert tracker.update(box(.7), .5) == []
    assert tracker.total == 1
    assert tracker.update(box(.7), 2) == [] # new track first seen beyond line is not counted


def test_camera_recovery_preserves_product_and_restarts(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, capture_delay_ms=100, reconnect_interval_ms=100)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        product = c.session["active_product"]
        camera.connected = False
        await cycle.tick()
        assert not io.on and io.led
        clock[0] += .11
        await cycle.tick()
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert io.on and c.session["active_product"] == product and c.session["count"] == 0
        clock[0] += .11
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        io.raw[1] = 0
        await cycle.tick()
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert c.session["count"] == 1 and c.last_result["product_id"] == product
    asyncio.run(run())


def test_di2_during_outage_never_passes_uncaptured_product(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, reconnect_interval_ms=100)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        camera.connected = False
        await cycle.tick()
        io.raw[1] = 0
        await cycle.tick()
        assert not io.led
        clock[0] += .11
        await cycle.tick()
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert not io.on and c.session["count"] == 0
        assert c.session["fault"] == "CAMERA_CAPTURE_MISSED"
    asyncio.run(run())


def test_mismatch_stops_before_di2(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, capture_delay_ms=0)
    cycle.vision.inspect_frame = lambda *a: {"observations": {"ocr": {"size": "999"}}, "failures": []}
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert not io.on and c.session["phase"] == "HOLD"
        assert c.session["count"] == 0 and c.session["failed"] == 1
    asyncio.run(run())


def test_real_cvzone_contours_cross_once():
    pytest.importorskip("cvzone")
    from station.counting import ObjectCounter
    counter = ObjectCounter(FlowSettings(counter="cvzone", min_area=10, match_distance=.5))
    results = []
    for i, y in enumerate((10, 22, 36, 45)):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[y:y+8, 20:28] = 255
        results.extend(counter.update(frame, i * .1)["crossed"])
    assert results == [1]


def test_do4_uses_speed_channel_and_rejects_duplicate_pins():
    from station.bench import BorrowedGPIO
    io = IO()
    adapter = BorrowedGPIO(io)
    adapter.set_output("speed", True)
    assert io.high and not io.led and not io.on
    adapter.stop()
    assert not io.high
    with pytest.raises(ValueError):
        StationConfig(speed_line=51)


@pytest.mark.parametrize("interruption", ["stop", "camera", "extra_di2"])
def test_slow_photo_save_does_not_block_monitor_or_count_after_stop(controller, recipe, monkeypatch, interruption):
    import threading
    from station import evidence
    gate, started = threading.Event(), threading.Event()
    original = evidence.save_frame
    def delayed(*args):
        started.set()
        gate.wait(2)
        return original(*args)
    monkeypatch.setattr(evidence, "save_frame", delayed)
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, capture_delay_ms=0)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        io.raw[1] = 0
        await cycle.tick()
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
            if started.is_set(): break
        assert started.is_set() and cycle.worker_busy() and c.session["count"] == 0
        # The monitor can keep renewing the I/O lease while image encoding runs.
        for _ in range(5):
            await asyncio.wait_for(cycle.tick(), .1)
        if interruption == "stop":
            c.command(command(c, "stop"), "test")
        elif interruption == "extra_di2":
            io.raw[1] = 1
            await cycle.tick()
            io.raw[1] = 0
            await cycle.tick()
            assert not io.on and c.session["fault"] == "QUANTITY_MISMATCH"
        else:
            camera.connected = False
            await cycle.tick()
            assert not io.on and c.session["phase"] == "CAMERA_WAIT"
        gate.set()
        for _ in range(50):
            await asyncio.sleep(.002)
            await cycle.tick()
        if interruption in ("stop", "extra_di2"):
            assert not io.on and c.session["count"] == 0 and c.last_result["status"] == "ABORTED"
        else:
            assert not io.on and c.session["count"] == 1 and c.session["phase"] == "CAMERA_WAIT"
            clock[0] += 2.1
            for _ in range(50):
                await asyncio.sleep(.002)
                await cycle.tick()
            assert io.on and c.session["count"] == 1
    try:
        asyncio.run(run())
    finally:
        gate.set()


def test_low_speed_deadline_survives_early_product_completion(controller, monkeypatch):
    c, io, _, cycle, clock = rig(controller, monkeypatch, low_speed_ms=500)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        clock[0] += .1
        io.raw[1] = 0
        await cycle.tick()
        assert c.session["count"] == 1 and cycle.pending is None and not io.high
        clock[0] += .41
        await cycle.tick()
        assert io.high and io.on
    asyncio.run(run())


def test_new_product_coasting_into_di1_during_camera_wait_is_preserved(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, reconnect_interval_ms=500,
                                     capture_delay_ms=100, low_speed_ms=200)
    async def run():
        await cycle.tick()
        camera.connected = False
        await cycle.tick()
        clock[0] += .3
        io.raw[0] = 0
        await cycle.tick()
        product = c.session["active_product"]
        assert product and c.session["phase"] == "CAMERA_WAIT" and not io.on
        clock[0] += .21
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert io.on and c.session["active_product"] == product
        assert cycle.pending["start"] == pytest.approx(clock[0])
        clock[0] += .21
        await cycle.tick()
        assert io.high
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        io.raw[1] = 0
        for _ in range(30):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert c.session["count"] == 1
    asyncio.run(run())


def test_early_di1_during_camera_wait_faults_without_motor_restart(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, reconnect_interval_ms=100)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        camera.connected = False
        await cycle.tick()
        io.raw[0] = 1
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        assert c.session["phase"] == "HOLD"
        assert c.session["fault"] == "EARLY_DI1_UNRESOLVED"
        clock[0] += .2
        for _ in range(20):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert ("motor", True) not in io.log and c.session["count"] == 0
    asyncio.run(run())


def test_stop_while_cancelling_capture_cannot_be_replaced_by_camera_wait(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, reconnect_interval_ms=100)
    async def run():
        await cycle.tick()
        async def capture():
            try:
                await asyncio.Future()
            finally:
                c.command(command(c, "stop"), "test")
        cycle.camera_task = asyncio.create_task(capture())
        await asyncio.sleep(0)
        camera.connected = False
        await cycle.tick()
        assert c.session["phase"] == "PAUSED" and not io.on
        clock[0] += .2
        for _ in range(20):
            await asyncio.sleep(.002)
            await cycle.tick()
        assert not io.on and ("motor", True) not in io.log
    asyncio.run(run())


@pytest.mark.parametrize("order", [("reset", "discard"), ("discard", "reset")])
def test_recovery_actions_stay_available_in_either_order(controller, monkeypatch, order):
    c, io, _, cycle, _ = rig(controller, monkeypatch)
    fault = [None]
    snapshot = io.snapshot
    io.snapshot = lambda: {**snapshot(), "fault": fault[0]}
    io.reset = lambda: fault.__setitem__(0, None)
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        c.fault("IO_FAULT")
        await cycle.tick()
        fault[0] = "IO_FAULT"
        c.config.mode = "HARDWARE"
        from station.controller import Conflict
        with pytest.raises(Conflict, match="두 제품 센서"):
            c.command(command(c, "discard"), "test")
        io.raw = [1, 1, 1]
        for action in order:
            assert c.session["phase"] in ("PAUSED", "HOLD", "FAULT")
            c.command(command(c, action), "test")
        assert c.session["phase"] == "READY"
        assert c.session["active_product"] is None and fault[0] is None and not io.on
    asyncio.run(run())


def test_camera_retry_continues_when_connect_returns_without_live_frames(controller, recipe, monkeypatch):
    recipe.channels = ["ocr"]
    c, io, camera, cycle, clock = rig(controller, monkeypatch, recipe, reconnect_interval_ms=100)
    def connect():
        camera.retries += 1
        camera.connected = camera.retries >= 2
    camera.connect = connect
    async def run():
        await cycle.tick()
        camera.connected = False
        await cycle.tick()
        for _ in range(2):
            clock[0] += .11
            for _ in range(20):
                await asyncio.sleep(.002)
                await cycle.tick()
        assert camera.retries == 2 and io.on and c.session["phase"] == "FEEDING"
    asyncio.run(run())


def test_tracking_frame_read_does_not_block_io_monitor(controller, monkeypatch):
    import threading
    gate, reading = threading.Event(), threading.Event()
    recipe = Recipe(kind="vision", brand_id="__simple__", brand_revision=1, targets={}, channels=[],
                    flow=FlowSettings(counter="cvzone"))
    c, io, camera, cycle, _ = rig(controller, monkeypatch, recipe, counter="cvzone", capture_delay_ms=0)
    cycle.counter = SimpleNamespace(update=lambda *a: {"crossed": [], "boxes": []})
    def read_latest():
        reading.set()
        gate.wait(.5)
        return np.zeros((50, 50, 3), dtype=np.uint8), {"seq": 1, "host_received_ns": time.monotonic_ns()}
    camera.read_latest = read_latest
    async def run():
        await cycle.tick()
        io.raw[0] = 0
        started = time.monotonic()
        await cycle.tick()
        assert time.monotonic() - started < .1
        for _ in range(20):
            await asyncio.sleep(.002)
            if reading.is_set(): break
        assert reading.is_set()
        started = time.monotonic()
        await cycle.tick()
        assert time.monotonic() - started < .1
        c.command(command(c, "stop"), "test")
        assert not io.on
        gate.set()
        await cycle.close()
    try:
        asyncio.run(run())
    finally:
        gate.set()


def test_disconnected_optional_rfid_does_not_disable_gpio_at_startup(monkeypatch):
    import enum
    import sys
    from station.hardware import GpioIO
    class Direction(enum.Enum):
        INPUT = 1
        OUTPUT = 2
    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1
    class Request:
        def get_values(self, lines): return [Value.ACTIVE] * len(lines)
        def get_value(self, line): return Value.ACTIVE
        def set_values(self, values): pass
        def set_value(self, line, value): pass
        def release(self): pass
    fake = SimpleNamespace(LineSettings=lambda **kw: kw, request_lines=lambda *a, **kw: Request())
    monkeypatch.setitem(sys.modules, "gpiod", fake)
    monkeypatch.setitem(sys.modules, "gpiod.line", SimpleNamespace(Direction=Direction, Value=Value))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    def missing(port): raise OSError("reader unplugged")
    monkeypatch.setattr("station.hardware.Reader", missing)
    io = GpioIO(StationConfig(do_on_raw=1, permit_line=107, permit_active_raw=1, speed_line=108,
                             rfid_port="/missing/reader", commissioning={"feedback_timeout_ms": 100}))
    try:
        snap = io.snapshot()
        assert snap["connected"] and not snap["rfid_ready"] and snap["rfid_error"] == "reader unplugged"
        assert 0 < snap["motor_restart_ms"] <= 5000
        assert len(io.blockers()) == 1 and "모터 정지 후 5초" in io.blockers()[0]
    finally:
        io.close()


def test_documented_board_opens_production_io_without_a_permit_input(monkeypatch):
    import enum
    import sys
    from station.hardware import GpioIO
    class Direction(enum.Enum):
        INPUT = 1
        OUTPUT = 2
    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1
    requested, written = {}, []
    class Request:
        def get_values(self, lines): return [Value.ACTIVE] * len(lines)
        def get_value(self, line): pytest.fail("the board has no permit input")
        def set_values(self, values): written.append(values)
        def set_value(self, line, value): pass
        def release(self): pass
    def request_lines(chip, consumer, config):
        requested.update(config)
        return Request()
    fake = SimpleNamespace(LineSettings=lambda **kw: kw, request_lines=request_lines)
    monkeypatch.setitem(sys.modules, "gpiod", fake)
    monkeypatch.setitem(sys.modules, "gpiod.line", SimpleNamespace(Direction=Direction, Value=Value))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    io = GpioIO(StationConfig(mode="HARDWARE"))
    try:
        assert sorted(requested) == [50, 51, 52, 105, 106, 144]
        assert requested[51]["output_value"] == Value.INACTIVE
        snap = io.snapshot()
        assert snap["connected"] and snap["physical_permit"] and io.feedback_ms == 3000
        io.motor_ready_at = 0
        io.motor(True)
        assert written[-1][51] == Value.ACTIVE
    finally:
        io.close()


def test_undocumented_wiring_still_needs_its_polarity_and_permit(monkeypatch):
    from station.hardware import GpioIO
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="출력 극성"):
        GpioIO(StationConfig(mode="HARDWARE", do_lines=(53, 54)))


def test_counter_can_return_to_previous_settings_after_failed_prepare(controller, monkeypatch):
    from station.schema import WorkPreset
    cycle = FlowCycle(controller, None, None, Vision())
    def create(cfg):
        if cfg.threshold == 128:
            raise ValueError("모델 설정 오류")
        return SimpleNamespace(identity={"counter": cfg.counter})
    monkeypatch.setattr("station.flow.ObjectCounter", create)
    good = WorkPreset(id="vision", name="와펜", kind="vision", flow={"counter": "cvzone"}).model_dump()
    cycle.prepare(good)
    bad = {**good, "flow": {**good["flow"], "threshold": 128}}
    with pytest.raises(ValueError): cycle.prepare(bad)
    cycle.prepare(good)
    assert cycle.counter is not None and cycle.counter_error is None
