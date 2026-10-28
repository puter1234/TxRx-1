"""Restore a connected bench camera after capture loss; never restart outputs."""
import logging
import threading
import time


class CameraRecovery:
    def __init__(self, camera, interval=2.0):
        self.camera, self.interval = camera, interval
        self.closed = threading.Event()
        self.lost_stream = None
        self.next_attempt = 0.
        self.thread = threading.Thread(target=self._run, daemon=True, name="bench-camera-recovery")

    def start(self):
        self.thread.start()

    def tick(self, now):
        stream = self.camera.stream
        if stream is None or self.camera.status().get("connected"):
            self.lost_stream = None
            return
        if stream is not self.lost_stream:
            self.lost_stream = stream
            self.next_attempt = now + self.interval
            return
        if now < self.next_attempt or self.closed.is_set():
            return
        try:
            self.camera.recover(stream)
        finally:
            self.next_attempt = time.monotonic() + self.interval

    def _run(self):
        while not self.closed.wait(0.2):
            try:
                self.tick(time.monotonic())
            except Exception as exc:
                logging.getLogger(__name__).warning("CAMERA_RECOVERY_FAILED: %s", exc)

    def close(self):
        self.closed.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1)
