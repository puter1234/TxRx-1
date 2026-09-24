"""바코드 값과 OCR 문자열을 비교하기 위한 정규화 및 판정.

실측하면 OCR 자체는 잘 읽는데 표기 규약 때문에 문자열이 안 맞는다:

    인쇄 '*HUTS 6A211 BK 095*'  vs  바코드 'HUTS6A211BK095'   -> 공백과 Code39 시작/끝 '*'
    인쇄 'TMTY62141-102-110'    vs  바코드 'TMTY62141102110'  -> 하이픈
    인쇄 'E61001ATS30BLKOXLO'   vs  바코드 'E61001ATS30BLK0XL0' -> O와 0

앞의 둘은 구분자 제거(strict)로 해결되고, 마지막은 글자 모양이 같아서 사람도 못 가리는
혼동쌍이라 통합(loose)해야 한다. 두 단계를 나눠 두고 어느 쪽에서 맞았는지 UI에 표시한다.
"""
import re
from dataclasses import dataclass

# 폰트상 사실상 같은 글자로 보이는 쌍. 잘못 통합하면 서로 다른 시리얼을 같다고 할 수 있어
# 실제로 혼동이 관찰된 것만 넣는다.
CONFUSABLES = str.maketrans({
    "O": "0", "Q": "0", "D": "0",
    "I": "1", "L": "1",
    "S": "5", "B": "8", "Z": "2", "G": "6",
})


def normalize_strict(text: str) -> str:
    """대문자화 + 영숫자만 남긴다 (공백·하이픈·`*` 등 구분자 제거)."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def normalize_loose(text: str) -> str:
    """strict에 더해 혼동 글자쌍을 하나로 통합한다."""
    return normalize_strict(text).translate(CONFUSABLES)


@dataclass
class Verdict:
    status: str            # 'match' | 'match_loose' | 'mismatch' | 'no_text' | 'no_barcode' | 'ocr_read'
    barcode: str | None
    text: str | None       # 바코드와 가장 잘 맞은 OCR 줄
    confidence: float = 0.0
    label: str = ""        # UI 표시용 한국어 라벨
    detail: str = ""

    @property
    def ok(self) -> bool:
        # Reading text without a comparison is not an inspection match.
        return self.status in ("match", "match_loose")


_LABELS = {
    "match": "일치",
    "match_loose": "일치 (혼동 글자 보정)",
    "mismatch": "불일치",
    "no_text": "텍스트 인식 실패",
    "no_barcode": "바코드 인식 실패",
}


def compare(barcode: str | None, candidates: list[tuple[str, float]]) -> Verdict:
    """바코드 값과 OCR 후보 줄들을 대조해 판정한다.

    candidates는 (문자열, confidence) 목록. strict 일치를 먼저 찾고, 없으면 loose 일치,
    그것도 없으면 confidence가 가장 높은 후보를 불일치 근거로 보여준다.
    """
    if not barcode:
        return Verdict("no_barcode", None, None, label=_LABELS["no_barcode"])

    usable = [(t, c) for t, c in candidates if normalize_strict(t)]
    if not usable:
        return Verdict("no_text", barcode, None, label=_LABELS["no_text"])

    target_strict, target_loose = normalize_strict(barcode), normalize_loose(barcode)

    for status, key, target in (
        ("match", normalize_strict, target_strict),
        ("match_loose", normalize_loose, target_loose),
    ):
        hits = [(t, c) for t, c in usable if key(t) == target]
        if hits:
            text, conf = max(hits, key=lambda tc: tc[1])
            return Verdict(status, barcode, text, conf, _LABELS[status])

    text, conf = max(usable, key=lambda tc: tc[1])
    return Verdict(
        "mismatch", barcode, text, conf, _LABELS["mismatch"],
        detail=f"바코드 {target_strict} != 인쇄 {normalize_strict(text)}",
    )
