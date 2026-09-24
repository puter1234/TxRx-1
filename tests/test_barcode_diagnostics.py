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
