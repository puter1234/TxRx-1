"""PARSeq 기반 텍스트 인식 + 택 텍스트 라인 세그멘테이션.

tagreader가 바코드와 그 주변 영역을 내주면, 여기서 그 영역의 텍스트 줄을 찾아 읽는다.

    from ocr import Recognizer, find_text_lines
"""
from .core import MODEL_NAMES, Recognizer, resolve_device, versions
from .normalize import Verdict, compare, normalize_loose, normalize_strict
from .textlines import find_text_lines

__all__ = [
    "MODEL_NAMES", "Recognizer", "resolve_device", "versions",
    "find_text_lines",
    "Verdict", "compare", "normalize_strict", "normalize_loose",
]
