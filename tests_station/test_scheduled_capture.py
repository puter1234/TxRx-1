"""Moving capture timing, frame identity, and cancellation without USB hardware."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from station import usb_camera


def timed_camera(monkeypatch, frames, on_wait=None):
    clock, index, reads = [0.0], [0], []
    image = np.full((24, 36, 3), 17, np.uint8)

    def wait(seconds):
        clock[0] += seconds
        index[0] = min(index[0] + 1, len(frames) - 1)
        if on_wait:
            on_wait()

    def read():
        seq, received = frames[index[0]]
        reads.append(seq)
        return image, {"seq": seq, "host_received_ns": received}

    monkeypatch.setattr(usb_camera, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=wait))
    camera = SimpleNamespace(status=lambda: {"connected": True, "frames": frames[index[0]][0]},
                             read_latest=read)
    return camera, image, reads, clock


def test_due_frame_is_returned_without_waiting_or_resampling(monkeypatch):
    camera, image, reads, clock = timed_camera(monkeypatch, [(10, 200)])
    captured, metadata = usb_camera.frame_at(camera, 200, 1)
    assert captured is image and metadata["seq"] == 10
    assert reads == [10] and clock[0] == 0


def test_capture_rejects_pre_due_and_reused_frames(monkeypatch):
    camera, _, reads, clock = timed_camera(monkeypatch, [(10, 100), (11, 200), (11, 200), (12, 300)])
    first = usb_camera.frame_at(camera, 200, 1)[1]
    second = usb_camera.frame_at(camera, 200, 1, previous_seq=first["seq"])[1]
    assert [first["seq"], second["seq"]] == [11, 12]
    assert reads == [10, 11, 12] and clock[0] == pytest.approx(.006)


def test_stale_frame_times_out_without_recopying(monkeypatch):
    camera, _, reads, _ = timed_camera(monkeypatch, [(10, 100)])
    with pytest.raises(TimeoutError):
        usb_camera.frame_at(camera, 200, .006)
    assert reads == [10]


def test_stop_interrupts_frame_wait(monkeypatch):
    cancel = threading.Event()
    camera, _, reads, clock = timed_camera(monkeypatch, [(10, 100)], cancel.set)
    with pytest.raises(RuntimeError, match="취소"):
        usb_camera.frame_at(camera, 200, 5, cancelled=cancel)
    assert reads == [10] and clock[0] == .002


def test_disconnect_interrupts_frame_wait(monkeypatch):
    camera, _, reads, _ = timed_camera(monkeypatch, [(10, 100)])
    camera.status = lambda: {"connected": False}
    with pytest.raises(RuntimeError, match="연결"):
        usb_camera.frame_at(camera, 200, 5)
    assert reads == []
