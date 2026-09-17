"""Lossless evidence writers. Call in worker threads to keep control/heartbeat responsive."""

import hashlib
import io


def save_upload(root, ident, data):
    from PIL import Image
    from ocr.core import to_rgb

    target = root / "evidence" / f"{ident}.png"
    target.parent.mkdir(exist_ok=True)
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > 24_000_000:
            raise ValueError("이미지는 2,400만 화소 이하여야 합니다.")
        original.load()
        # Preserve the established EXIF + white-alpha preprocessing exactly.
        to_rgb(original).save(target, format="PNG")
    target.with_suffix(".original").write_bytes(data)
    return target, {
        "url": f"/api/evidence/{ident}",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "source": "UPLOADED_PHOTO",
    }


def save_frame(root, ident, frame, timing, product):
    import cv2

    target = root / "evidence" / f"{ident}.png"
    target.parent.mkdir(exist_ok=True)
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise IOError("EVIDENCE_WRITE_FAILED")
    data = encoded.tobytes()
    target.write_bytes(data)
    return target, {
        "url": f"/api/evidence/{ident}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "CSI_CAMERA",
        "timing": timing,
        "product_detection": product,
    }
