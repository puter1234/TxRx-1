"""Synthetic geometry checks; these do not substitute for field OCR accuracy."""
import cv2
import numpy as np
import pytest

from tagreader.stripes import candidate_tiers, normalize_local


def label_image(angle=0, contrast=190, size=None):
    image = np.full((1080, 1920, 3), 220, np.uint8)
    x, y = 650, 430
    # Deliberately not an encoded barcode: detection must not depend on a value.
    for i, width in enumerate(np.random.default_rng(7).choice([3, 5, 8, 11], 80)):
        if i % 2 == 0:
            image[y:y + 130, x:x + width] = 220 - contrast
        x += width
    quad = np.float32([[650, y], [x, y], [x, y + 130], [650, y + 130]])
    cv2.putText(image, "AB12CD345", (650, 410), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 30, 30), 2)
    cv2.putText(image, "123456789", (650, 602), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 30, 30), 2)
    matrix = cv2.getRotationMatrix2D((960, 540), angle, 1)
    image = cv2.warpAffine(image, matrix, (1920, 1080), borderValue=(220, 220, 220))
    quad = cv2.transform(quad[None], matrix)[0]
    image = np.clip(image.astype(float) * np.linspace(.45, 1, 1920)[None, :, None], 0, 255).astype(np.uint8)
    image = cv2.GaussianBlur(image, (3, 3), .7)
    if size:
        image = cv2.resize(image, size)
        quad *= [size[0] / 1920, size[1] / 1080]
    return image, quad


def intersection_over_union(a, b):
    a, b = a.astype(np.float32), b.astype(np.float32)
    intersection, _ = cv2.intersectConvexConvex(a, b)
    return intersection / (cv2.contourArea(a) + cv2.contourArea(b) - intersection)


@pytest.mark.parametrize("angle", [0, 17, -32, 45, 90])
@pytest.mark.parametrize("contrast", [190, 45])
def test_locates_unreadable_stripes_under_rotation_shadow_and_blur(angle, contrast):
    image, expected = label_image(angle, contrast)
    original = image.copy()
    rows = []
    quads = [q for _, candidates in candidate_tiers(image, diagnostics=rows) for q in candidates]
    assert len(quads) == 1
    assert intersection_over_union(expected, quads[0]) > .9
    assert max(rows[0]["working_width"], rows[0]["working_height"]) == 960
    assert rows[0]["attempted"] == rows[0]["decoded"] == 0
    np.testing.assert_array_equal(image, original)


@pytest.mark.parametrize("scene", ["blank", "text", "ones", "uniform", "woven", "noise"])
def test_rejects_non_barcode_patterns(scene):
    image = np.full((720, 1280, 3), 230, np.uint8)
    if scene in ("text", "ones"):
        for y in range(70, 660, 60):
            cv2.putText(image, "HUTS6C612 095 ABC123" if scene == "text" else "IIIIIIIII 111111111",
                        (80, y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (20, 20, 20), 2)
    elif scene == "uniform":
        for x in range(200, 1050, 12):
            image[200:500, x:x + 6] = 20
    elif scene == "woven":
        image[:, ::8] = 110
        image[::8] = 110
    elif scene == "noise":
        image = np.random.default_rng(0).integers(0, 256, image.shape, dtype=np.uint8)
    assert not [q for _, quads in candidate_tiers(image) for q in quads]


def test_green_channel_is_used_and_coordinates_return_to_odd_sized_original():
    image, expected = label_image(17, size=(3847, 2163))
    image[:, :, 0] = 242
    image[:, :, 2] = 137
    quads = [q for _, candidates in candidate_tiers(image) for q in candidates]
    assert len(quads) == 1 and intersection_over_union(expected, quads[0]) > .9
    monochrome = [q for _, candidates in candidate_tiers(image[:, :, 1]) for q in candidates]
    np.testing.assert_allclose(quads, monochrome)
    assert normalize_local(np.full((32, 32), 90, np.uint8)).min() == 128


def test_original_color_text_crops_reach_ocr_without_barcode_decoding(monkeypatch):
    import pipeline
    import tagreader
    image, _ = label_image(size=(3840, 2160))
    image[:, :, 0] = 242
    image[:, :, 2] = 137
    crops = []

    def forbidden(*args, **kwargs):
        pytest.fail("Stripe-only location must not call a decoder or the legacy locator")

    monkeypatch.setattr(tagreader, "decode_quad", forbidden)
    monkeypatch.setattr(tagreader, "scan", forbidden)
    monkeypatch.setattr(tagreader, "candidate_tiers", forbidden)

    class Reader:
        def read(self, image):
            crops.append(np.asarray(image))
            return {"text": "TEST", "confidence": .9, "ms": 1}

    diagnostics = {}
    result = pipeline.process_task(image, Reader(), decode_values=False, locator="stripes", diagnostics=diagnostics)
    assert result.error is None and len(result.reads) == 1
    assert result.reads[0].barcode is None and result.reads[0].stage == "stripes"
    assert len(crops) >= 2
    assert all(crop.shape[1] > 400 for crop in crops)
    for crop in crops:
        assert np.median(crop[:, :, 0]) == 137  # RGB conversion, original color retained.
        assert np.median(crop[:, :, 2]) == 242
    assert diagnostics["locator"] == "stripes" and len(diagnostics["regions"]) == 1
    assert diagnostics["source_width"] == 3840
