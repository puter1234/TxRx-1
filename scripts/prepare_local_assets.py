"""Copy already available assets. Never downloads at runtime."""

from pathlib import Path
import argparse, hashlib, json, shutil

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--cache", type=Path, required=True)
p.add_argument("--hazzys", type=Path, required=True)
args = p.parse_args()
repository = args.cache / "hub/baudm_parseq_main"
weight = args.cache / "hub/checkpoints/parseq-bb5792a6.pt"
if not repository.is_dir() or not weight.is_file():
    raise SystemExit("기존 PARSeq 소스와 가중치가 모두 필요합니다.")
dest = root / "models/parseq"
dest.mkdir(parents=True, exist_ok=True)
shutil.copytree(
    repository,
    dest / "source",
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("__pycache__", ".git", "*.pyc"),
)
shutil.copy2(weight, dest / weight.name)
manifest = {
    f.relative_to(dest).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
    for f in sorted(dest.rglob("*"))
    if f.is_file() and f.name != "manifest.json"
}
(dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
data = json.loads(args.hazzys.read_text(encoding="utf-8"))
brand = {
    "id": "hazzys",
    "name": "헤지스",
    "revision": 1,
    "options": [
        {"key": k, "label": label, "values": sorted({r[k] for r in data["rows"]})}
        for k, label in [("style", "품번"), ("color", "색상"), ("size", "사이즈")]
    ],
    "decoder": {"kind": "hazzys_6bit_crc8", "records": {}},
    "ocr_regions": [],
    "barcode_records": {},
    "note": "제공된 127개 표본에서 확인한 6-bit 품번/색상/사이즈 및 CRC8 규칙. 공식 제조사 규격 아님. 후행 01·일련번호·4D의 의미는 미확정. CRC는 정품 인증 아님.",
}
(root / "config/brands/hazzys.samples.json").write_text(
    json.dumps(brand, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    f'Local assets ready: {len(manifest)} files; {len(data["rows"])} RFID samples; no network used.'
)
