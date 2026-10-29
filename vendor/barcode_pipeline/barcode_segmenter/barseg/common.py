import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def read_image(path):
    im = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise ValueError(f'Cannot decode {path}')
    return im

def save_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f'Cannot encode {path}')
    buf.tofile(path)

def prepare_roi(image, gain=3.5):
    """Fixed green gain; no spatial transform, identical in dataset and inference."""
    lut = np.clip(np.arange(256) * gain, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.LUT(image[:, :, 1], lut), cv2.COLOR_GRAY2BGR)

def polygon_iou(a, b):
    a = cv2.convexHull(np.asarray(a, np.float32))
    b = cv2.convexHull(np.asarray(b, np.float32))
    inter, _ = cv2.intersectConvexConvex(a, b)
    return float(inter / max(cv2.contourArea(a) + cv2.contourArea(b) - inter, 1e-9))
