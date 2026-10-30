"""The process test's alternative text finders on a drawn tag: one line per side, full width."""
import cv2
import numpy as np
import pytest

from tagreader.text_lines import find_detected, find_lines
from vendor.barcode_pipeline.barcode_segmenter.barseg.text_regions import extract_text_regions

ROI = [1000, 800, 1900, 1500]


@pytest.fixture
def tag():
    image = np.full((700, 900, 3), 225, np.uint8)
    rng = np.random.default_rng(3)
    x = 250
    while x < 650:
        width = int(rng.integers(2, 7))
        image[300:380, x:x + width] = 20
        x += width + int(rng.integers(2, 7))
    font = cv2.FONT_HERSHEY_SIMPLEX
    # A product code longer than the barcode, with a word space, and a short line below.
    cv2.putText(image, "HUTS 6D713 14 105 BLK", (130, 275), font, 1.1, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(image, "W279,000", (330, 425), font, 1.1, (30, 30, 30), 2, cv2.LINE_AA)
    polygon = [[250, 300], [650, 300], [650, 380], [250, 380]]
    return image, [{"polygon_roi": polygon}]


def spans(result):
    found = {}
    for region in result["regions"]:
        quad = np.asarray(region["quad_roi"])
        found[region["side_in_aligned_image"]] = (quad[:, 0].min(), quad[:, 0].max(), quad[:, 1].min(), quad[:, 1].max())
        assert len(region["quad_source"]) == 4 and len(region["quad_target"]) == 4
        assert region["barcode_index"] == 0
    return found


def text_extent(image):
    ink = np.where(image[:290, :, 1] < 120)
    return ink[1].min(), ink[1].max()


def test_lines_keeps_the_whole_code_line_and_one_line_per_side(tag):
    image, instances = tag
    left, right = text_extent(image)
    result = find_lines(image, instances, ROI, [4000, 3000], [8000, 6000])
    found = spans(result)
    assert set(found) == {"above", "below"} and result["region_count"] == 2
    x0, x1, y0, y1 = found["above"]
    assert x0 <= left and x1 >= right and y1 <= 300
    assert found["below"][2] >= 380
    vendored = spans(extract_text_regions(image, instances, ROI, [4000, 3000], [8000, 6000]))
    assert vendored["above"][0] > left or vendored["above"][1] < right


def test_detector_finds_the_lines_beside_the_barcode(tag):
    pytest.importorskip("onnxruntime")
    image, instances = tag
    left, right = text_extent(image)
    result = find_detected(image, instances, ROI, [4000, 3000], [8000, 6000])
    found = spans(result)
    assert set(found) == {"above", "below"} and result["region_count"] == 2
    x0, x1, _, y1 = found["above"]
    assert x0 <= left + 5 and x1 >= right - 5 and y1 <= 305
    assert found["below"][2] >= 375
