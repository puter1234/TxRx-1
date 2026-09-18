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
