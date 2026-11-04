"""Every text line on a tag, found by PP-OCRv4 in the full-resolution tag crop.

Each line box is turned along its own long side, so neither the tag nor the
barcode decides the reading direction. Lines that are not long enough to be a
product code are dropped, and the rest come longest first, the order OCR reads them.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

WHOLE_MIN_SIDE = 736  # RapidOCR's whole-page setting: small tags are enlarged to this, large ones kept
MIN_LINE_RATIO = 4    # product-code lines are at least this many times longer than high (widened crop)


def reading_quad(points):
    """The box from the start of its long side: p0->p1 runs along the line, p0->p3 across it.

    Lines read left to right, or bottom to top when they stand upright; the
    opposite direction is the 180 degree reading.
    """
    p = np.asarray(points, np.float64).reshape(4, 2)
    if np.linalg.norm(p[1] - p[0]) < np.linalg.norm(p[2] - p[1]):
        p = np.roll(p, -1, axis=0)
    dx, dy = p[1] - p[0]
    if not -135 < math.degrees(math.atan2(dy, dx)) <= 45:
        p = p[[2, 3, 0, 1]]
    return p


def tag_angle(gray):
    """The tag's dominant edge direction, modulo 90 degrees, from gradient orientation."""
    small_scale = 600 / max(gray.shape[:2])
    small = cv2.resize(gray, None, fx=small_scale, fy=small_scale, interpolation=cv2.INTER_AREA).astype(np.float32)
    gx, gy = cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1)
    z = ((gx * gx + gy * gy) * np.exp(4j * np.arctan2(gy, gx))).sum()
    return math.degrees(np.angle(z) / 4)


def upright_boxes(tag):
    """Text lines of a tag squared up first: a tilted tag merges or breaks lines in the detector.

    Boxes come back in the tag's own coordinates.
    """
    from .text_detector import get_detector
    gray = tag if tag.ndim == 2 else tag[:, :, 1]
    h, w = tag.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), tag_angle(gray), 1)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    size = (int(h * sin + w * cos), int(h * cos + w * sin))
    m[0, 2] += size[0] / 2 - w / 2
    m[1, 2] += size[1] / 2 - h / 2
    turned = cv2.warpAffine(tag, m, size, borderValue=255)
    back = cv2.invertAffineTransform(m)
    return [(np.asarray(p, np.float64) @ back[:, :2].T + back[:, 2], score)
            for p, score in get_detector().boxes(turned, min_side=WHOLE_MIN_SIDE)]


def find_tag_lines(original, roi_12mp):
    """The tag cut from the 48MP frame and preprocessed for OCR, with its lines in reading order."""
    from .model_pipeline import widen
    from .preprocess import prepare_ocr_source
    from .text_detector import get_detector
    started = time.perf_counter()
    x1, y1, x2, y2 = (int(v) * 2 for v in roi_12mp)
    x1, y1 = max(0, x1), max(0, y1)
    tag = prepare_ocr_source(original[y1:y2, x1:x2])
    preprocess_ms = (time.perf_counter() - started) * 1000
    t0 = time.perf_counter()
    boxes = upright_boxes(tag)
    detect_ms = (time.perf_counter() - t0) * 1000
    regions = []
    for points, score in boxes:
        quad = reading_quad(points) + [x1, y1]
        wide = np.asarray(widen(quad))
        ratio = np.linalg.norm(wide[1] - wide[0]) / max(np.linalg.norm(wide[3] - wide[0]), 1e-6)
        if ratio >= MIN_LINE_RATIO:
            regions.append({"barcode_index": 0, "side_in_aligned_image": "whole", "quad_target": quad.tolist(),
                            "ratio": float(ratio), "detector_score": float(score), "finder": "whole"})
    regions.sort(key=lambda region: -region["ratio"])
    return {"regions": regions, "region_count": len(regions), "tag": tag, "origin": (x1, y1),
            "elapsed_ms": (time.perf_counter() - started) * 1000, "detect_ms": detect_ms,
            "preprocess_ms": preprocess_ms}
