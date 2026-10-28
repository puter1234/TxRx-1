"""UVC capture loop with a scripted cv2.VideoCapture. No camera is used."""
import queue
import threading
from types import SimpleNamespace

import cv2
import numpy as np

from station import usb_camera

SETTINGS = {"device": "/dev/video0", "width": 4, "height": 2, "fps": 30.0, "pixel_format": "YUYV"}
FRAME = np.zeros((2, 4, 3), np.uint8)


class ScriptDone(BaseException):
    pass


def run_capture(monkeypatch, reads, clock=None):
    class Capture:
        def __init__(self, *args): pass
        def isOpened(self): return True
        def set(self, *args): return True
        def release(self): pass

        def read(self):
            if not reads:
                raise ScriptDone("script finished")
            return reads.pop(0)

    class Memory:
        def __init__(self, name): self.buf = bytearray(FRAME.nbytes)
        def close(self): pass

    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    monkeypatch.setattr(usb_camera.shared_memory, "SharedMemory", Memory)
    if clock is not None:
        monkeypatch.setattr(usb_camera, "time", clock)
    metadata, errors = [0, 0, 0], queue.Queue(maxsize=1)
    usb_camera._capture_process(SETTINGS, "test", metadata, threading.Lock(), errors)
    return metadata, errors.get_nowait()


def test_single_failed_reads_do_not_end_the_stream(monkeypatch):
    reads = [(True, FRAME), (False, None), (False, None), (True, FRAME)]
    metadata, error = run_capture(monkeypatch, reads)
    assert error == "script finished"
    assert metadata[0] == 2
    assert metadata[2] == 2


def test_stream_ends_after_stale_interval_without_frames(monkeypatch):
    now = [0]

    def sleep(seconds):
        now[0] += int(seconds * 1e9)

    clock = SimpleNamespace(monotonic_ns=lambda: now[0], sleep=sleep)
    metadata, error = run_capture(monkeypatch, [(False, None)] * 1000, clock)
    assert "카메라 영상이 끊겼습니다" in error
    assert metadata[0] == 0
    assert 1 < metadata[2] < 1000
