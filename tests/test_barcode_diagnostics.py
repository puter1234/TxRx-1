import numpy as np
import pytest

import tagreader


@pytest.mark.parametrize("located, expected", [(False, "not_detected"), (True, "decode_failed")])
def test_diagnostics_distinguish_no_location_from_unreadable_value(monkeypatch, located, expected):
    quad = np.array([[10, 10], [90, 10], [90, 40], [10, 40]], dtype=float)
    attempts = []

    def candidates(image, diagnostics=None):
        if diagnostics is not None:
            diagnostics.append(dict(stage="full", candidates=int(located), detect_ms=0,
                                    decode_ms=0, attempted=0, decoded=0))
        yield "full", [quad] if located else []

    def decode(image, quad):
        attempts.append("region")
        return None, None

    def scan(image):
        attempts.append("whole")
        return []

    monkeypatch.setattr(tagreader, "candidate_tiers", candidates)
    monkeypatch.setattr(tagreader, "decode_quad", decode)
    monkeypatch.setattr(tagreader, "scan", scan)
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    assert tagreader.read_tag(frame) == []
    baseline = attempts[:]
    attempts.clear()
    diagnostic = {}
    assert tagreader.read_tag(frame, diagnostics=diagnostic) == []
    assert diagnostic["status"] == expected
    assert diagnostic["decoded"] == 0
    assert attempts == baseline  # Observing the result must never trigger another read.


def test_location_only_keeps_ocr_geometry_without_decoding_or_retrying(monkeypatch):
    quad = np.array([[50, 50], [180, 50], [180, 75], [50, 75]], dtype=float)

    def candidates(image, diagnostics=None):
        if diagnostics is not None:
            diagnostics.append(dict(stage="full", candidates=1, detect_ms=0,
                                    decode_ms=0, attempted=0, decoded=0))
        yield "full", [quad]
        pytest.fail("Location was already found; no further search should run")

    def forbidden(*args, **kwargs):
        pytest.fail("OCR-only processing must not decode barcode values")

    monkeypatch.setattr(tagreader, "candidate_tiers", candidates)
    monkeypatch.setattr(tagreader, "decode_quad", forbidden)
    monkeypatch.setattr(tagreader, "scan", forbidden)
    diagnostic = {}
    tags = tagreader.read_tag(np.zeros((160, 240, 3), dtype=np.uint8),
                              decode_values=False, want_crops=False,
                              want_rotated=False, diagnostics=diagnostic)
    assert len(tags) == 1
    assert tags[0].text is None and tags[0].format is None
    assert np.array_equal(tags[0].quad, quad)
    assert tags[0].rotated is None
    assert diagnostic["status"] == "located"
    assert diagnostic["decoded"] == 0
    assert diagnostic["stages"][0]["attempted"] == 0


@pytest.mark.parametrize("angle", [0, 30, 90, -90])
def test_text_region_preserves_pixel_scale_and_samples_only_label_area(angle):
    import cv2
    from tagreader.crop import rotate_text_region
    from tagreader.geometry import transform_points

    frame = np.full((800, 1000, 3), 40, dtype=np.uint8)
    quad = np.array([[420, 385], [580, 385], [580, 415], [420, 415]], dtype=float)
    quad = transform_points(quad, cv2.getRotationMatrix2D((500, 400), -angle, 1.0))
    region, aligned = rotate_text_region(frame, quad, angle, 1.6, 0.1)
    assert region.size < frame.size / 10
    assert np.all(region == 40)
    assert np.linalg.norm(aligned[1] - aligned[0]) == pytest.approx(160)
    assert np.linalg.norm(aligned[3] - aligned[0]) == pytest.approx(30)


def test_text_region_at_image_edge_does_not_invent_extra_white_text_band():
    from tagreader.crop import rotate_text_region

    frame = np.full((60, 120, 3), 40, dtype=np.uint8)
    quad = np.array([[20, 20], [100, 20], [100, 40], [20, 40]], dtype=float)
    region, aligned = rotate_text_region(frame, quad, 0, 1.6, 0.1)
    assert np.all(region == 40)
    assert aligned[:, 1].min() == 20
