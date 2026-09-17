"""apps/tools 스크립트를 `python apps/web.py`처럼 직접 실행해도 tagreader를 찾게 한다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
