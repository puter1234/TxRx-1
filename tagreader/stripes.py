"""Locate 1D stripe patterns without decoding their contents.

Only bounded detection images are normalized. OCR samples the original image.
"""
import time

import cv2
import numpy as np

WORK_EDGES = (960, 1600)
MAX_CANDIDATES = 4


def normalize_local(green):
    values = green.astype(np.float32)
    mean = cv2.boxFilter(values, -1, (31, 31))
    variance = cv2.boxFilter(values * values, -1, (31, 31)) - mean * mean
    deviation = np.sqrt(np.maximum(variance, 64.0))
    return np.clip(128 + 40 * (values - mean) / deviation, 0, 255).astype(np.uint8)


def _ordered_box(rect):
    points = cv2.boxPoints(rect)
    if np.linalg.norm(points[1] - points[0]) < np.linalg.norm(points[2] - points[1]):
        points = np.roll(points, -1, axis=0)
    return points


def _stripe_score(gray, quad):
    width = max(2, round(float(np.linalg.norm(quad[1] - quad[0]))))
    height = max(2, round(float(np.linalg.norm(quad[2] - quad[1]))))
    transform = cv2.getPerspectiveTransform(quad.astype(np.float32), np.float32(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]))
    patch = cv2.warpPerspective(gray, transform, (width, height), borderValue=128)
    profile = patch[height // 5:max(height // 5 + 1, height * 4 // 5)].mean(axis=0)
    low, high = np.percentile(profile, [10, 90])
    if high - low < 22:
        return None
    dark = profile < (low + high) / 2
    changes = np.flatnonzero(dark[1:] != dark[:-1]) + 1
    if len(changes) < 14:
        return None
    runs = np.diff(changes)
    # Regular clothing stripes alone do not establish a barcode candidate.
    if len(runs) < 10 or np.std(runs) / max(1, np.mean(runs)) < .16:
        return None
    for alternating in (runs[::2], runs[1::2]):
        narrow, wide = np.percentile(alternating, [10, 90])
        if wide < max(1, narrow) * 1.45:
            return None
    row_low, row_high = np.percentile(patch, [10, 90], axis=1)
    agreement = np.mean((patch < ((row_low + row_high) / 2)[:, None]) == dark[None, :], axis=1)
    good = (agreement > .8) & (row_high - row_low > 22)
    edges = np.diff(np.r_[False, good, False].astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    if not len(starts):
        return None
    longest = np.argmax(ends - starts)
    top, bottom = int(starts[longest]), int(ends[longest])
    if bottom - top < max(10, height * .4):
        return None
    # Exclude adjoining text and quiet margins before defining the OCR bands.
    profile = patch[top:bottom].mean(axis=0)
    low, high = np.percentile(profile, [10, 90])
    ink = np.flatnonzero(profile < (low + high) / 2)
    if not len(ink):
        return None
    left, right = int(ink[0]), int(ink[-1]) + 1
    tight = np.float32([[[left, top], [right, top], [right, bottom], [left, bottom]]])
    tight = cv2.perspectiveTransform(tight, np.linalg.inv(transform))[0]
    score = float(agreement[top:bottom].mean() * min(1, len(changes) / 40) * min(1, (high - low) / 70))
    return score, tight


def _candidates(gray):
    dx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    xx = cv2.boxFilter(dx * dx, -1, (9, 9))
    yy = cv2.boxFilter(dy * dy, -1, (9, 9))
    xy = cv2.boxFilter(dx * dy, -1, (9, 9))
    energy = xx + yy
    coherence = np.sqrt((xx - yy) ** 2 + 4 * xy * xy) / (energy + 1)
    mask = ((coherence > .65) & (energy > 400)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    # Bound detailed verification even in highly textured scenes.
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:32]:
        rect = cv2.minAreaRect(contour)
        short, long = sorted(rect[1])
        if short < 12 or long < 45 or not 1.4 <= long / short <= 20:
            continue
        if cv2.contourArea(contour) < short * long * .35:
            continue
        quad = _ordered_box(rect)
        verified = _stripe_score(gray, quad)
        if verified is not None:
            candidates.append(verified)
    return sorted(candidates, key=lambda item: item[0], reverse=True)[:MAX_CANDIDATES]


def _refine(green, quad):
    height, width = green.shape
    lower = np.floor(quad.min(axis=0) - 12).astype(int)
    upper = np.ceil(quad.max(axis=0) + 12).astype(int)
    x0, y0 = max(0, lower[0]), max(0, lower[1])
    x1, y1 = min(width, upper[0]), min(height, upper[1])
    region = green[y0:y1, x0:x1]
    if not region.size:
        return quad
    scale = min(1., 1280 / max(region.shape))
    if scale < 1:
        region = cv2.resize(region, (round(region.shape[1] * scale), round(region.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    sx, sy = region.shape[1] / (x1 - x0), region.shape[0] / (y1 - y0)
    matches = _candidates(normalize_local(region))
    if not matches:
        return quad
    center = quad.mean(axis=0)
    mapped = [q / [sx, sy] + [x0, y0] for _, q in matches]
    best = min(mapped, key=lambda q: np.linalg.norm(q.mean(axis=0) - center))
    # Refinement must stay on the same label, not jump to nearby texture.
    if np.linalg.norm(best.mean(axis=0) - center) > np.linalg.norm(quad[2] - quad[0]) * .2:
        return quad
    return best


def candidate_tiers(image, *, diagnostics=None):
    channel_started = time.perf_counter()
    green = cv2.extractChannel(image, 1) if image.ndim == 3 else image
    channel_ms = (time.perf_counter() - channel_started) * 1000
    height, width = green.shape
    for edge in WORK_EDGES:
        started = time.perf_counter()
        scale = min(1., edge / max(height, width))
        small = cv2.resize(green, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else green
        normalized = normalize_local(small)
        prepared_ms = (time.perf_counter() - started) * 1000 + channel_ms
        candidates = _candidates(normalized)
        sx, sy = small.shape[1] / width, small.shape[0] / height
        refine_started = time.perf_counter()
        quads = [_refine(green, quad / [sx, sy]) for _, quad in candidates]
        if diagnostics is not None:
            diagnostics.append({"stage": "stripes", "candidates": len(quads),
                "detect_ms": (time.perf_counter() - started) * 1000 + channel_ms,
                "preprocess_ms": prepared_ms, "refine_ms": (time.perf_counter() - refine_started) * 1000,
                "working_width": small.shape[1], "working_height": small.shape[0],
                "decode_ms": 0., "attempted": 0, "decoded": 0})
        yield "stripes", quads
        if quads or scale == 1:
            return
        channel_ms = 0.
