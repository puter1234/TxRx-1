"""Reject nearby text that does not run along the detected barcode."""
import cv2
import numpy as np
import pytest

from vendor.barcode_pipeline.barcode_segmenter.barseg.text_regions import _line_boxes, extract_text_regions


def printed_line(angle):
    image = np.zeros((120, 500), np.uint8)
    cv2.putText(image, "E62002ATW42BLK0050", (40, 70), cv2.FONT_HERSHEY_SIMPLEX, .8, 255, 2, cv2.LINE_8)
    return cv2.warpAffine(image, cv2.getRotationMatrix2D((250, 60), angle, 1), (500, 120))


@pytest.mark.parametrize("angle", [0, 3, -3])
def test_parallel_text_keeps_a_full_line(angle):
    boxes = _line_boxes(printed_line(angle), 360, 60)
    assert len(boxes) == 1
    assert boxes[0][0][2] - boxes[0][0][0] > 250


@pytest.mark.parametrize("angle", [8, -8, 10, 90])
def test_reject_text_at_a_different_angle_even_if_its_rectangle_is_wide(angle):
    assert not _line_boxes(printed_line(angle), 360, 60)


@pytest.mark.parametrize("angle", [0, 25, -30, 180])
def test_text_crop_follows_the_barcode_when_the_whole_label_rotates(angle):
    image = np.full((500, 600, 3), 255, np.uint8)
    for x in range(120, 450, 7):
        cv2.rectangle(image, (x, 210), (x+2, 270), (0, 0, 0), -1)
    cv2.putText(image, "E62002ATW42BLK0050", (125, 195), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
    matrix = cv2.getRotationMatrix2D((300, 250), angle, 1)
    rotated = cv2.warpAffine(image, matrix, (600, 500), borderValue=(255, 255, 255))
    polygon = cv2.transform(np.float32([[[120, 210], [452, 210], [452, 270], [120, 270]]]), matrix)[0]
    result = extract_text_regions(rotated, [{"polygon_roi": polygon.tolist()}])
    assert len(result["regions"]) == 1
    region = result["regions"][0]
    points = np.asarray(region["quad_roi"])
    assert np.linalg.norm(points[1] - points[0]) > 250
    direction = np.degrees(np.arctan2(*(points[1] - points[0])[::-1]))
    assert abs((direction + angle + 90) % 180 - 90) < 5
