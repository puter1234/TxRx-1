"""Sensor state and RAM queue checks. No camera, GPIO, or OCR model is used."""
import threading
import time
from types import SimpleNamespace

import numpy as np

from station.sensor_ocr import SensorOcrSettings, SensorOcrTest


class Camera:
    def __init__(self):
        self.seq = 100
        self.received = time.monotonic_ns()
        self.lock = threading.Lock()

    def status(self):
        with self.lock:
            return {"connected": True, "width": 40, "height": 20, "frames": self.seq,
                    "profile": {"fps": 10}}

    def read_latest(self):
        with self.lock:
            return np.zeros((20, 40, 3), np.uint8), {"seq": self.seq, "host_received_ns": self.received}

    def publish(self):
        with self.lock:
            self.seq += 1
            self.received = time.monotonic_ns()


class Bench:
    def __init__(self, raw=1):
        self.input_listeners, self.stop_listeners = [], []
        self.lock, self.cancel = threading.RLock(), threading.Event()
        self.io = SimpleNamespace(snapshot=lambda: {"di_raw": [raw, 1, 0]})
        self.runs = {"motor": {}, "led": {}}

    def stop(self, reason):
        self.cancel.set()
        for listener in self.stop_listeners:
            listener(reason)


def until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("worker did not complete")
        time.sleep(0.002)


def test_capture_and_release_count_continue_while_ocr_waits():
    bench, camera = Bench(), Camera()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def read(image, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(2)
        return {"reads": [{"lines": [{"text": "AB12"}]}]}

    trial = SensorOcrTest(bench, camera, SimpleNamespace(test_auto=read))
    try:
        trial.start(SensorOcrSettings(frame_count=3, pattern="[A-Z]{2}[0-9]{2}"))
        trial.edge(1, 0, time.monotonic_ns())
        trial.edge(1, 0, time.monotonic_ns())
        for count in (1, 2, 3):
            camera.publish()
            until(lambda: len(trial.status()["jobs"][0]["frames"]) == count)
        assert entered.is_set()
        trial.edge(1, 1, time.monotonic_ns())
        trial.edge(1, 1, time.monotonic_ns())
        assert trial.status()["count"] == trial.status()["detected"] == 1
        assert [f["seq"] for f in trial.status()["jobs"][0]["frames"]] == [101, 102, 103]
        release.set()
        until(lambda: trial.status()["passed"] == 1)
        assert len(calls) == 1
        assert [f["state"] for f in trial.status()["jobs"][0]["frames"]] == ["passed", "skipped", "skipped"]
    finally:
        release.set()
        trial.close()


def test_failed_frame_advances_and_ends_after_n_distinct_frames():
    bench, camera = Bench(), Camera()
    calls = []

    def read(image, **kwargs):
        calls.append(True)
        return {"reads": [{"lines": [{"text": "wrong"}]}]}

    trial = SensorOcrTest(bench, camera, SimpleNamespace(test_auto=read))
    try:
        trial.start(SensorOcrSettings(frame_count=2, pattern="[0-9]{4}"))
        trial.edge(1, 0, time.monotonic_ns())
        for count in (1, 2):
            camera.publish()
            until(lambda: len(calls) == count)
        until(lambda: trial.status()["failed"] == 1)
        assert trial.status()["active"]
        assert len(trial.status()["jobs"][0]["frames"]) == 2
        trial.edge(1, 1, time.monotonic_ns())
        assert trial.status()["count"] == 1
    finally:
        trial.close()


def test_starting_with_active_sensor_waits_for_clear_without_counting():
    trial = SensorOcrTest(Bench(raw=0), Camera(), SimpleNamespace())
    try:
        trial.start(SensorOcrSettings())
        trial.edge(1, 0, time.monotonic_ns())
        trial.edge(1, 1, time.monotonic_ns())
        assert trial.status()["count"] == trial.status()["detected"] == 0
        trial.edge(1, 0, time.monotonic_ns())
        trial.edge(1, 1, time.monotonic_ns())
        assert trial.status()["count"] == trial.status()["detected"] == 1
    finally:
        trial.close()
