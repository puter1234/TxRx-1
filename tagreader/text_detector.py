"""PP-OCRv4 text boxes on a tag crop, with RapidOCR's own pre- and post-processing settings."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parent.parent / "vendor/text_detector/ch_PP-OCRv4_det_infer.onnx"
SHA256 = "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9"
LONG_SIDE = 736
THRESH, BOX_THRESH, UNCLIP = .3, .5, 1.6

_instance = None
_load_lock = threading.Lock()


class TextDetector:
    def __init__(self, path=MODEL):
        if not path.is_file():
            raise RuntimeError("글자 검출 모델 파일이 없습니다.")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError("글자 검출 모델 파일이 변경됐습니다.")
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        self.session = ort.InferenceSession(data, options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.lock = threading.Lock()

    def boxes(self, image):
        """Quadrilaterals (4x2, in image pixels) with their mean text probability."""
        height, width = image.shape[:2]
        scale = LONG_SIDE / max(height, width)
        rows = max(32, int(round(height * scale / 32)) * 32)
        cols = max(32, int(round(width * scale / 32)) * 32)
        resized = cv2.resize(image, (cols, rows), interpolation=cv2.INTER_AREA)
        if resized.ndim == 2:
            resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
        blob = ((resized.astype(np.float32) / 255 - .5) / .5).transpose(2, 0, 1)[None]
        with self.lock:
            prob = self.session.run(None, {self.input: blob})[0][0, 0]
        mask = cv2.dilate((prob > THRESH).astype(np.uint8), np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for contour in contours[:1000]:
            rect = cv2.minAreaRect(contour)
            if min(rect[1]) < 3:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            filled = np.zeros((h, w), np.uint8)
            cv2.fillPoly(filled, [contour - [x, y]], 1)
            score = float(prob[y:y + h, x:x + w][filled > 0].mean())
            if score < BOX_THRESH:
                continue
            (cx, cy), (w, h), angle = rect
            area, perimeter = w * h, 2 * (w + h)
            grow = area * UNCLIP / max(perimeter, 1)
            points = cv2.boxPoints(((cx, cy), (w + 2 * grow, h + 2 * grow), angle))
            points[:, 0] = np.clip(points[:, 0] * width / cols, 0, width - 1)
            points[:, 1] = np.clip(points[:, 1] * height / rows, 0, height - 1)
            found.append((points.astype(np.float64), score))
        return found


def get_detector():
    global _instance
    with _load_lock:
        if _instance is None:
            _instance = TextDetector()
        return _instance
