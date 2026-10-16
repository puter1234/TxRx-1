import { useEffect, useState } from "react";
import { useNavigate, useSearchParams, useLocation } from "react-router-dom";
import { api, PHASE, ERR, type Snapshot } from "../station/shared";
import { useApp } from "../lib/store";
import {
  acceptSnapshot,
  ended,
  reportError,
  sendCommand,
} from "../lib/station";
import { CameraView } from "../components/DeviceTests";
import type { Preset } from "../components/WorkPresets";

export default function Work() {
  const restored = useLocation().state;
  const nav = useNavigate(),
    [params] = useSearchParams();
  const state = useApp((s) => s.snapshot),
    brands = useApp((s) => s.brands),
    equipment = useApp((s) => s.equipment);
  const [presets, setPresets] = useState<Preset[]>([]),
    [selected, setSelected] = useState<string>(params.get("preset") || restored?.presetId || "");
  const [targets, setTargets] = useState<Record<string, string>>(restored?.targets || {}),
    [target, setTarget] = useState(restored?.target ? String(restored.target) : "");
  const [adjustment, setAdjustment] = useState(0);
  const [busy, setBusy] = useState(false),
    [reason, setReason] = useState("");
  const session = state?.session,
    active = !ended(session),
    preset = presets.find((p) => p.id === selected);
  const brand = brands.find((b) => b.id === preset?.brand_id)?.source;
  const test = params.get("test") === "1";
  useEffect(() => {
    api<Preset[]>("/presets")
      .then((r) => {
        const rows = r.filter((p) => p.enabled);
        setPresets(rows);
        setSelected((id) => id || rows[0]?.id || "");
      })
      .catch(reportError);
  }, []);
  const command = async (name: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await sendCommand(name, reason);
      setReason("");
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  const flow = session?.recipe.flow;
  return (
    <div className="mx-auto flex min-h-full max-w-[1500px] flex-col gap-5 p-6">
      <header className="flex items-center gap-3">
        <h1 className="mr-auto text-3xl font-bold">
          {active
            ? session?.recipe.work_name || session?.brand.name
            : test
              ? "작업 시험"
              : "작업 선택"}
        </h1>
        <button className="btn btn-outline" onClick={() => nav("/history")}>
          작업 기록
        </button>
        <button className="btn btn-outline" onClick={() => nav("/equipment")}>
          장비 테스트
        </button>
        <button
          className="btn btn-outline"
          onClick={() => nav("/settings?tab=presets")}
        >
          설정
        </button>
      </header>
      {active && session ? (
        <>
          <div className="grid grid-cols-[1fr_1fr] gap-5">
            <section className="card space-y-5 p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-2xl font-bold">
                  {PHASE[session.phase] || session.phase}
                </h2>
                {session.recipe.test_run && (
                  <span className="rounded border border-line px-3 py-1 font-bold">
                    시험 작업
                  </span>
                )}
              </div>
              <div className="flex items-end gap-3">
                <strong className="text-8xl tabular-nums">
                  {session.count}
                </strong>
                <span className="pb-2 text-2xl">
                  개
                  {session.recipe.target_count &&
                    ` / ${session.recipe.target_count}개`}
                </span>
              </div>
              <p className="text-xl">
                합격 {session.passed}개, 불합격 {session.failed}개
              </p>
              <p>브랜드: {session.recipe.brand_id === "__simple__" ? "없음" : session.brand.name}</p>
              {Object.entries(session.recipe.targets).map(([key, value]) => (
                <p key={key}>
                  {session.brand.options.find((o) => o.key === key)?.label ||
                    key}
                  : <strong>{value}</strong>
                </p>
              ))}
              {flow?.counter !== "sensor" && flow && (
                <p className="break-all">
                  모델: {flow.counter === "cvzone" ? "CVZone" : flow.model_path}
                </p>
              )}
              {session.fault && (
                <p role="alert" className="text-xl font-bold text-danger">
                  {ERR[session.fault] || session.fault}
                </p>
              )}
              {session.phase === "CAMERA_WAIT" && (
                <p>
                  카메라 연결을 {flow?.reconnect_interval_ms}ms 간격으로 다시
                  확인합니다.
                </p>
              )}
              {state?.mode === "REPLAY" && <p>사진 시험 모드에서는 장비를 운전하지 않습니다.</p>}
          <div className="grid grid-cols-2 gap-3">
                <button
                  className="btn btn-primary btn-lg"
                  disabled={busy || !state?.can_start || state?.mode !== "HARDWARE"}
                  onClick={() => command("start")}
                >
                  운전 시작
                </button>
                <button
                  className="btn btn-danger btn-lg"
                  disabled={busy}
                  onClick={() => command("stop")}
                >
                  정지
                </button>
              </div>
              {!!state?.blockers?.length &&
                ["READY", "PAUSED"].includes(session.phase) && (
                  <div className="space-y-1">
                    {state.blockers.map((b) => (
                      <p key={b} className="text-danger">
                        {b}
                      </p>
                    ))}
                  </div>
                )}
            </section>
            <section className="card space-y-4 p-5">
              <h2 className="text-xl font-bold">현재 상태</h2>
              {flow &&
              flow.counter === "sensor" &&
              !session.recipe.channels.some(
                (c) => c === "ocr" || c === "barcode",
              ) ? (
                <div className="rounded border border-line p-5 text-xl">
                  센서로 계수합니다.
                </div>
              ) : (
                <CameraView
                  connected={equipment?.camera?.connected === true}
                  tracking={state?.tracking}
                  flow={flow || undefined}
                />
              )}
              <div className="grid grid-cols-3 gap-3 text-lg">
                {[0, 1].map((i) => (
                  <div className="rounded border border-line p-3" key={i}>
                    DI{i + 1}
                    <strong className="block">
                      {Array.isArray(state?.io.di_raw)
                        ? state.io.di_raw[i] === 0
                          ? "감지"
                          : "대기"
                        : "미연결"}
                    </strong>
                  </div>
                ))}
                <div className="rounded border border-line p-3">
                  속도
                  <strong className="block">
                    {state?.io.speed_requested ? "고속" : "저속"}
                  </strong>
                </div>
              </div>
              {state?.last_result && (
                <p className="text-lg font-bold">
                  최근 결과:{" "}
                  {state.last_result.status === "PASS"
                    ? "합격"
                    : state.last_result.failures
                        .map((f) => ERR[f.code] || f.code)
                        .join(", ")}
                </p>
              )}
            </section>
          </div>
          <section className="card flex flex-wrap items-end gap-3 p-5">
            <label className="min-w-80 flex-1 font-bold">
              조치 내용
              <input
                className="field mt-1"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="제품 제거, 연결 확인 등"
              />
            </label>
            {["HOLD", "FAULT", "PAUSED"].includes(session.phase) && (
              <>
                <button
                  className="btn btn-outline"
                  disabled={busy || reason.trim().length < 3}
                  onClick={() => command("discard")}
                >
                  제품 제거 완료
                </button>
                <button
                  className="btn btn-outline"
                  disabled={busy || reason.trim().length < 3}
                  onClick={() => command("reset")}
                >
                  오류 해제
                </button>
              </>
            )}
            {["READY", "PAUSED", "HOLD", "FAULT"].includes(session.phase) && <details className="w-full"><summary className="cursor-pointer font-bold">수량 보정</summary><div className="mt-3 flex items-end gap-3"><label className="font-bold">더하거나 뺄 수량<input type="number" min={-10000} max={10000} className="field" value={adjustment} onChange={e => setAdjustment(Number(e.target.value))}/></label><button className="btn btn-outline" disabled={busy || !adjustment || reason.trim().length < 3} onClick={async () => {setBusy(true); try {await sendCommand("adjust", reason, adjustment); setAdjustment(0); setReason("");} catch(e) {reportError(e);} finally {setBusy(false);}}}>보정 적용</button></div></details>}
            <button
              className="btn btn-outline"
              disabled={busy}
              onClick={() => command("finish")}
            >
              작업 종료
            </button>
          </section>
        </>
      ) : (
        <>
          {session?.phase === "DONE" && (
            <p role="status" className="card p-5 text-2xl font-bold">
              목표 수량 {session.count}개를 완료했습니다.
            </p>
          )}
          <div className="grid grid-cols-[320px_1fr] gap-5">
            <section className="card space-y-3 p-5">
              <h2 className="text-xl font-bold">등록된 작업</h2>
              {presets.map((p) => (
                <button
                  className={
                    "btn w-full " +
                    (p.id === selected ? "btn-primary" : "btn-outline")
                  }
                  key={p.id}
                  onClick={() => {
                    setSelected(p.id);
                    setTargets({});
                  }}
                >
                  {p.name}
                </button>
              ))}
              {!presets.length && <p>설정에서 작업을 등록하세요.</p>}
            </section>
            {preset && (
              <section className="card space-y-5 p-6">
                <h2 className="text-2xl font-bold">{preset.name}</h2>
                <p>브랜드: {brand?.name || "없음"}</p>
                {preset.kind === "vision" && (
                  <p className="break-all">
                    모델:{" "}
                    {preset.flow.counter === "cvzone"
                      ? "CVZone"
                      : preset.flow.model_path}
                  </p>
                )}
                {brand?.options.map((option) => (
                  <fieldset className="space-y-2" key={option.key}>
                    <legend className="text-xl font-bold">
                      {option.label}
                    </legend>
                    <div className="flex flex-wrap gap-3">
                      {option.values.map((v) => (
                        <button
                          className={
                            "btn " +
                            (targets[option.key] === v
                              ? "btn-primary"
                              : "btn-outline")
                          }
                          key={v}
                          aria-pressed={targets[option.key] === v}
                          onClick={() =>
                            setTargets((t) => ({ ...t, [option.key]: v }))
                          }
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                ))}
                <label className="block max-w-sm text-lg font-bold">
                  목표 수량 (비우면 계속 계수)
                  <input
                    className="field mt-2"
                    type="number"
                    min={1}
                    max={1000000}
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                  />
                </label>
                {test && <p>시험 수량은 생산 통계에서 제외됩니다.</p>}
                <button
                  className="btn btn-primary btn-lg"
                  disabled={
                    busy ||
                    !!brand?.options.some((o) => !o.values.includes(targets[o.key])) ||
                    (!!target &&
                      (!Number.isInteger(Number(target)) || Number(target) < 1))
                  }
                  onClick={async () => {
                    setBusy(true);
                    try {
                      acceptSnapshot(
                        await api<Snapshot>(`/presets/${preset.id}/start`, {
                          preset_revision: preset.revision,
                          brand_revision: brand?.revision || 1,
                          targets,
                          target_count: target ? Number(target) : null,
                          test_run: test,
                        }),
                      );
                    } catch (e) {
                      reportError(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {test ? "시험 준비" : "작업 준비"}
                </button>
              </section>
            )}
          </div>
        </>
      )}
    </div>
  );
}
