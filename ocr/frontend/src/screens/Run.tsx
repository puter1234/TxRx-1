import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Minus, Play, Plus, Flag, RotateCcw, PackageX, Camera } from "lucide-react";
import { useApp } from "../lib/store";
import { refresh, reportError, sendCommand } from "../lib/station";
import { api, errorText, uuid } from "../station/shared";
import { optionColorStyle } from "../lib/optionColors";
import { cameraOn, jobTitle, needsCamera, phaseView, presetLabel, RUNNING, TONE_BAR, useRedo } from "../lib/jobs";
import { Screen, Sheet } from "../ui/kit";
import CameraBox, { CameraOnButton } from "../ui/CameraBox";
import StopButton from "../ui/StopButton";

const ADD_REASONS = ["놓친 제품", "수량 확인"];
const SUBTRACT_REASONS = ["중복 계수", "불량 제외", "수량 확인"];
const FINISH_REASONS = ["작업 완료", "작업 중단"];

function elapsed(from: string) {
  const sec = Math.max(0, Math.floor((Date.now() - new Date(from).getTime()) / 1000));
  return [Math.floor(sec / 3600), Math.floor(sec / 60) % 60, sec % 60].map((n) => String(n).padStart(2, "0")).join(":");
}

export default function Run() {
  const nav = useNavigate();
  const state = useApp((s) => s.snapshot);
  const equipment = useApp((s) => s.equipment);
  const online = useApp((s) => s.connected);
  const pending = useApp((s) => s.pending);
  const redo = useRedo();
  const [sheet, setSheet] = useState<"adjust" | "finish" | null>(null);
  const [delta, setDelta] = useState(1);
  const [busy, setBusy] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const s = state?.session;
  // A job that reached its target (DONE) stays on screen with its final count.
  if (!s || s.phase === "FINISHED" || s.phase === "ABORTED")
    return (
      <Screen title="작업" onBack={() => nav("/")}>
        <div className="flex h-full flex-col items-center justify-center gap-8">
          <p className="text-[48px] font-black">진행 중인 작업 없음</p>
          <button className="btn btn-primary btn-xl" onClick={() => nav("/")}>처음으로</button>
        </div>
      </Screen>
    );

  const phase = s.phase;
  const done = phase === "DONE";
  const view = phaseView(phase);
  const running = RUNNING.includes(phase);
  const target = s.recipe.target_count;
  const kind = s.recipe.kind || "condition";
  const cameraNeeded = needsCamera(kind, s.recipe.channels) && state?.mode === "HARDWARE";
  const showCamera = cameraNeeded;
  const failures = phase === "HOLD" ? state?.last_result?.failures ?? [] : [];
  const blockers = ["READY", "PAUSED"].includes(phase) ? state?.blockers ?? [] : [];
  const cameraBlocked = blockers.some((b) => b.includes("카메라")) || (cameraNeeded && !cameraOn(equipment));
  const adjustable = online && ["READY", "PAUSED"].includes(phase) && !state?.busy && !pending.includes("adjust");
  const label = presetLabel(s.recipe.work_name);

  const run = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  const command = (name: string, reason = "") => run(() => sendCommand(name, reason));
  const changeConditions = () =>
    run(async () => {
      await sendCommand("finish", "검사 조건 변경으로 작업 종료");
      redo(s, s.recipe.test_run);
    });

  const primary =
    phase === "PASSED" ? (
      <button className="btn btn-go btn-xl min-w-[400px]" disabled={!online || busy || !!state?.busy} onClick={() => command("release")}>
        <Play size={48} strokeWidth={3} />
        {state?.mode === "REPLAY" ? "다음 제품" : "제품 배출"}
      </button>
    ) : (
      <button
        className="btn btn-go btn-xl min-w-[400px]"
        disabled={!online || busy || !!state?.busy || running || !state?.can_start || pending.includes("start") || ["HOLD", "FAULT"].includes(phase)}
        onClick={() => command("start")}
      >
        <Play size={48} strokeWidth={3} />
        {phase === "PAUSED" ? "다시 시작" : "시작"}
      </button>
    );

  const controls = done ? (
    <>
      <button className="btn btn-go btn-xl min-w-[400px]" onClick={() => redo(s, s.recipe.test_run)}>
        <RotateCcw size={44} strokeWidth={3} />
        다시 하기
      </button>
      <button className="btn btn-primary btn-xl ml-auto min-w-[300px]" onClick={() => nav("/")}>
        처음으로
      </button>
    </>
  ) : (
    <>
      {primary}
      <StopButton />
      {kind === "condition" && (
        <button className="btn btn-outline btn-lg" disabled={!online || busy || running || !!state?.busy} onClick={changeConditions}>
          조건 바꾸기
        </button>
      )}
      <button
        className="btn btn-outline btn-xl ml-auto min-w-[300px]"
        disabled={!online || busy || !!state?.busy || running}
        onClick={() => setSheet("finish")}
      >
        <Flag size={44} />
        끝내기
      </button>
    </>
  );

  return (
    <Screen
      title={jobTitle(s)}
      onBack={() => nav("/")}
      right={
        <>
          {label && <span className="rounded-2xl border-2 border-ink-500 px-5 py-3 text-[28px] font-extrabold">{label}</span>}
          {s.recipe.test_run && <span className="rounded-2xl border-2 border-ink-500 px-5 py-3 text-[28px] font-extrabold">시험</span>}
          {kind === "condition" &&
            s.brand.options.map((o) => (
              <span
                key={o.key}
                aria-label={`${o.label} ${s.recipe.targets[o.key]}`}
                className="rounded-2xl border-2 border-ink-700 bg-white px-5 py-3 text-[32px] font-black"
                style={optionColorStyle(o, s.recipe.targets[o.key])}
              >
                {s.recipe.targets[o.key]}
              </span>
            ))}
        </>
      }
      footer={controls}
    >
      <div className="grid h-full gap-8" style={{ gridTemplateColumns: showCamera || state?.mode === "REPLAY" ? "minmax(0,1.25fr) minmax(0,1fr)" : "1fr" }}>
        <section className="flex min-h-0 flex-col gap-6">
          <p role="status" className={"rounded-3xl px-8 py-5 text-[48px] font-black leading-none " + TONE_BAR[view.tone]}>
            {view.label}
          </p>
          {["HOLD", "FAULT"].includes(phase) ? (
            <div role="alert" className="flex flex-1 flex-col gap-6 rounded-3xl border-4 border-danger bg-danger-bg p-8">
              {!!failures.filter((f) => f.field).length && (
                <div className="grid grid-cols-[1fr_1fr_1fr] gap-4 text-center text-[28px] font-extrabold text-ink-700">
                  <span />
                  <span>목표</span>
                  <span>읽음</span>
                </div>
              )}
              {failures.filter((f) => f.field).map((f, i) => {
                const option = s.brand.options.find((o) => o.key === f.field);
                return (
                  <div key={i} className="grid grid-cols-[1fr_1fr_1fr] items-center gap-4 text-[40px] font-black">
                    <span>{option?.label || f.field}</span>
                    <span className="rounded-2xl bg-white px-5 py-3 text-center" style={option ? optionColorStyle(option, f.expected || "") : undefined}>
                      {f.expected || "없음"}
                    </span>
                    <span className="rounded-2xl border-4 border-danger bg-white px-5 py-3 text-center text-danger">
                      {f.actual || "못 읽음"}
                    </span>
                  </div>
                );
              })}
              {failures.filter((f) => !f.field).map((f, i) => (
                <p key={i} className="text-[40px] font-black text-danger">{errorText(f.code)}</p>
              ))}
              {phase === "FAULT" && <p className="text-[40px] font-black text-danger">{errorText(s.fault) || "장비 오류"}</p>}
              <div className="mt-auto flex flex-wrap gap-5">
                <button className="btn btn-primary btn-xl" disabled={!online || busy || !!state?.busy}
                  onClick={() => command("reset", phase === "FAULT" ? "작업자 확인 후 오류 해제" : "작업자 확인 후 재검사")}>
                  <RotateCcw size={44} strokeWidth={3} />
                  {phase === "FAULT" ? "오류 해제" : "다시 검사"}
                </button>
                {s.active_product && (
                  <button className="btn btn-outline btn-xl" disabled={!online || busy || !!state?.busy} onClick={() => command("discard", "불량 제품 제거")}>
                    <PackageX size={44} />
                    제품 뺐음
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="card flex flex-1 flex-col items-center justify-center gap-4 p-8">
              <div className="flex items-end gap-4">
                <span aria-label="현재 수량" className="text-[clamp(160px,15vw,300px)] font-black leading-[0.85] tabular-nums text-ink-900">
                  {s.count}
                </span>
                <span className="pb-4 text-[64px] font-black text-ink-700">{target ? `/ ${target}` : "개"}</span>
              </div>
              {target != null && (
                <div className="w-full max-w-3xl">
                  <div className="h-8 overflow-hidden rounded-full bg-panel ring-2 ring-line">
                    <div className="h-full rounded-full bg-ok transition-all" style={{ width: Math.min(100, (s.count / target) * 100) + "%" }} />
                  </div>
                  <p className="mt-3 text-center text-[40px] font-black">남은 수량 {Math.max(0, target - s.count)}</p>
                </div>
              )}
              {!done && <div className="mt-2 flex items-center gap-6">
                <button aria-label="1개 빼기" className="btn btn-outline btn-lg !min-w-[120px]" disabled={!adjustable}
                  onClick={() => { setDelta(-1); setSheet("adjust"); }}>
                  <Minus size={44} strokeWidth={3} />
                </button>
                <span className="text-[32px] font-extrabold tabular-nums text-ink-700">{elapsed(s.created_at)}</span>
                <button aria-label="1개 더하기" className="btn btn-outline btn-lg !min-w-[120px]" disabled={!adjustable}
                  onClick={() => { setDelta(1); setSheet("adjust"); }}>
                  <Plus size={44} strokeWidth={3} />
                </button>
              </div>}
            </div>
          )}
          {phase === "PAUSED" && s.active_product && s.recipe.flow && state?.mode === "HARDWARE" && (
            <button className="btn btn-outline btn-xl" disabled={!online || busy} onClick={() => command("discard", "이송 중 제품 정리")}>
              <PackageX size={44} />
              제품 뺐음
            </button>
          )}
          {!!blockers.length && (
            <div role="status" className="flex flex-wrap items-center gap-4">
              {[...new Set(blockers.map(errorText))].map((b) => (
                <span key={b} className="rounded-2xl border-2 border-danger bg-danger-bg px-5 py-3 text-[26px] font-extrabold text-danger">{b}</span>
              ))}
              {cameraBlocked && !cameraOn(equipment) && <CameraOnButton />}
            </div>
          )}
        </section>
        {(showCamera || state?.mode === "REPLAY") && (
          <section className="flex min-h-0 flex-col gap-6">
            {showCamera && <CameraBox className="min-h-[360px] flex-1" tracking={kind === "vision" ? state?.tracking : undefined} flow={s.recipe.flow} />}
            {state?.mode === "REPLAY" && kind !== "vision" && <PhotoTest />}
          </section>
        )}
      </div>
      {sheet === "adjust" && (
        <AdjustSheet
          count={s.count}
          delta={delta}
          allowZero={kind !== "condition"}
          busy={busy}
          onClose={() => setSheet(null)}
          onApply={(change, reason) =>
            run(async () => {
              await sendCommand("adjust", reason, change);
              setSheet(null);
            })
          }
        />
      )}
      {sheet === "finish" && (
        <Sheet title="끝내기" onClose={() => !busy && setSheet(null)}>
          <p className="mb-8 text-[56px] font-black tabular-nums">
            {jobTitle(s)} {s.count}개
          </p>
          <div className="grid grid-cols-2 gap-5">
            {FINISH_REASONS.map((reason, i) => (
              <button key={reason} className={"btn btn-xl " + (i === 0 ? "btn-primary" : "btn-outline")} disabled={!online || busy}
                onClick={() =>
                  run(async () => {
                    await sendCommand("finish", reason);
                    setSheet(null);
                    nav("/");
                  })
                }>
                {reason}
              </button>
            ))}
          </div>
        </Sheet>
      )}
    </Screen>
  );
}

function AdjustSheet({
  count,
  delta,
  allowZero,
  busy,
  onClose,
  onApply,
}: {
  count: number;
  delta: number;
  allowZero: boolean;
  busy: boolean;
  onClose: () => void;
  onApply: (change: number, reason: string) => void;
}) {
  const [zero, setZero] = useState(false);
  const change = zero ? -count : delta;
  const reasons = zero ? ["수량 확인"] : delta > 0 ? ADD_REASONS : SUBTRACT_REASONS;
  return (
    <Sheet title="수량 고치기" onClose={() => !busy && onClose()}>
      <p className="mb-8 text-center text-[96px] font-black tabular-nums leading-none">
        {count} <span className="text-ink-500">→</span> {Math.max(0, count + change)}
      </p>
      <div className="grid grid-cols-2 gap-5">
        {reasons.map((reason) => (
          <button key={reason} className="btn btn-primary btn-xl" disabled={busy || count + change < 0} onClick={() => onApply(change, reason)}>
            {reason}
          </button>
        ))}
      </div>
      {allowZero && count > 0 && (
        <button className="btn btn-outline btn-lg mt-8 w-full" aria-pressed={zero} disabled={busy} onClick={() => setZero((v) => !v)}>
          {zero ? "1개씩 고치기" : "0개로"}
        </button>
      )}
    </Sheet>
  );
}

function PhotoTest() {
  const state = useApp((s) => s.snapshot);
  const online = useApp((s) => s.connected);
  const s = state?.session;
  const [file, setFile] = useState<File | null>(null);
  const [epc, setEpc] = useState("");
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(0);
  const [product, setProduct] = useState(() => s?.active_product || uuid());
  useEffect(() => {
    setProduct(s?.active_product || uuid());
    if (!s?.active_product) {
      setFile(null);
      setKey((k) => k + 1);
      setEpc("");
    }
  }, [s?.id, s?.active_product]);
  if (!s) return null;
  const needsPhoto = s.recipe.kind === "simple" || s.recipe.channels.some((c) => c === "ocr" || c === "barcode");
  const needsEpc = s.recipe.channels.includes("rfid");
  const evidence = state?.last_result?.evidence?.url;
  const inspect = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.set("product_id", product);
      form.set("epcs", epc);
      if (file) form.set("image", file);
      await api("/replay", form);
      await refresh();
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-label="사진 검사" className="card flex min-h-0 flex-1 flex-col gap-5 p-6">
      <div className="flex min-h-[240px] flex-1 items-center justify-center overflow-hidden rounded-2xl bg-ink-900">
        {evidence ? <img src={evidence} alt="최근 검사 사진" className="h-full w-full object-contain" /> : <Camera size={96} className="text-white/40" aria-hidden="true" />}
      </div>
      {needsPhoto && (
        <label className="btn btn-outline btn-lg w-full cursor-pointer">
          {file ? file.name : "사진 고르기"}
          <input key={key} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" disabled={busy || !!state?.busy}
            onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
      )}
      {needsEpc && (
        <label className="block text-[28px] font-extrabold">
          RFID
          <textarea value={epc} disabled={busy || !!state?.busy} onChange={(e) => setEpc(e.target.value)} className="field mt-2 min-h-24 py-3" />
        </label>
      )}
      <button className="btn btn-primary btn-xl w-full" disabled={!online || busy || !!state?.busy || !state?.can_start || s.phase !== "READY" || (needsPhoto && !file)}
        onClick={inspect}>
        {busy ? "검사 중" : "사진 검사"}
      </button>
    </section>
  );
}
