"""Text lines on a drawn tag: found by the text detector, longest first, each along its own long side."""
import cv2
import numpy as np
import pytest

from tagreader.text_lines import MIN_LINE_RATIO, find_tag_lines, reading_quad

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
    # A long product code with a word space, and a short line below the bars.
    cv2.putText(image, "HUTS 6D713 14 105 BLK", (130, 275), font, 1.1, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(image, "W279", (330, 425), font, 1.1, (30, 30, 30), 2, cv2.LINE_AA)
    return image


def test_boxes_run_clockwise_from_the_top_left():
    from tagreader.text_detector import clockwise
    points = np.array([[10., 40.], [10., 20.], [90., 20.], [90., 40.]])
    assert clockwise(points).tolist() == [[10, 20], [90, 20], [90, 40], [10, 40]]


@pytest.mark.parametrize("box,start,end", [
    ([[10, 20], [90, 20], [90, 40], [10, 40]], [10, 20], [90, 20]),     # flat: left to right
    ([[10, 20], [30, 20], [30, 100], [10, 100]], [10, 100], [10, 20]),  # standing: bottom to top
])
def test_reading_quad_starts_on_the_long_side(box, start, end):
    quad = reading_quad(np.asarray(box, float))
    assert quad[0].tolist() == start and quad[1].tolist() == end
    assert np.linalg.norm(quad[1] - quad[0]) > np.linalg.norm(quad[3] - quad[0])


@pytest.mark.parametrize("turn", [None, cv2.ROTATE_90_COUNTERCLOCKWISE])
def test_tag_lines_come_longest_first_without_short_ones(tag, turn):
    pytest.importorskip("onnxruntime")
    image = tag if turn is None else cv2.rotate(tag, turn)
    # The tag twice as large, placed in a 48MP frame where the 12MP ROI points.
    frame = np.full((6000, 8000, 3), 40, np.uint8)
    height, width = image.shape[:2]
    frame[1600:1600 + 2 * height, 2000:2000 + 2 * width] = cv2.resize(image, (2 * width, 2 * height),
                                                                      interpolation=cv2.INTER_CUBIC)
    roi = [1000, 800, 1000 + width, 800 + height]
    result = find_tag_lines(frame, roi)
    regions = result["regions"]
    assert regions and result["origin"] == (2000, 1600) and result["tag"].shape == (2 * height, 2 * width)
    ratios = [r["ratio"] for r in regions]
    assert ratios == sorted(ratios, reverse=True) and min(ratios) >= MIN_LINE_RATIO
    first = np.asarray(regions[0]["quad_target"])
    along = first[1] - first[0]
    if turn is None:
        assert along[0] > 0 and abs(along[1]) < .1 * along[0]
        assert 240 < (first[:, 1].mean() - 1600) / 2 < 290
    else:
        assert along[1] < 0 and abs(along[0]) < .1 * -along[1]
    # The short W279 line is too stubby to be a product code.
    assert len(regions) == 1
