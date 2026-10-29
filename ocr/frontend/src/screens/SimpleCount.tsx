import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Clock, Timer } from "lucide-react";
import { useApp } from "../lib/store";
import VideoPanel from "../components/VideoPanel";
import JudgeLog from "../components/JudgeLog";
import StatusBanner from "../components/StatusBanner";
import ControlBar from "../components/ControlBar";
import { ended, runPath } from "../lib/station";
import { usePresets } from "../lib/presets";
import OptionButtons from "../components/OptionButtons";

function useElapsed(startedAt: string | null, ticking: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!ticking) return;
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, [ticking]);
  if (!startedAt) return "00:00:00";
  const sec = Math.max(
    0,
    Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000),
  );
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    p(Math.floor(sec / 3600)) +
    ":" +
    p(Math.floor((sec % 3600) / 60)) +
    ":" +
    p(sec % 60)
  );
}

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between py-3.5">
      <span className="flex items-center gap-2.5 text-lg font-bold text-ink-700">
        <Icon size={22} className="text-brand-600" /> {label}
      </span>
      <span className="text-xl font-extrabold tabular-nums">{value}</span>
    </div>
  );
}

export default function SimpleCount({ mode = "simple" }: { mode?: "simple" | "vision" }) {
  const nav = useNavigate();
  const restored = useLocation().state;
  const [params] = useSearchParams();
  const presets = usePresets(mode);
  const [selected, setSelected] = useState(params.get("preset") || restored?.presetId || "");
  const [target, setTarget] = useState(restored?.target ? String(restored.target) : "");
  const [targets, setTargets] = useState<Record<string, string>>(restored?.targets || {});
  const snapshot = useApp((s) => s.snapshot);
  const brands = useApp((s) => s.brands);
  const preset = presets.rows.find((p) => p.id === selected);
  const brand = brands.find((b) => b.id === preset?.brand_id)?.source;
  const testRun = params.get("test") === "1" || restored?.testRun === true;
  useEffect(() => {
    if (!selected && presets.rows.length) setSelected(presets.rows[0].id);
  }, [presets.rows, selected]);
  const session = useApp((s) => s.server?.session);
  const activeSession = useApp((s) => s.snapshot?.session);
  const count = session?.mode === mode ? session.count : 0;
  const elapsed = useElapsed(
    session?.startedAt ?? null,
    session?.status === "running",
  );
  const active = !ended(activeSession);
  const usePreset = !!preset;
  const createReady = !presets.loading && !presets.error && (!selected || !!preset) && (mode !== "vision" || !!preset) && (!target || (Number.isInteger(Number(target)) && Number(target) >= 1 && Number(target) <= 1000000))
    && (!brand || brand.options.every((o) => o.values.includes(targets[o.key])));
  if (active && activeSession?.recipe.kind !== mode)
    return (
      <div className="flex h-full flex-col items-center justify-center gap-5">
        <p className="text-2xl font-bold">다른 작업이 진행 중입니다.</p>
        <button
          className="btn btn-primary"
          onClick={() => nav(runPath(activeSession?.recipe.kind))}
        >
          진행 중인 작업 열기
        </button>
      </div>
    );

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav("/")}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">{mode === "vision" ? "와펜 계수" : "단순 계수"}</h1>
        {(testRun || (active && activeSession?.recipe.test_run)) && <span className="rounded border border-line px-3 py-1 font-bold">시험 작업</span>}
        <button className="btn btn-outline btn-sm ml-auto" onClick={() => nav("/equipment")}>장비 점검</button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1.25fr_1fr] gap-5 p-6">
        <div className="flex min-h-0 flex-col gap-5 overflow-y-auto">
          <VideoPanel />
          <JudgeLog />
        </div>

        <div className="flex min-h-0 flex-col gap-5 overflow-y-auto">
          {!active && (
            <section className="card space-y-3 p-5">
              {presets.error && <p role="alert">{presets.error} <button className="btn btn-outline btn-sm" onClick={presets.retry}>다시 불러오기</button></p>}
              {(mode === "vision" || presets.rows.length > 1 || (!!selected && !preset)) && <>
                <label className="block text-lg font-bold">작업 설정
                  <select className="field mt-2" value={selected} onChange={(e) => { setSelected(e.target.value); setTargets({}); }} disabled={presets.loading}>
                    <option value="">작업 선택</option>
                    {presets.rows.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}
                  </select>
                </label>

                {!presets.loading && !presets.error && !preset && <p>작업을 선택하세요.</p>}
                {mode === "vision" && preset && <p className="break-all">모델: {preset.flow.counter === "cvzone" ? "CVZone" : preset.flow.model_path}</p>}
              </>}
              {brand?.options.map((option) => <OptionButtons key={option.key} option={option} value={targets[option.key] || ""} onChange={(value) => setTargets((old) => ({...old, [option.key]: value}))}/>)}
              <label className="block text-lg font-bold">목표 수량 (비우면 계속 계수)
                <input className="field mt-2" type="number" min={1} max={1000000} value={target} onChange={(e) => setTarget(e.target.value)}/>
              </label>
            </section>
          )}
          {active && activeSession?.recipe.work_name && <p className="text-lg font-bold">{activeSession.recipe.work_name}</p>}
          <div className="card p-6 text-center">
            <div className="text-lg font-bold text-ink-700">현재 수량</div>
            <div className="flex items-end justify-center gap-3">
              <span className="text-[104px] font-black leading-none tabular-nums text-brand-800">
                {count}
              </span>
              <span className="pb-3 text-3xl font-extrabold text-brand-600">
                개
              </span>
            </div>
            {activeSession?.recipe.target_count != null && session?.mode === mode && <div className="mt-4">
              <progress aria-label="목표 수량 진행률" className="h-4 w-full" value={count} max={activeSession.recipe.target_count}/>
              <p className="text-lg font-bold">목표 {activeSession.recipe.target_count}개, 남은 수량 {Math.max(0, activeSession.recipe.target_count - count)}개</p>
            </div>}
            <div className="mt-5 border-t border-line">
              <div className="divide-y divide-line">
                <InfoRow icon={Timer} label="작업 시간" value={elapsed} />
                <InfoRow
                  icon={Clock}
                  label="최근 통과"
                  value={session?.lastPassAt ?? "없음"}
                />
              </div>
            </div>
          </div>
          <StatusBanner />
        </div>
      </div>

      <ControlBar mode={mode} createReady={createReady} createConfig={{ mode, countMode: target ? "target" : "continuous", target: target ? Number(target) : null,
        presetId: usePreset ? preset?.id : undefined, presetRevision: preset?.revision, brandId: preset?.brand_id,
        targets, testRun }}/>
    </div>
  );
}
