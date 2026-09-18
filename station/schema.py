from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )


class Option(Model):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=40)
    values: list[str] = Field(min_length=1, max_length=1000)
    display: Literal["buttons", "colors"] | None = None
    colors: dict[str, str] = Field(default_factory=dict, max_length=1000)

    @model_validator(mode="after")
    def distinct(self):
        if any(not v.strip() or len(v) > 100 for v in self.values):
            raise ValueError("옵션 값은 1~100자여야 합니다.")
        self.values = [v.strip() for v in self.values]
        if len(self.values) != len(set(self.values)):
            raise ValueError("옵션 값이 중복됩니다.")
        import re

        if any(code not in self.values for code in self.colors):
            raise ValueError("색상은 등록된 선택값에만 지정할 수 있습니다.")
        if any(
            not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
            for value in self.colors.values()
        ):
            raise ValueError("버튼 색상은 #RRGGBB 형식이어야 합니다.")
        self.colors = {code: value.upper() for code, value in self.colors.items()}
        return self


class Region(Model):
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    # Normalized ROI, same PARSeq/preprocessing. No barcode anchor required.
    box: tuple[float, float, float, float]
    rotation: Literal[0, 90, 180, 270] = 0
    min_char_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def valid_box(self):
        x, y, w, h = self.box
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 or y + h > 1:
            raise ValueError("영역은 이미지 내부의 0~1 좌표여야 합니다.")
        return self


class Decoder(Model):
    kind: Literal["none", "hazzys_6bit_crc8", "lookup"] = "none"
    # Other makers register exact EPC -> fields, never infer their encoding.
    records: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100000)


class Brand(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    name: str = Field(min_length=1, max_length=60)
    revision: int = Field(default=1, ge=1)
    options: list[Option] = Field(default_factory=list, max_length=30)
    decoder: Decoder = Field(default_factory=Decoder)
    ocr_regions: list[Region] = Field(default_factory=list, max_length=30)
    barcode_records: dict[str, dict[str, str]] = Field(
        default_factory=dict, max_length=100000
    )
    note: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def coherent(self):
        keys = [o.key for o in self.options]
        if len(set(keys)) != len(keys):
            raise ValueError("옵션 이름이 중복됩니다.")
        fields = [r.field for r in self.ocr_regions]
        if len(set(fields)) != len(fields) or any(f not in keys for f in fields):
            raise ValueError("OCR 영역은 등록된 옵션마다 최대 한 개입니다.")
        if self.decoder.kind == "lookup":
            clean = {}
            for epc, values in self.decoder.records.items():
                epc = epc.strip().upper()
                import re

                if not re.fullmatch("[0-9A-F]+", epc):
                    raise ValueError("EPC는 공백 없는 HEX 문자열이어야 합니다.")
                if not epc or len(epc) > 128 or len(epc) % 2:
                    raise ValueError("EPC는 짝수 길이 HEX 문자열이어야 합니다.")
                try:
                    bytes.fromhex(epc)
                except ValueError as exc:
                    raise ValueError("EPC HEX 형식 오류") from exc
                if epc in clean:
                    raise ValueError("EPC 중복 매핑")
                clean[epc] = values
            self.decoder.records = clean
        for record in list(self.decoder.records.values()) + list(
            self.barcode_records.values()
        ):
            import re

            if not record or len(record) > 30:
                raise ValueError("기준표 행은 1~30개 필드가 필요합니다.")
            for k, v in record.items():
                if (
                    not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", k)
                    or not v
                    or len(v) > 100
                ):
                    raise ValueError("기준표 필드 이름 또는 값 형식 오류")
            # A maker may decode products outside the currently selectable targets.
            # Keep those observations so mismatches remain explicit.
        return self


class Recipe(Model):
    kind: Literal["condition", "simple"] = "condition"
    brand_id: str
    brand_revision: int = Field(ge=1)
    targets: dict[str, str] = Field(max_length=30)
    channels: list[Literal["ocr", "rfid", "barcode"]] = Field(max_length=3)
    target_count: int | None = Field(default=None, ge=1, le=1000000)

    @model_validator(mode="after")
    def channels_unique(self):
        if self.kind == "condition" and (not self.targets or not self.channels):
            raise ValueError("조건 계수는 목표값과 검사 항목이 필요합니다.")
        if self.kind == "simple" and (
            self.targets or self.channels or self.brand_id != "__simple__"
        ):
            raise ValueError("단순 계수에는 검사 조건을 지정할 수 없습니다.")
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("중복 검사 항목")
        return self


class Command(Model):
    request_id: str = Field(min_length=8, max_length=100)
    session_id: str
    action: Literal["start", "pause", "stop", "reset", "release", "discard", "finish"]
    reason: str = Field(default="", max_length=500)
    expected_revision: int = Field(ge=0)
    issued_at: float | None = None


class Adjustment(Model):
    request_id: str = Field(min_length=8, max_length=100)
    session_id: str
    delta: int = Field(ge=-10000, le=10000)
    reason: str = Field(min_length=3, max_length=500)


class Commissioning(Model):
    # No guessed field measurements. HARDWARE cannot arm with these unset.
    settle_ms: int | None = Field(default=None, ge=10, le=30000)
    inspection_timeout_ms: int | None = Field(default=None, ge=100, le=120000)
    feedback_timeout_ms: int | None = Field(default=None, ge=20, le=10000)
    release_timeout_ms: int | None = Field(default=None, ge=100, le=60000)
    product_sensor: Literal[1, 2] | None = None
    departure_sensor: Literal[1, 2] | None = None
    sensor_clear_ms: int | None = Field(default=None, ge=10, le=1000)
    sensor_active_raw: Literal[0, 1] | None = None
    detector_module: str | None = None
    detector_sha256: str | None = None
    physical_permit_observed: bool = False
    power_cycle_off_verified: bool = False
    process_kill_off_verified: bool = False
    os_hang_off_verified: bool = False
    stop_chain_verified: bool = False
    single_product_verified: bool = False
    camera_calibrated: bool = False
    rfid_protocol_verified: bool = False
    signed_by: str = ""
    evidence_reference: str = ""

    def blockers(self):
        required_values = (
            "settle_ms",
            "inspection_timeout_ms",
            "feedback_timeout_ms",
            "release_timeout_ms",
            "product_sensor",
            "departure_sensor",
            "sensor_clear_ms",
            "sensor_active_raw",
            "detector_module",
            "detector_sha256",
            "signed_by",
            "evidence_reference",
        )
        required_checks = (
            "physical_permit_observed",
            "power_cycle_off_verified",
            "process_kill_off_verified",
            "os_hang_off_verified",
            "stop_chain_verified",
            "single_product_verified",
            "camera_calibrated",
            "rfid_protocol_verified",
        )
        return [
            k
            for k in required_values
            if getattr(self, k) is None or getattr(self, k) == ""
        ] + [k for k in required_checks if not getattr(self, k)]


class StationConfig(Model):
    mode: Literal["REPLAY", "HARDWARE"] = "REPLAY"
    gpio_chip: str = "/dev/gpiochip0"
    di_lines: tuple[int, int, int] = (105, 144, 106)
    do_lines: tuple[int, int] = (51, 52)
    rfid_port: str = ""
    camera_source: str = ""
    camera_width: int | None = Field(default=None, ge=320, le=8000)
    camera_height: int | None = Field(default=None, ge=240, le=6000)
    camera_fps: int | None = Field(default=None, ge=1, le=120)
    rfid_window_ms: int | None = Field(default=None, ge=100, le=10000)
    io_lease_ms: int = Field(default=500, ge=100, le=2000)
    do_on_raw: Literal[0, 1] | None = None
    # Additional verified physical permit observation, never assigned to spare DI4 implicitly.
    permit_line: int | None = Field(default=None, ge=0)
    permit_active_raw: Literal[0, 1] | None = None
    disk_min_free_mb: int = Field(default=1024, ge=100)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    commissioning: Commissioning = Field(default_factory=Commissioning)
    automatic_cycle: bool = True
