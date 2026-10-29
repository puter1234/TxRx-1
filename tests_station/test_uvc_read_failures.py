"""Dropped frames must not release capture; a sustained loss still terminates it."""
import queue
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from station import usb_camera


@pytest.mark.parametrize('persistent', [False, True])
@pytest.mark.parametrize('decode_error', [False, True])
def test_uvc_read_failure_recovery_and_deadline(monkeypatch, persistent, decode_error):
    pixels = bytearray(4 * 3 * 3)
    mem = SimpleNamespace(buf=pixels, close=lambda: None)
    monkeypatch.setattr(usb_camera.shared_memory, 'SharedMemory', lambda **kw: mem)
    frame = np.full((3, 4, 3), 42, np.uint8)
    ticks = iter([0.0, 0.1, 2.1] if persistent else [0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(usb_camera.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(usb_camera.time, 'sleep', lambda _: None)
    calls = []
    class Capture:
        closed = False
        def isOpened(self): return True
        def set(self, *args): pass
        def release(self): self.closed = True
        def read(self):
            calls.append(True)
            if len(calls) == 1: return True, frame
            if len(calls) == 2 or persistent:
                if decode_error:
                    raise cv2.error('bad camera frame')
                return False, None
            if len(calls) == 3: return True, frame
            raise RuntimeError('test finished')
    cap = Capture()
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *args: cap)
    metadata, errors = [0, 0, 0], queue.Queue()
    usb_camera._capture_process({'device':'test','width':4,'height':3,'fps':30,'pixel_format':'YUYV'},
                                'test', metadata, threading.Lock(), errors)
    assert metadata[2] == 1
    assert cap.closed
    if persistent:
        assert metadata[0] == 1
        assert '새 영상 없음' in errors.get_nowait()
    else:
        assert metadata[0] == 2
        assert errors.get_nowait() == 'test finished'
        np.testing.assert_array_equal(np.ndarray((3,4,3),np.uint8,buffer=pixels),frame)


def test_preview_buffer_preserves_original_and_sequence():
    frame = np.zeros((1200, 1600, 3), np.uint8)
    frame[:, ::2] = (17, 83, 241)
    shape = usb_camera.preview_shape(1600, 1200)
    pixels = bytearray(frame.nbytes + np.prod(shape))
    metadata = [0, 0, 0, 0, 0]
    usb_camera.publish_frame(frame, pixels, metadata, threading.Lock(), 123456)
    original = np.ndarray(frame.shape, np.uint8, buffer=pixels)
    preview = np.ndarray(shape, np.uint8, buffer=pixels, offset=frame.nbytes)
    np.testing.assert_array_equal(original, frame)
    np.testing.assert_array_equal(preview, cv2.resize(frame, (1280, 960)))
    assert metadata[:2] == [1, 123456]
