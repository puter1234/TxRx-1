"""회귀 테스트: images/의 샘플 9장이 expected.json의 값으로 읽히는지, 그리고 예산 안에 드는지.

OCR을 합칠 때 이 테스트가 통과하는 한 바코드 쪽은 건드리지 않은 것이다.
"""
import json
import time
from pathlib import Path

import pytest

import tagreader
from tagreader.io import imread

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = json.loads((ROOT / "tests" / "expected.json").read_text(encoding="utf-8"))

# 한 프로세스에서 OCR과 합쳐 1초 안에 끝내야 하므로 바코드 몫의 상한을 잡는다.
# (imdecode 제외, 12MP 기준. 실측은 중앙값 ~50ms / 최악 ~250ms)
BUDGET_MS = 400


@pytest.fixture(scope="session")
def images():
    return {stem: imread(ROOT / "images" / f"{stem}.jpg") for stem in EXPECTED}


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_decodes_expected_value(images, stem):
    tags = tagreader.read_tag(images[stem])
    values = {t.text for t in tags if t.text}
    assert values, f"{stem}: 바코드를 하나도 읽지 못함"
    assert set(EXPECTED[stem]) <= values, f"{stem}: 기대 {EXPECTED[stem]}, 실제 {values}"


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_crops_are_usable_for_ocr(images, stem):
    for tag in tagreader.read_tag(images[stem]):
        assert tag.above is not None and tag.below is not None
        # 바코드가 이미지 가장자리에 붙으면 한쪽이 빌 수 있으나, 둘 다 비면 크롭 로직이 깨진 것
        assert tag.above.size or tag.below.size, f"{stem}: above/below가 모두 비어 있음"


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_within_time_budget(images, stem):
    img = images[stem]
    tagreader.read_tag(img)  # 웜업 (감지기 초기화 등)
    t0 = time.perf_counter()
    tagreader.read_tag(img)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < BUDGET_MS, f"{stem}: {elapsed_ms:.0f} ms > {BUDGET_MS} ms 예산"


def test_values_only_path_is_faster(images):
    """값만 필요할 때(want_crops=False)는 크롭 생성을 건너뛰어야 한다."""
    img = next(iter(images.values()))
    assert tagreader.read_barcode_values(img)
