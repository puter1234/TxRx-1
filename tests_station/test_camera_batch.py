import json
import zipfile
import numpy as np
import pytest
from station.camera_batch import capture_batch


class Camera:
    seq = 0
    def read_latest(self):
        return np.full((12, 16, 3), self.seq, dtype=np.uint8), {"seq": self.seq, "host_received_ns": self.seq * 1000}
    def status(self):
        self.seq += 2
        return {"connected": True, "frames": self.seq, "profile": {"fps": 60}}


def test_batch_saves_exact_count_and_reports_skipped_frames(tmp_path):
    path = tmp_path / "photos.zip"
    progress = []
    result = capture_batch(Camera(), path, 3, lambda: False, lambda: None, progress.append)
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["00001.png", "00002.png", "00003.png", "capture.json"]
        manifest = json.loads(archive.read("capture.json"))
        assert [frame["seq"] for frame in manifest["frames"]] == [2, 4, 6]
    assert result["count"] == 3
    assert result["skipped_frames"] == 3
    assert progress == [1, 2, 3]


def test_cancel_does_not_leave_partial_archive(tmp_path):
    path = tmp_path / "cancel.zip"
    with pytest.raises(ValueError, match="중지"):
        capture_batch(Camera(), path, 3, lambda: True, lambda: None, lambda n: None)
    assert not path.exists()


def test_disk_failure_does_not_leave_partial_archive(tmp_path):
    path = tmp_path / "disk.zip"
    def disk(): raise ValueError("disk full")
    with pytest.raises(ValueError, match="disk"):
        capture_batch(Camera(), path, 3, lambda: False, disk, lambda n: None)
    assert not path.exists()


def test_interval_uses_fresh_frames_and_records_actual_times(tmp_path, monkeypatch):
    from station import camera_batch
    import cv2

    class Clock:
        now = 1.0
        def monotonic(self): return self.now
        def sleep(self, seconds): self.now += seconds

    clock = Clock()
    monkeypatch.setattr(camera_batch.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(camera_batch.time, "sleep", clock.sleep)

    class TimedCamera:
        def read_latest(self):
            # Hardware runs at 100 FPS, independently of requested save intervals.
            seq = int(clock.now * 100)
            return np.full((12, 16, 3), seq % 256, dtype=np.uint8), {
                "seq": seq, "host_received_ns": seq * 10_000_000,
                "camera_settings_revision": 3,
            }
        def status(self):
            return {"connected": True, "frames": int(clock.now * 100)}

    path = tmp_path / "interval.zip"
    result = capture_batch(TimedCamera(), path, 3, lambda: False, lambda: None, lambda n: None, interval_ms=100)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("capture.json"))
        frames = manifest["frames"]
        assert all(b["host_received_ns"] - a["host_received_ns"] >= 100_000_000 for a, b in zip(frames, frames[1:]))
        for frame in frames:
            image = cv2.imdecode(np.frombuffer(archive.read(frame["file"]), np.uint8), cv2.IMREAD_COLOR)
            assert np.all(image == frame["seq"] % 256)
            assert frame["camera_settings_revision"] == 3
    assert result["interval_ms"] == 100 and result["count"] == 3


def test_interval_wait_can_be_cancelled_without_leaving_partial_files(tmp_path, monkeypatch):
    from station import camera_batch
    clock = [1.0]
    monkeypatch.setattr(camera_batch.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(camera_batch.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    class TimedCamera(Camera):
        def read_latest(self):
            image, meta = super().read_latest()
            meta["host_received_ns"] = int(clock[0] * 1e9)
            return image, meta

    path = tmp_path / "cancel-interval.zip"
    with pytest.raises(ValueError, match="중지"):
        capture_batch(TimedCamera(), path, 3, lambda: clock[0] >= 1.2,
                      lambda: None, lambda n: None, interval_ms=10000)
    assert clock[0] < 1.22
    assert not path.exists()
