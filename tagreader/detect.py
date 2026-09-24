"""바코드 위치 검출. 위치 전용 경로는 첫 검출에서 검색을 끝낸다."""
import cv2
import numpy as np
import time

from .geometry import dedupe_quads

# 첫 검출 단계의 작업 폭. 원본 해상도 검색은 다음 단계에서 수행한다.
WORK_WIDTH = 1800

# 타일 폴백 파라미터. tile > stride 여야 경계에 걸친 바코드를 놓치지 않는다.
TILE = 1000
TILE_STRIDE = 700

# 타일이 이보다 작으면 감지기가 의미 있는 결과를 못 낸다.
MIN_TILE_PX = 100


def _as_quads(points) -> list[np.ndarray]:
    if points is None or len(points) == 0:
        return []
    return [p.reshape(4, 2).astype(np.float64) for p in points]


def _detect_tiled(detector, gray: np.ndarray, *, first_only: bool = False) -> list[np.ndarray]:
    """타일 단위로 쪼개 감지한 뒤 좌표를 전체 이미지 기준으로 되돌린다.

    고해상도 + 배경 텍스처 노이즈 때문에 전체 감지가 실패할 때만 쓴다.
    축소본이 아니라 원본 해상도에 대고 돌려야 한다 (작은 바코드는 축소하면 사라진다).
    """
    quads = []
    h, w = gray.shape[:2]
    for y in range(0, h, TILE_STRIDE):
        for x in range(0, w, TILE_STRIDE):
            tile = gray[y:y + TILE, x:x + TILE]
            if min(tile.shape[:2]) < MIN_TILE_PX:
                continue
            ok, points = detector.detect(tile)
            if ok:
                quads.extend(q + [x, y] for q in _as_quads(points))
                if first_only and quads:
                    return quads
    return quads


def candidate_tiers(gray: np.ndarray, *, diagnostics: list | None = None, first_only: bool = False):
    """(단계 이름, quad 리스트)를 비용이 싼 순서대로 내놓는 제너레이터.

    first_only는 값 판독 없이 위치만 쓰는 경로다. 첫 후보가 나온 타일에서
    반환하며 이후 타일과 검출 단계는 실행하지 않는다.
    """
    detector = cv2.barcode.BarcodeDetector()
    h, w = gray.shape[:2]

    def record(stage, quads, started):
        if diagnostics is not None:
            diagnostics.append({"stage": stage, "candidates": len(quads),
                                "detect_ms": (time.perf_counter() - started) * 1000,
                                "decode_ms": 0.0, "attempted": 0, "decoded": 0})

    scale = WORK_WIDTH / w if w > WORK_WIDTH else 1.0
    if scale < 1.0:
        started = time.perf_counter()
        small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, points = detector.detect(small)
        quads = dedupe_quads([q / scale for q in _as_quads(points)]) if ok else []
        record("small", quads, started)
        if ok:
            yield "small", quads
            if first_only and quads:
                return

    started = time.perf_counter()
    ok, points = detector.detect(gray)
    quads = dedupe_quads(_as_quads(points)) if ok else []
    record("full", quads, started)
    if ok:
        yield "full", quads
        if first_only and quads:
            return

    started = time.perf_counter()
    quads = dedupe_quads(_detect_tiled(detector, gray, first_only=first_only))
    record("tiled", quads, started)
    yield "tiled", quads
