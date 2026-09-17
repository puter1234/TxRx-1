"""폴더 또는 파일 하나를 일괄 처리해 크롭/디코딩 결과를 저장한다.

기존 crop_barcode_text.py CLI를 대체한다.
실행: python tools/batch.py images/ out/ --debug
"""
import argparse
import sys
import time
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path 설정)
import tagreader
from tagreader.io import IMAGE_EXTS, imread, imwrite


def process(path: Path, out_root: Path, args) -> bool:
    img = imread(path)
    if img is None:
        print(f"[skip] 읽기 실패: {path}", file=sys.stderr)
        return False

    t0 = time.perf_counter()
    tags = tagreader.read_tag(
        img,
        want_rotated=args.debug,
        margin_above=args.margin_above_ratio,
        margin_below=args.margin_below_ratio,
        full_width=not args.no_full_width,
        x_pad_ratio=args.x_pad_ratio,
    )
    elapsed = (time.perf_counter() - t0) * 1000

    if not tags:
        print(f"[fail] 바코드 없음: {path.name}  ({elapsed:.0f} ms)")
        return False

    for i, tag in enumerate(tags):
        out_dir = out_root / path.stem / f"barcode_{i}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("above", "below"):
            crop = getattr(tag, name)
            if crop is not None and crop.size:
                imwrite(out_dir / f"{name}.png", crop)
        if tag.text:
            (out_dir / "decoded.txt").write_text(tag.text, encoding="utf-8")
        if args.debug:
            if tag.rotated is not None:
                imwrite(out_dir / "rotated.png", tag.rotated)
            debug = tag.debug_view(margin_above=args.margin_above_ratio,
                                   margin_below=args.margin_below_ratio)
            if debug is not None:
                imwrite(out_dir / "debug.png", debug)

        print(f"  [{i}] {tag.text or '디코딩 실패'}  {tag.format}  {tag.angle:.1f}도  ({tag.stage})")

    print(f"[ok] {path.name}: 바코드 {len(tags)}개  {elapsed:.0f} ms")
    return True


def main():
    parser = argparse.ArgumentParser(description="택 사진 일괄 처리 (바코드 디코딩 + OCR용 크롭)")
    parser.add_argument("input", type=Path, help="이미지 파일 또는 폴더")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--margin-above-ratio", type=float, default=1.2, help="바코드 높이 대비 위쪽 크롭 배수")
    parser.add_argument("--margin-below-ratio", type=float, default=1.2, help="바코드 높이 대비 아래쪽 크롭 배수")
    parser.add_argument("--no-full-width", action="store_true", help="크롭 폭을 바코드 폭 기준으로 제한")
    parser.add_argument("--x-pad-ratio", type=float, default=0.15, help="--no-full-width일 때 좌우 여백")
    parser.add_argument("--debug", action="store_true", help="rotated.png / debug.png도 저장")
    args = parser.parse_args()

    if args.input.is_dir():
        files = [p for p in sorted(args.input.iterdir()) if p.suffix.lower() in IMAGE_EXTS]
        if not files:
            print(f"이미지 파일을 찾지 못했습니다: {args.input}", file=sys.stderr)
            sys.exit(1)
    elif args.input.exists():
        files = [args.input]
    else:
        print(f"입력이 없습니다: {args.input}", file=sys.stderr)
        sys.exit(1)

    t0 = time.perf_counter()
    ok = sum(process(p, args.output_dir, args) for p in files)
    print(f"\n{ok}/{len(files)} 성공, 총 {(time.perf_counter() - t0):.1f}s -> {args.output_dir}")


if __name__ == "__main__":
    main()
