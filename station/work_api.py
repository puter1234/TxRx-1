from __future__ import annotations
from datetime import date
from fastapi import Request
from fastapi.responses import Response
from pydantic import Field
from .schema import Model, WorkPreset, Recipe, FlowSettings
from typing import Literal
from .controller import Conflict
from .storage import dump
from .statistics import report, csv_bytes


class PresetSave(Model):
    preset: WorkPreset
    expected_revision: int | None = None


class SpeedWiring(Model):
    speed_line: int = Field(ge=0, le=1023)


class WorkStart(Model):
    preset_revision: int = Field(ge=1)
    brand_revision: int = Field(default=1, ge=1)
    targets: dict[str, str] = Field(default_factory=dict, max_length=30)
    target_count: int | None = Field(default=None, ge=1, le=1000000)
    test_run: bool = False
    channels: list[Literal["ocr", "rfid", "barcode"]] | None = None
    barcode_targets: list[Literal["tag", "poly"]] | None = None


def prepare_session(controller, vision, monitor, recipe, actor):
    # All creation routes must check ownership before touching the active model.
    with controller.lock:
        if controller.session and controller.session["phase"] not in ("DONE", "FINISHED", "ABORTED"):
            raise Conflict("현재 작업을 종료하세요.")
        if controller.busy or controller.external_busy():
            raise Conflict("진행 중인 장비 시험을 종료하세요.")
        recipe = controller.resolve_recipe(recipe)
        if controller.config.mode == "HARDWARE" and recipe.default_flow and recipe.flow is None:
            recipe = recipe.model_copy(update={"flow": FlowSettings()})
        try:
            if "ocr" in recipe.channels:
                vision.load()
            if set(recipe.channels) & {"ocr", "barcode"} and hasattr(vision, "prepare_locator"):
                vision.prepare_locator()
                if monitor and monitor.camera:
                    vision.prepare_capture(monitor.camera.status())
        except (ImportError, OSError, RuntimeError) as exc:
            # A missing model or package is an installation problem; nothing is stopped or faulted.
            raise Conflict("검사 모델을 확인하세요.") from exc
        if monitor and recipe.flow:
            monitor.prepare(recipe.model_dump())
        result = controller.new_session(recipe, actor)
        if monitor and recipe.flow and monitor.counter:
            controller.session["model_identity"] = monitor.counter.identity
            controller.changed("MODEL_SELECTED", monitor.counter.identity)
            result = controller.snapshot()
        return result


def install_work_api(app, controller, permitted, vision, monitor):
    store = controller.store
    if store.get("work_presets") is None:
        store.put("work_presets", {"simple": WorkPreset(id="simple", name="단순 계수").model_dump()})

    @app.get("/api/speed-wiring")
    def wiring():
        return {"active": controller.config.speed_line, "saved": store.get("speed_line", controller.config.speed_line)}

    @app.put("/api/speed-wiring")
    def save_wiring(body: SpeedWiring, request: Request):
        actor = permitted(request, ("admin",))
        from .schema import StationConfig
        StationConfig.model_validate({**controller.config.model_dump(), "speed_line": body.speed_line})
        store.put("speed_line", body.speed_line)
        store.event("SPEED_WIRING_SAVED", {"line": body.speed_line, "actor": actor})
        return wiring()

    @app.get("/api/presets")
    def presets():
        return list(store.get("work_presets", {}).values())

    @app.post("/api/presets")
    def save(body: PresetSave, request: Request):
        actor = permitted(request, ("admin",))
        p = body.preset
        with controller.lock, store.transaction() as c:
            existing = store.get("work_presets", {})
            old = existing.get(p.id)
            if (old or {}).get("revision") != body.expected_revision:
                raise Conflict("작업 설정이 변경되었습니다. 다시 불러오세요.")
            if p.brand_id != "__simple__":
                store.brand(p.brand_id)
            saved = {**p.model_dump(), "revision": (old or {}).get("revision", 0) + 1}
            existing[p.id] = saved
            c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("work_presets", dump(existing)))
            store.event("PRESET_SAVED", {"actor": actor, "before": old, "after": saved}, c)
        return saved

    @app.post("/api/presets/{ident}/start")
    def start(ident: str, body: WorkStart, request: Request):
        actor = permitted(request, ("admin",) if body.test_run else ("admin", "operator"))
        raw = store.get("work_presets", {}).get(ident)
        if not raw:
            raise ValueError("작업 프리셋이 없습니다.")
        preset = WorkPreset.model_validate(raw)
        if preset.revision != body.preset_revision or not preset.enabled:
            raise Conflict("작업 설정이 변경되었습니다. 다시 선택하세요.")
        recipe = Recipe(kind=preset.kind, brand_id=preset.brand_id, brand_revision=body.brand_revision,
                        channels=preset.channels if body.channels is None else body.channels,
                        barcode_targets=preset.barcode_targets if body.barcode_targets is None else body.barcode_targets,
                        targets=body.targets, target_count=body.target_count,
                        preset_id=preset.id, preset_revision=preset.revision, flow=preset.flow,
                        work_name=preset.name, test_run=body.test_run)
        return prepare_session(controller, vision, monitor, recipe, actor)

    @app.get("/api/statistics")
    def statistics(since: date, until: date, include_tests: bool = False, brand_id: str | None = None, preset_id: str | None = None):
        return report(store, since, until, include_tests, brand_id, preset_id)

    @app.get("/api/statistics.csv")
    def export(since: date, until: date, kind: str = "jobs", include_tests: bool = False, brand_id: str | None = None, preset_id: str | None = None):
        if kind not in ("jobs", "daily", "inspections"):
            raise ValueError("작업별, 일자별, 검사별 중 하나를 선택하세요.")
        rows = report(store, since, until, include_tests, brand_id, preset_id)[kind]
        return Response(csv_bytes(rows), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="{kind}-{since}-{until}.csv"'})
