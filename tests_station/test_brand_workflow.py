from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from station.app import create_app
from station.rules import RuleError, validate_recipe
from station.schema import Brand, BrandCaps, Recipe, WorkPreset
from station.vision import Vision
from test_api import login
from test_moving_api import line
from test_roles_stream import enter


def test_brand_checks_and_both_reference_tables_survive_edit(tmp_path, brand):
    app = create_app(tmp_path)
    brand.caps = BrandCaps(rfid=True, ocr=False, barcode_poly=True)
    brand.barcode_records = {"TAG": {"size": "095"}}
    brand.barcode_poly_records = {"BAG": {"size": "095"}}
    with TestClient(app) as client:
        login(client)
        saved = client.post("/api/brands", json={"brand": brand.model_dump(), "reason": "브랜드 설정 변경"})
        assert saved.status_code == 200, saved.text
        changed = saved.json()
        changed["caps"]["ocr"] = True
        saved = client.post("/api/brands", json={"brand": changed, "expected_revision": 1, "reason": "검사 항목 변경"})
        assert saved.status_code == 200, saved.text
        restored = next(b for b in client.get("/api/brands").json() if b["id"] == brand.id)
        assert restored["caps"] == {"rfid": True, "ocr": True, "barcode_tag": False, "barcode_poly": True}
        assert restored["barcode_records"] == brand.barcode_records
        assert restored["barcode_poly_records"] == brand.barcode_poly_records
        assert restored["decoder"] == brand.decoder.model_dump()


def test_disabled_brand_channel_cannot_be_started(brand, recipe):
    brand.caps = BrandCaps(rfid=False)
    with pytest.raises(RuleError, match="사용하지 않는"):
        validate_recipe(recipe, brand)


def test_operator_start_uses_selected_checks_and_saved_timing(line, recipe):
    preset = WorkPreset(id="brand-flow", name="브랜드 촬영", kind="condition", brand_id="hazzys",
                        channels=["ocr", "rfid"], flow={"capture_delay_ms": 350, "low_speed_ms": 900,
                                                     "rfid_attempts": 4, "rfid_interval_ms": 80})
    assert line.client.post("/api/presets", json={"preset": preset.model_dump()}).status_code == 200
    line.client.post("/api/auth/logout", json={})
    enter(line.client)
    result = line.client.post("/api/presets/brand-flow/start", json={"preset_revision": 1,
        "brand_revision": 1, "channels": ["rfid"], "targets": recipe.targets})
    assert result.status_code == 200, result.text
    actual = result.json()["session"]["recipe"]
    assert actual["channels"] == ["rfid"]
    assert actual["flow"]["capture_delay_ms"] == 350
    assert actual["flow"]["low_speed_ms"] == 900
    assert actual["flow"]["rfid_attempts"] == 4
    assert actual["flow"]["rfid_interval_ms"] == 80


@pytest.mark.parametrize("kind", ["simple", "condition"])
def test_operator_can_start_default_hardware_flow_without_admin(line, recipe, kind):
    line.client.post("/api/auth/logout", json={})
    enter(line.client)
    body = recipe.model_dump() if kind == "condition" else {
        "kind": "simple", "brand_id": "__simple__", "brand_revision": 1, "targets": {}, "channels": []}
    body["default_flow"] = True
    # Supplying custom motion settings still requires the administrator.
    blocked = line.client.post("/api/sessions", json={**body, "flow": {"low_speed_ms": 1}})
    assert blocked.status_code == 403
    response = line.client.post("/api/sessions", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["session"]["recipe"]["flow"]["low_speed_ms"] == 500


@pytest.mark.parametrize("targets,codes,poly_size,expected", [
    (["tag"], ["TAG"], "095", None),
    (["poly"], ["BAG"], "095", None),
    (["tag", "poly"], ["BAG", "TAG"], "095", None),
    (["tag", "poly"], ["TAG", "BAG"], "100", "BARCODE_LABEL_MISMATCH"),
    (["tag", "poly"], ["TAG"], "095", "BARCODE_MISSING"),
    (["poly"], ["TAG"], "095", "BARCODE_UNREGISTERED"),
])
def test_label_targets_require_their_own_registered_reads(monkeypatch, targets, codes, poly_size, expected):
    import tagreader
    monkeypatch.setattr(tagreader, "read_tag", lambda image: [SimpleNamespace(text=code) for code in codes])
    brand = Brand(id="labels", name="Labels", options=[{"key": "size", "label": "사이즈", "values": ["095", "100"]}],
                  barcode_records={"TAG": {"size": "095"}}, barcode_poly_records={"BAG": {"size": poly_size}})
    recipe = Recipe(brand_id=brand.id, brand_revision=1, targets={"size": "095"}, channels=["barcode"], barcode_targets=targets)
    result = Vision(locator="opencv").inspect_frame(np.zeros((20, 20, 3), dtype=np.uint8), brand, recipe)
    if expected:
        assert result["failures"][0]["code"] == expected
        assert "barcode" not in result["observations"]
    else:
        assert result["failures"] == []
        assert result["observations"]["barcode"] == {"size": "095"}
