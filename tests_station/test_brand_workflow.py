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


def test_barcode_reading_is_switched_off():
    recipe = Recipe(brand_id="b", brand_revision=1, targets={"size": "095"}, channels=["ocr", "barcode"])
    assert recipe.channels == ["ocr"]
    with pytest.raises(ValueError):
        Recipe(brand_id="b", brand_revision=1, targets={"size": "095"}, channels=["barcode"])

@pytest.mark.parametrize("found,lines,expected", [
    (2, {0: ["HUTS6C612N3095", "W279,000"], 1: ["HUTS6C612N3095"]}, []),
    (2, {0: ["HUTS6C612N3095"], 1: ["W279,000"]}, ["OCR_TAG_UNMATCHED"]),
    (1, {0: ["HUTS6C612N3095"]}, ["TAG_COUNT_MISMATCH"]),
    (3, {0: ["HUTS6C612N3095"], 1: ["HUTS6C612N3095"], 2: ["HUTS6C612BK095"]}, ["TAG_COUNT_MISMATCH", "OCR_TAG_UNMATCHED"]),
])
def test_each_tag_or_sticker_needs_one_line_with_the_target(brand, found, lines, expected):
    recipe = Recipe(brand_id="hazzys", brand_revision=1, targets={"style": "HUTS6C612", "color": "N3", "size": "095"},
                    channels=["ocr"], tag_count=2)
    vision = Vision()
    vision.load = lambda: None

    def read(frame, *, diagnostics=None, **kwargs):
        diagnostics["tags"] = [{"roi": [0, 0, 1, 1]}] * found
        reads = [SimpleNamespace(lines=[{"text": t, "confidence": .9, "roi_index": i} for t in texts], barcode=None)
                 for i, texts in lines.items()]
        return SimpleNamespace(reads=reads, ms_ocr=1, error=None)
    vision._auto_read = read
    result = vision.inspect_frame(np.zeros((20, 20, 3), np.uint8), brand, recipe)
    assert [f["code"] for f in result["failures"]] == expected
    assert result["observations"]["ocr"] == ({} if expected else recipe.targets)
    assert result["details"]["tag_count"] == found


def test_rfid_tag_is_registered_with_the_chosen_values(line, monkeypatch):
    epc = "E28011700000020F1A2B3C4D"
    monkeypatch.setattr(line.app.state.bench, "rfid_test", lambda: {"tags": [{"epc": epc.lower()}]})
    targets = {"style": "HUTS6C612", "color": "BK", "size": "100"}
    response = line.client.post("/api/bench/rfid/register", json={"brand_id": "hazzys", "targets": targets})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["epc"] == epc and body["brand"]["decoder"]["kind"] == "lookup"
    assert body["brand"]["decoder"]["records"][epc] == targets
    # A second tag on the antenna is refused instead of guessing which one was meant.
    monkeypatch.setattr(line.app.state.bench, "rfid_test", lambda: {"tags": [{"epc": "AA"}, {"epc": "BB"}]})
    again = line.client.post("/api/bench/rfid/register", json={"brand_id": "hazzys", "targets": targets})
    assert again.status_code == 409 and "한 개만" in again.text
    wrong = line.client.post("/api/bench/rfid/register", json={"brand_id": "hazzys", "targets": {"size": "100"}})
    assert wrong.status_code == 422


def test_tags_of_one_product_match_on_the_brand_prefix(line, monkeypatch):
    from station.rules import decode_epc
    brand = Brand.model_validate(line.app.state.store.brand("hazzys"))
    first, same_product = "1D44D280281B70D75A8DF0000E114D7A", "1D44D280281B70D75A8DF0FFFFFFFFFF"
    assert brand.decoder.prefix_length is None
    with pytest.raises(RuleError):
        decode_epc(brand, same_product)
    brand.decoder.prefix_length = 21
    assert decode_epc(brand, same_product) == {"style": "HUTS6C612", "color": "N3", "size": "095"}
    with pytest.raises(RuleError):
        decode_epc(brand, "1D44D280281B70D75A8DE" + "0" * 11)
    # Registering another tag of the same product replaces the entry instead of adding one.
    saved = line.app.state.store.save_brand(brand.model_dump(), brand.revision, "test")
    monkeypatch.setattr(line.app.state.bench, "rfid_test", lambda: {"tags": [{"epc": same_product}]})
    targets = {"style": "HUTS6C612", "color": "BK", "size": "100"}
    body = line.client.post("/api/bench/rfid/register", json={"brand_id": "hazzys", "targets": targets}).json()
    assert body["replaced"] == {"style": "HUTS6C612", "color": "N3", "size": "095"}
    assert body["brand"]["decoder"]["records"] == {same_product: targets}
    assert body["brand"]["decoder"]["prefix_length"] == 21 and saved["revision"] < body["brand"]["revision"]
