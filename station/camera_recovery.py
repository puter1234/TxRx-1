"""Keep a wanted bench camera connected with its last settings; never restart outputs."""
import logging
import threading
import time


class CameraRecovery:
    def __init__(self, camera, interval=2.0, longest=10.0, paused=lambda: False):
        self.camera, self.interval, self.longest = camera, interval, longest
        # True while someone else (a running job) is reconnecting the camera.
        self.paused = paused
        self.closed = threading.Event()
        self.waiting = False
        self.failures = 0
        self.next_attempt = 0.
        self.thread = threading.Thread(target=self._run, daemon=True, name="bench-camera-recovery")

    def start(self):
        self.thread.start()

    def tick(self, now):
        camera = self.camera
        if not camera.wanted or self.paused() or camera.status().get("connected"):
            self.waiting, self.failures = False, 0
            return
        if not self.waiting:
            # Give a dropped USB device a moment to enumerate before the first try.
            self.waiting = True
            self.next_attempt = now + self.interval
            return
        if now < self.next_attempt or self.closed.is_set():
            return
        try:
            camera.ensure()
            self.failures = 0
        except Exception:
            # Keep trying for as long as the camera is wanted, a little slower each time.
            self.failures += 1
            raise
        finally:
            self.next_attempt = time.monotonic() + min(self.longest, self.interval * (1 + self.failures))

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
