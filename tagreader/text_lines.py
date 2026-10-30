"""Two alternatives to the vendored barcode-adjacent text finder, for comparison in the process test.

Both keep its contract: at most one line above and one below each barcode, with the
same region fields, so OCR reads no more crops than before. Coordinates follow
barseg.text_regions: rotate into the barcode direction, choose a line there, and map
the four corners back to the ROI, the 12MP frame and the 48MP frame.

lines    Fixes what cut lines short on real tags: the line may run past the barcode
         ends, word spaces do not split it, the ink threshold follows the label's own
         brightness, and a line must sit over the barcode rather than beside it.
detector Text boxes from PaddleOCR's PP-OCRv4 detector (text_detector.py), run on the
         same turned view with the bars blanked, kept when they lie above or below.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from vendor.barcode_pipeline.barcode_segmenter.barseg.infer import long_axis, map_points
from vendor.barcode_pipeline.barcode_segmenter.barseg.text_regions import _refine_angle

LINE_MARGIN = 0.6   # a line may run this far past each barcode end, in barcode widths
LINE_SEARCH = 2.0   # lines are looked for this far from the bars, in barcode heights
WORD_GAP = 3.0      # gaps up to this many glyph heights stay inside one line
INK_RATIO = 190     # ink is at least ~25% darker than the label around it


def normalized_green(raw):
    """The vendored finder's input: green channel stretched between its 1st and 99th percentiles."""
    gray = np.ascontiguousarray(raw[:, :, 1])
    low, high = np.percentile(gray, [1, 99])
    return np.clip((gray.astype(np.float32) - low) * 255 / max(high - low, 1), 0, 255).astype(np.uint8)


def barcode_mask(shape, instances):
    """Every barcode on the tag, so neither finder takes bars for a line of text."""
    mask = np.zeros(shape, np.uint8)
    for inst in instances:
        cv2.fillPoly(mask, [np.round(np.asarray(inst["polygon_roi"])).astype(np.int32)], 255)
    return mask


def aligned_view(gray, polygon, bars=None, margin_ratio=LINE_MARGIN, search_ratio=LINE_SEARCH):
    """The barcode's surroundings turned so the bars run left to right."""
    _, base = long_axis(polygon)
    if base is None:
        return None
    angle, coherence = _refine_angle(gray, polygon, base)
    theta = math.radians(angle)
    rotation = np.array([[math.cos(theta), math.sin(theta)], [-math.sin(theta), math.cos(theta)]])
    aligned = polygon @ rotation.T
    left, top = aligned.min(axis=0)
    right, bottom = aligned.max(axis=0)
    bw, bh = right - left, bottom - top
    if bw < 15 or bh < 5:
        return None
    margin_x = max(8, margin_ratio * bw)
    search = max(16, search_ratio * bh)
    origin = np.array([left - margin_x, top - search])
    matrix = np.column_stack((rotation, -origin))
    size = (int(math.ceil(bw + 2 * margin_x)), int(math.ceil(bh + 2 * search)))
    local = cv2.warpAffine(gray, matrix, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    valid = cv2.warpAffine(np.full(gray.shape, 255, np.uint8), matrix, size, flags=cv2.INTER_NEAREST)
    view = {"angle": angle, "coherence": coherence, "matrix": matrix, "inverse": cv2.invertAffineTransform(matrix),
            "size": size, "local": local, "valid": valid, "bw": bw, "bh": bh, "margin_x": margin_x,
            "top": top - origin[1], "bottom": bottom - origin[1]}
    view["top"], view["bottom"] = bar_rows(view)
    grow = max(3, int(.08 * bh)) | 1
    view["bars"] = (cv2.dilate(cv2.warpAffine(bars, matrix, size, flags=cv2.INTER_NEAREST), np.ones((grow, grow), np.uint8))
                    if bars is not None else np.zeros(local.shape, np.uint8))
    return view


def bar_rows(view):
    """Rows of the bars themselves, from the dense cross-bar gradient (as the vendored finder does)."""
    local, bw, bh, margin_x = view["local"], view["bw"], view["bh"], view["margin_x"]
    top, bottom = view["top"], view["bottom"]
    gx = np.abs(cv2.Sobel(local, cv2.CV_32F, 1, 0, ksize=3))
    xa, xb = int(margin_x + .1 * bw), int(margin_x + .9 * bw)
    energy = np.convolve(gx[:, xa:xb].mean(axis=1), np.ones(3) / 3, mode="same")
    ta, tb = max(0, int(top - .3 * bh)), min(view["size"][1], int(bottom + .3 * bh))
    if tb <= ta:
        return top, bottom
    peak = int(ta + np.argmax(energy[ta:tb]))
    threshold = energy[peak] * .58
    lo = hi = peak
    while lo > ta and energy[lo - 1] > threshold:
        lo -= 1
    while hi < tb - 1 and energy[hi + 1] > threshold:
        hi += 1
    return (float(lo), float(hi + 1)) if .4 * bh <= hi - lo + 1 <= 1.5 * bh else (top, bottom)


def region(view, box, side, index, roi_xyxy, source_size, target_size, extra):
    """One region in the vendored shape, from an axis-aligned box in the turned view."""
    x0, y0, x1, y1 = box
    corners = np.array([[x0, y0], [x1 - 1, y0], [x1 - 1, y1 - 1], [x0, y1 - 1]], np.float64)
    quad = corners @ view["inverse"][:, :2].T + view["inverse"][:, 2]
    item = {"barcode_index": index, "side_in_aligned_image": side, "angle_degrees_mod180": view["angle"] % 180,
            "angle_gradient_coherence": view["coherence"], "quad_roi": quad.tolist(), "crop_size": [x1 - x0, y1 - y0],
            "orientation_resolved": False, "candidate_rotations_degrees": [0, 180], "text": None,
            "status": "unrecognized_candidate", **extra}
    if roi_xyxy is not None:
        item["quad_source"] = map_points(quad, roi_xyxy, source_size).tolist()
        if target_size is not None:
            item["quad_target"] = map_points(quad, roi_xyxy, source_size, target_size).tolist()
    return item


def padded(view, box):
    x0, y0, x1, y1 = box
    height = y1 - y0
    px, py = max(3, int(math.ceil(height * .35))), max(3, int(math.ceil(height * .30)))
    width, rows = view["size"]
    return max(0, x0 - px), max(0, y0 - py), min(width, x1 + px), min(rows, y1 + py)


def over_barcode(view, x0, x1):
    """A product code line is printed over the bars, not beside them."""
    start, end = view["margin_x"], view["margin_x"] + view["bw"]
    return min(x1, end) - max(x0, start) >= .3 * min(x1 - x0, view["bw"])


def _ink(view):
    local, bh = view["local"], view["bh"]
    # Closing removes glyphs, leaving the label's own brightness; dividing by it keeps
    # faint glyphs in a dark photo as visible as bright ones.
    kernel = max(15, int(bh) | 1)
    background = cv2.morphologyEx(local, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    flat = cv2.divide(local, np.maximum(background, 1), scale=255)
    ink = (flat < INK_RATIO).astype(np.uint8) * 255
    width = view["size"][0]
    rows = slice(max(0, int(view["top"])), min(view["size"][1], int(view["bottom"])))
    ink[rows, max(0, int(view["margin_x"] - 3)):min(width, int(view["margin_x"] + view["bw"] + 3))] = 0
    ink[(view["valid"] == 0) | (view["bars"] > 0)] = 0
    return ink


def _lines(ink, bw, bh):
    """Glyph-sized pieces grouped into lines; a word space does not end a line."""
    _, _, stats, centres = cv2.connectedComponentsWithStats(ink, 8)
    glyphs = [(int(x), int(y), int(w), int(h), float(c[1])) for (x, y, w, h, area), c in zip(stats[1:], centres[1:])
              if area >= 3 and max(3, bh * .08) <= h <= bh and w <= bw * 1.2 and h / max(w, 1) < 12
              and area / max(w * h, 1) < .92]
    rows = []
    for g in sorted(glyphs, key=lambda g: g[4]):
        near = [row for row in rows if abs(np.median([a[4] for a in row]) - g[4]) < .55 * max(g[3], np.median([a[3] for a in row]))]
        if near:
            min(near, key=lambda row: abs(np.median([a[4] for a in row]) - g[4])).append(g)
        else:
            rows.append([g])
    boxes = []
    for row in rows:
        height = float(np.median([g[3] for g in row]))
        groups = [[]]
        for g in sorted(row):
            if groups[-1] and g[0] - (groups[-1][-1][0] + groups[-1][-1][2]) > WORD_GAP * height:
                groups.append([])
            groups[-1].append(g)
        for group in groups:
            x0, x1 = min(g[0] for g in group), max(g[0] + g[2] for g in group)
            y0, y1 = min(g[1] for g in group), max(g[1] + g[3] for g in group)
            thin = np.mean([g[3] > 5 * g[2] for g in group])
            if (len(group) >= 3 or any(g[2] > .25 * bw for g in group)) and x1 - x0 >= .25 * bw \
                    and (x1 - x0) / max(1, y1 - y0) >= 3 and thin < .6:
                boxes.append(((x0, y0, x1, y1), len(group)))
    return boxes


def find_lines(raw_crop, instances, roi_xyxy=None, source_size=None, target_size=None):
    """Option A: the vendored finder with the faults that cut product codes short fixed."""
    started = time.perf_counter()
    gray = normalized_green(raw_crop)
    bars = barcode_mask(gray.shape, instances)
    regions = []
    for index, inst in enumerate(instances):
        view = aligned_view(gray, np.asarray(inst["polygon_roi"], np.float64), bars)
        if view is None:
            continue
        ink = _ink(view)
        for side, y0, y1 in (("above", 0, max(0, int(view["top"]))),
                             ("below", min(view["size"][1], int(math.ceil(view["bottom"]))), view["size"][1])):
            if y1 - y0 < 3:
                continue
            found = []
            for (bx0, by0, bx1, by1), count in _lines(ink[y0:y1], view["bw"], view["bh"]):
                box = (bx0, by0 + y0, bx1, by1 + y0)
                patch = view["local"][box[1]:box[3], box[0]:box[2]]
                if (over_barcode(view, box[0], box[2]) and np.median(patch) > 60
                        and np.mean(view["valid"][box[1]:box[3], box[0]:box[2]] > 0) > .98):
                    found.append((box, count))
            if not found:
                continue
            distance = (lambda b: view["top"] - b[0][3]) if side == "above" else (lambda b: b[0][1] - view["bottom"])
            box, count = min(found, key=distance)
            regions.append(region(view, padded(view, box), side, index, roi_xyxy, source_size, target_size,
                                  {"glyph_component_count": count, "finder": "lines"}))
    return {"status": "experimental", "regions": regions, "region_count": len(regions),
            "elapsed_ms": (time.perf_counter() - started) * 1000}


def find_detected(raw_crop, instances, roi_xyxy=None, source_size=None, target_size=None):
    """Option B: PP-OCRv4 text boxes beside each barcode, read in the barcode direction."""
    from .text_detector import get_detector
    started = time.perf_counter()
    detector = get_detector()
    gray = normalized_green(raw_crop)
    bars = barcode_mask(gray.shape, instances)
    regions = []
    detect_ms = 0.
    for index, inst in enumerate(instances):
        view = aligned_view(gray, np.asarray(inst["polygon_roi"], np.float64), bars)
        if view is None:
            continue
        local = view["local"].copy()
        local[view["bars"] > 0] = 255
        t0 = time.perf_counter()
        boxes = detector.boxes(local)
        detect_ms += (time.perf_counter() - t0) * 1000
        sides = {"above": [], "below": []}
        for points, score in boxes:
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            height = y1 - y0
            if height < 3 or x1 - x0 < .25 * view["bw"] or x1 - x0 < 2 * height or not over_barcode(view, x0, x1):
                continue
            if (y0 + y1) / 2 < view["top"]:
                sides["above"].append([x0, y0, x1, y1, score])
            elif (y0 + y1) / 2 > view["bottom"]:
                sides["below"].append([x0, y0, x1, y1, score])
        for side, found in sides.items():
            if not found:
                continue
            # The detector can split one line at a wide space; pieces on one row are joined.
            found.sort(key=lambda b: b[0])
            rows = []
            for b in found:
                last = rows[-1] if rows else None
                height = b[3] - b[1]
                if (last and abs((last[1] + last[3]) / 2 - (b[1] + b[3]) / 2) < .5 * height
                        and b[0] - last[2] < WORD_GAP * height):
                    last[:4] = [min(last[0], b[0]), min(last[1], b[1]), max(last[2], b[2]), max(last[3], b[3])]
                    last[4] = max(last[4], b[4])
                else:
                    rows.append(list(b))
            near = min(rows, key=(lambda b: view["top"] - b[3]) if side == "above" else (lambda b: b[1] - view["bottom"]))
            box = tuple(int(round(v)) for v in near[:4])
            regions.append(region(view, box, side, index, roi_xyxy, source_size, target_size,
                                  {"detector_score": float(near[4]), "finder": "detector"}))
    return {"status": "experimental", "regions": regions, "region_count": len(regions),
            "elapsed_ms": (time.perf_counter() - started) * 1000, "detect_ms": detect_ms}


FINDERS = {"lines": find_lines, "detector": find_detected}
