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


class BrandCaps(Model):
    rfid: bool = False
    ocr: bool = True
    barcode_tag: bool = False
    barcode_poly: bool = False


class Brand(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    name: str = Field(min_length=1, max_length=60)
    revision: int = Field(default=1, ge=1)
    caps: BrandCaps | None = None
    options: list[Option] = Field(default_factory=list, max_length=30)
    decoder: Decoder = Field(default_factory=Decoder)
    ocr_regions: list[Region] = Field(default_factory=list, max_length=30)
    barcode_records: dict[str, dict[str, str]] = Field(
        default_factory=dict, max_length=100000
    )
    barcode_poly_records: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100000)
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
        ) + list(
            self.barcode_poly_records.values()
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


class FlowSettings(Model):
    low_speed_ms: int = Field(default=500, ge=0, le=60000)
    capture_delay_ms: int = Field(default=100, ge=0, le=60000)
    capture_count: int = Field(default=1, ge=1, le=30)
    capture_interval_ms: int = Field(default=100, ge=0, le=10000)
    rfid_delay_ms: int = Field(default=100, ge=0, le=60000)
    result_timeout_ms: int = Field(default=5000, ge=100, le=120000)
    departure_timeout_ms: int = Field(default=10000, ge=100, le=120000)
    reconnect_interval_ms: int = Field(default=2000, ge=100, le=60000)
    di1_debounce_ms: int = Field(default=20, ge=0, le=1000)
    di2_debounce_ms: int = Field(default=20, ge=0, le=1000)
    counter: Literal["sensor", "cvzone", "yolo"] = "sensor"
    model_path: str = Field(default="", max_length=1000)
    confidence: float = Field(default=0.5, gt=0, le=1)
    classes: list[int] = Field(default_factory=list, max_length=100)
    image_size: int = Field(default=640, ge=32, le=2048)
    threshold: int = Field(default=127, ge=0, le=255)
    invert: bool = False
    min_area: int = Field(default=100, ge=1, le=10000000)
    roi: tuple[float, float, float, float] = (0, 0, 1, 1)
    axis: Literal["x", "y"] = "y"
    direction: Literal[1, -1] = 1
    line: float = Field(default=0.5, gt=0, lt=1)
    hysteresis: float = Field(default=0.02, ge=0, le=0.2)
    match_distance: float = Field(default=0.15, gt=0, le=1)
    track_lost_ms: int = Field(default=500, ge=10, le=10000)

    @model_validator(mode="after")
    def coherent(self):
        x, y, w, h = self.roi
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 or y + h > 1:
            raise ValueError("검출 영역은 영상 안의 0~1 좌표로 지정하세요.")
        if self.capture_delay_ms + (self.capture_count - 1) * self.capture_interval_ms >= self.result_timeout_ms:
            raise ValueError("검사 제한 시간은 마지막 촬영 시간보다 길어야 합니다.")
        if self.rfid_delay_ms >= self.result_timeout_ms:
            raise ValueError("RFID 실행 시간은 검사 제한 시간보다 짧아야 합니다.")
        if self.counter == "yolo" and not self.model_path.lower().endswith((".pt", ".onnx")):
            raise ValueError("YOLO 모델은 로컬 .pt 또는 .onnx 파일을 지정하세요.")
        if any(c < 0 for c in self.classes):
            raise ValueError("클래스 번호는 0 이상입니다.")
        return self


class WorkPreset(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    name: str = Field(min_length=1, max_length=80)
    revision: int = Field(default=1, ge=1)
    enabled: bool = True
    kind: Literal["simple", "condition", "vision"] = "simple"
    brand_id: str = "__simple__"
    channels: list[Literal["ocr", "rfid", "barcode"]] = Field(default_factory=list, max_length=3)
    barcode_targets: list[Literal["tag", "poly"]] = Field(default_factory=lambda: ["tag"], max_length=2)
    flow: FlowSettings = Field(default_factory=FlowSettings)

    @model_validator(mode="after")
    def coherent(self):
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("검사 항목이 중복됩니다.")
        if "barcode" in self.channels and (not self.barcode_targets or len(self.barcode_targets) != len(set(self.barcode_targets))):
            raise ValueError("바코드 검사 대상을 선택하세요.")
        if self.kind == "simple" and (self.channels or self.flow.counter != "sensor" or self.brand_id != "__simple__"):
            raise ValueError("단순 계수는 센서만 사용합니다.")
        if self.kind == "condition" and (not self.channels or self.brand_id == "__simple__"):
            raise ValueError("조건 검사의 브랜드와 검사 항목을 지정하세요.")
        if self.kind == "vision" and (self.flow.counter == "sensor" or self.channels):
            raise ValueError("와펜 계수는 CVZone 또는 YOLO를 사용합니다.")
        return self


class Recipe(Model):
    kind: Literal["condition", "simple", "vision"] = "condition"
    brand_id: str
    brand_revision: int = Field(ge=1)
    targets: dict[str, str] = Field(max_length=30)
    channels: list[Literal["ocr", "rfid", "barcode"]] = Field(max_length=3)
    barcode_targets: list[Literal["tag", "poly"]] = Field(default_factory=lambda: ["tag"], max_length=2)
    target_count: int | None = Field(default=None, ge=1, le=1000000)
    preset_id: str | None = None
    preset_revision: int | None = None
    flow: FlowSettings | None = None
    default_flow: bool = False
    work_name: str = ""
    test_run: bool = False

    @model_validator(mode="after")
    def channels_unique(self):
        if self.kind == "condition" and (not self.targets or not self.channels):
            raise ValueError("조건 계수는 목표값과 검사 항목이 필요합니다.")
        if self.kind == "simple" and (
            self.targets or self.channels or self.brand_id != "__simple__"
        ):
            raise ValueError("단순 계수에는 검사 조건을 지정할 수 없습니다.")
        if self.kind == "vision" and (self.channels or self.flow is None or self.flow.counter == "sensor"):
            raise ValueError("와펜 계수 방법을 지정하세요.")
        if self.kind == "simple" and self.flow and self.flow.counter != "sensor":
            raise ValueError("단순 계수는 센서만 사용합니다.")
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("중복 검사 항목")
        if "barcode" in self.channels and (not self.barcode_targets or len(set(self.barcode_targets)) != len(self.barcode_targets)):
            raise ValueError("바코드 검사 대상을 선택하세요.")
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
    speed_line: int | None = Field(
        default=None, ge=0, le=1023,
        description="미지정 시 J4012 JetPack 6 기본 배선의 DO4(PH.07, offset 50)를 사용합니다.",
    )
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

    @model_validator(mode="after")
    def unique_pins(self):
        # Seeed J40/J30: DO4 is PH.07, gpiochip0 offset 50 on JetPack 6.
        # Resolve old null/omitted values only for the documented board wiring.
        # Explicit overrides remain valid for installations with custom wiring.
        if (self.speed_line is None and self.gpio_chip == "/dev/gpiochip0"
                and self.di_lines == (105, 144, 106) and self.do_lines == (51, 52)):
            self.speed_line = 50
        pins = [*self.di_lines, *self.do_lines]
        pins += [v for v in (self.speed_line, self.permit_line) if v is not None]
        if len(pins) != len(set(pins)):
            raise ValueError("입출력 핀을 중복 지정할 수 없습니다.")
        return self
