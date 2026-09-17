"""통합 파이프라인 회귀 테스트.

바코드만 검증하는 test_read_tag.py 와 달리, 여기서는 바코드 <-> 인쇄 시리얼 대조까지 본다.
OCR 테스트는 PARSeq 로드가 필요해 느리므로, 모델을 못 올리는 환경에서는 자동으로 skip한다.
(CI/오프라인에서도 바코드 테스트는 계속 돌아야 하기 때문)
"""
import json
from pathlib import Path

import pytest

import pipeline
from ocr.normalize import compare, normalize_loose, normalize_strict
from tagreader.io import imread

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = json.loads((ROOT / "tests" / "expected.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 정규화/판정 로직 — 모델 없이 도는 순수 로직이라 항상 실행된다
# --------------------------------------------------------------------------- #
def test_strict_removes_separators():
    # Code39/93 인쇄 관례의 시작·끝 '*', 공백, 하이픈을 제거해야 바코드 값과 같아진다
    assert normalize_strict("*HUTS 6A211 BK 095*") == "HUTS6A211BK095"
    assert normalize_strict("TMTY62141-102-110") == "TMTY62141102110"


def test_loose_folds_confusables():
    # O/0 처럼 글자 모양이 같은 쌍만 통합한다
    assert normalize_loose("E61001ATS30BLKOXLO") == normalize_loose("E61001ATS30BLK0XL0")
    assert normalize_loose("HWTS68352N3095") == normalize_loose("HWTS6B352N3095")


def test_loose_does_not_fold_unrelated_chars():
    # 통합이 지나치면 서로 다른 시리얼을 같다고 판정한다. 모양이 다른 글자는 남아야 한다.
    assert normalize_loose("ABC123") != normalize_loose("ABC124")
    assert normalize_loose("TNTMS1201060XL") != normalize_loose("TNPMT1103030XL")


@pytest.mark.parametrize("barcode,ocr,expected_status", [
    ("HUTS6A211BK095", "HUTS6A211BK095*", "match"),
    ("TMTY62141102110", "TMTY62141-102-110", "match"),
    ("E61001ATS30BLK0XL0", "E61001ATS30BLKOXLO", "match_loose"),
    ("HWTS6B352N3095", "PHOTOGRAPHY", "mismatch"),
])
def test_compare_status(barcode, ocr, expected_status):
    assert compare(barcode, [(ocr, 0.9)]).status == expected_status


def test_compare_without_barcode_or_text():
    assert compare(None, [("ANYTHING", 0.9)]).status == "no_barcode"
    assert compare("ABC123", []).status == "no_text"


def test_mismatch_is_not_ok():
    """오탐이 통과로 잡히면 검수 자체가 무의미해진다."""
    verdict = compare("HWTS6B352N3095", [("PHOTOGRAPHY", 0.99)])
    assert not verdict.ok
    assert verdict.detail


# --------------------------------------------------------------------------- #
# 실제 사진 -> 바코드 + OCR + 대조 (모델 필요)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def recognizer():
    try:
        from ocr import Recognizer

        return Recognizer("parseq", "auto")
    except Exception as exc:
        pytest.skip(f"PARSeq를 로드할 수 없어 OCR 테스트를 건너뜁니다: {exc}")


@pytest.mark.slow
@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_barcode_matches_printed_serial(recognizer, stem):
    """택에 인쇄된 시리얼이 바코드 값과 대조되어야 한다 — 이 시스템의 존재 이유."""
    result = pipeline.process_task(imread(ROOT / "images" / f"{stem}.jpg"), recognizer)
    assert result.reads, f"{stem}: {result.error}"

    read = result.reads[0]
    assert read.barcode in EXPECTED[stem]
    assert read.verdict.ok, (
        f"{stem}: 바코드 {read.barcode} vs 인쇄 {read.verdict.text} -> {read.verdict.label}"
    )


@pytest.mark.slow
def test_barcode_only_mode_needs_no_model():
    """recognizer=None이면 모델 없이 바코드만 읽고 no_text로 판정해야 한다."""
    stem = sorted(EXPECTED)[0]
    result = pipeline.process_task(imread(ROOT / "images" / f"{stem}.jpg"), None)
    assert result.reads[0].barcode in EXPECTED[stem]
    assert result.reads[0].verdict.status == "no_text"
