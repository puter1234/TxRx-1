"""Read-only preflight. Does not open GPIO, serial, camera or a browser."""

import argparse, importlib.metadata, json, platform, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def inspect():
    from station.schema import StationConfig
    from station.vision import verify_model

    results = []
    for package in (
        "fastapi",
        "uvicorn",
        "websockets",
        "pydantic",
        "pillow",
        "torch",
        "torchvision",
        "timm",
        "opencv-python",
        "zxing-cpp",
        "psutil",
        "pyserial",
    ):
        try:
            results.append(
                {
                    "check": package,
                    "ok": True,
                    "version": importlib.metadata.version(package),
                }
            )
        except importlib.metadata.PackageNotFoundError:
            results.append({"check": package, "ok": False, "detail": "missing"})
    try:
        results.append(
            {
                "check": "model_manifest",
                "ok": True,
                "sha256": verify_model(ROOT / "models/parseq"),
            }
        )
    except Exception as exc:
        results.append({"check": "model_manifest", "ok": False, "detail": str(exc)})
    results.append(
        {
            "check": "frontend_build",
            "ok": (ROOT / "ocr/frontend/dist/index.html").exists(),
        }
    )
    cfg_path = ROOT / "config/station.json"
    try:
        cfg = (
            StationConfig.model_validate_json(cfg_path.read_text(encoding="utf-8"))
            if cfg_path.exists()
            else StationConfig()
        )
        commissioning = cfg.commissioning.blockers()
        results.append({"check": "config", "ok": True, "mode": cfg.mode})
    except Exception as exc:
        commissioning = ["invalid_config"]
        results.append({"check": "config", "ok": False, "detail": str(exc)})
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "software_ready": all(r["ok"] for r in results),
        "hardware_acceptance": "NOT_VERIFIED",
        "commissioning_required": commissioning,
        "checks": results,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = inspect()
    report = json.dumps(result, ensure_ascii=False, indent=2)
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    raise SystemExit(0 if result["software_ready"] else 1)
