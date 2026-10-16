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


class Camera:
    def __init__(self, io): self.io, self.connected, self.retries = io, True, 0
    def status(self): return {"connected": self.connected, "frames": 20}
    def verify_fixed_controls(self): self.io.log.append("verify")
    def after(self, *args):
        self.io.log.append("capture")
        return np.zeros((50, 50, 3), dtype=np.uint8), {"seq": 10, "host_received_ns": time.monotonic_ns()}
    def connect(self): self.retries += 1; self.connected = True


class Vision:
    def status(self): return {"busy": False, "local_assets_present": True}
    def inspect_frame(self, frame, brand, recipe): return {"observations": {"ocr": recipe.targets}, "failures": []}


def rig(controller, monkeypatch, recipe=None, **settings):
    io = IO()
    c = Controller(controller.store, io, StationConfig())
    flow = FlowSettings(di1_debounce_ms=0, di2_debounce_ms=0, **settings)
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


@pytest.mark.parametrize("interruption", ["stop", "camera"])
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
        else:
            camera.connected = False
            await cycle.tick()
            assert not io.on and c.session["phase"] == "CAMERA_WAIT"
        gate.set()
        for _ in range(50):
            await asyncio.sleep(.002)
            await cycle.tick()
        if interruption == "stop":
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
