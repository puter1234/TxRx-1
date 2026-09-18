"""Save a requested number of distinct full-resolution frames to one archive."""
import json
import time
import zipfile


def capture_batch(camera, path, count, cancelled, check_disk, progress):
    import cv2
    records = []
    started = time.monotonic()
    last = camera.read_latest()[1]["seq"]
    baseline = last
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            while len(records) < count:
                if cancelled():
                    raise ValueError("연속 촬영을 중지했습니다.")
                if time.monotonic() - started > 300:
                    raise ValueError("촬영 제한시간 5분을 초과했습니다. 촬영 장수를 줄여주세요.")
                status = camera.status()
                if not status.get("connected"):
                    raise ValueError("카메라 연결이 끊겼습니다.")
                if status.get("frames", 0) <= last:
                    time.sleep(0.002)
                    continue
                image, meta = camera.read_latest()
                if meta["seq"] <= last:
                    continue
                check_disk()
                ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                if not ok:
                    raise ValueError("사진 저장에 실패했습니다.")
                name = f"{len(records) + 1:05d}.png"
                archive.writestr(name, encoded.tobytes())
                last = meta["seq"]
                records.append({"file": name, **meta})
                progress(len(records))
            elapsed = time.monotonic() - started
            result = {"count": count, "elapsed_seconds": round(elapsed, 3),
                      "saved_fps": round(count / max(elapsed, 0.001), 2),
                      "skipped_frames": max(0, last - baseline - count),
                      "camera": camera.status().get("profile"), "frames": records}
            archive.writestr("capture.json", json.dumps(result, ensure_ascii=False, indent=2))
        return {key: value for key, value in result.items() if key != "frames"}
    except BaseException:
        path.unlink(missing_ok=True)
        raise
