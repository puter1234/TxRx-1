"""Explicit local maker rules. Unknown fields never become matching evidence."""

from .schema import Brand, Recipe

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class RuleError(ValueError):
    pass


def crc8(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (7 if value & 128 else 0)) & 255
    return value


def decode_hazzys(epc: str) -> dict:
    try:
        raw = bytes.fromhex(epc.strip())
    except ValueError as exc:
        raise RuleError("RFID_HEX_INVALID") from exc
    if len(raw) != 16:
        raise RuleError("RFID_LENGTH_INVALID")
    if crc8(raw[:15]) != raw[-1]:
        raise RuleError("RFID_CRC_INVALID")
    bits = "".join(f"{b:08b}" for b in raw)
    chars = []
    for i in range(0, 84, 6):
        n = int(bits[i : i + 6], 2)
        if n >= len(ALPHABET):
            raise RuleError("RFID_CHAR_UNSUPPORTED")
        chars.append(ALPHABET[n])
    return {
        "style": "".join(chars[:9]),
        "color": "".join(chars[9:11]),
        "size": "".join(chars[11:14]),
    }


def decode_epc(brand: Brand, epc: str) -> dict:
    if brand.decoder.kind == "hazzys_6bit_crc8":
        return decode_hazzys(epc)
    if brand.decoder.kind == "lookup":
        value = brand.decoder.records.get(epc.strip().upper())
        if value is None:
            raise RuleError("RFID_UNREGISTERED")
        return dict(value)
    raise RuleError("RFID_RULE_MISSING")


def validate_recipe(recipe: Recipe, brand: Brand, require_regions: bool = True):
    if recipe.brand_revision != brand.revision:
        raise RuleError("설정이 변경되었습니다. 목표 옵션을 다시 선택하세요.")
    choices = {o.key: o.values for o in brand.options}
    if set(recipe.targets) != set(choices):
        raise RuleError("모든 옵션의 목표값을 하나씩 선택하세요.")
    if any(k not in choices or v not in choices[k] for k, v in recipe.targets.items()):
        raise RuleError("등록되지 않은 목표 옵션입니다.")
    if "rfid" in recipe.channels:
        if brand.decoder.kind == "none":
            raise RuleError("이 메이커의 RFID 규칙을 먼저 등록하세요.")
        if brand.decoder.kind == "lookup" and not brand.decoder.records:
            raise RuleError("메이커별 EPC 기준표를 먼저 등록하세요.")
        if brand.decoder.kind == "hazzys_6bit_crc8" and not set(recipe.targets) <= {
            "style",
            "color",
            "size",
        }:
            raise RuleError("헤지스 규칙에서 확인된 필드는 품번·색상·사이즈입니다.")
    # OCR finds printed lines automatically. Legacy region coordinates are not
    # a prerequisite and must not silently replace the established pipeline.
    if "barcode" in recipe.channels and not brand.barcode_records:
        raise RuleError("바코드 기준표를 먼저 등록하세요.")


def judge(recipe: Recipe, observations: dict[str, dict[str, str]]) -> list[dict]:
    failures = []
    for channel in recipe.channels:
        fields = observations.get(channel, {})
        for field, expected in recipe.targets.items():
            actual = fields.get(field)
            # No O/0 substitution, fuzzy comparison, or expected-data imputation.
            if actual is None or actual == "":
                failures.append(
                    {
                        "code": "REQUIRED_FIELD_MISSING",
                        "channel": channel,
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )
            elif actual != expected:
                failures.append(
                    {
                        "code": "TARGET_MISMATCH",
                        "channel": channel,
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )
    return failures
