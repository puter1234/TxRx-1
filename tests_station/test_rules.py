import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from station.rules import (
    decode_hazzys,
    crc8,
    RuleError,
    judge,
    validate_recipe,
    decode_epc,
)
from station.schema import Brand, Recipe, Option


def test_every_supplied_hazzys_row():
    p = Path(__file__).resolve().parents[1] / "reference/hazzys_rfid_analysis.json"
    if not p.exists():
        pytest.skip("User reference dataset is distributed locally, not via Git.")
    rows = json.loads(p.read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 127
    for row in rows:
        assert decode_hazzys(row["rfid"]) == {
            k: row[k] for k in ("style", "color", "size")
        }


@pytest.mark.parametrize(
    "epc", ["", "AA", "ZZ" * 16, "1D44D280281B70D75A8DF0000E114D00"]
)
def test_invalid_epc_never_passes(epc):
    with pytest.raises(RuleError):
        decode_hazzys(epc)


def test_unknown_character_even_with_valid_crc():
    data = bytearray.fromhex("1D44D280281B70D75A8DF0000E114D7A")
    data[0] = 0xFF
    data[-1] = crc8(data[:-1])
    with pytest.raises(RuleError, match="CHAR_UNSUPPORTED"):
        decode_hazzys(data.hex())


def test_missing_or_conflicting_any_required_channel(recipe):
    recipe.channels = ["ocr", "rfid"]
    assert len(judge(recipe, {"rfid": recipe.targets})) == 3
    result = judge(
        recipe, {"rfid": recipe.targets, "ocr": {**recipe.targets, "size": "105"}}
    )
    assert result[0]["code"] == "TARGET_MISMATCH"


def test_optional_barcode_is_not_required(recipe):
    assert judge(recipe, {"rfid": recipe.targets}) == []
    recipe.channels.append("barcode")
    assert len(judge(recipe, {"rfid": recipe.targets})) == 3


def test_no_fuzzy_substitution(recipe):
    assert judge(recipe, {"rfid": {**recipe.targets, "size": "O95"}})


def test_other_maker_lookup(brand):
    brand.decoder.kind = "lookup"
    brand.decoder.records = {"AABB": {"color": "N3"}}
    assert decode_epc(brand, "aabb") == {"color": "N3"}
    with pytest.raises(RuleError, match="UNREGISTERED"):
        decode_epc(brand, "1122")


def test_deleted_and_stale_options_rejected(brand, recipe):
    brand.revision = 2
    with pytest.raises(RuleError):
        validate_recipe(recipe, brand)
    brand.revision = 1
    brand.options[-1].values = ["100"]
    with pytest.raises(RuleError):
        validate_recipe(recipe, brand)


def test_custom_field_not_invented_for_hazzys(brand, recipe):
    brand.options.append(Option(key="serial", label="serial", values=["01"]))
    brand = Brand.model_validate(brand.model_dump())
    recipe.targets["serial"] = "01"
    with pytest.raises(RuleError):
        validate_recipe(recipe, brand)


def test_invalid_region_and_duplicate_options(brand):
    b = brand.model_dump()
    b["ocr_regions"] = [{"field": "size", "box": [0.9, 0, 0.5, 1]}]
    with pytest.raises(ValidationError):
        Brand.model_validate(b)


def test_every_configured_option_must_have_a_target(brand, recipe):
    del recipe.targets["color"]
    with pytest.raises(RuleError, match="모든 옵션"):
        validate_recipe(recipe, brand)
    b = brand.model_dump()
    b["options"].append(b["options"][0])
    with pytest.raises(ValidationError):
        Brand.model_validate(b)
