import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Award, Play, Shirt } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended, reportError, startSession } from "../lib/station";
import type { Preset } from "../components/WorkPresets";
import OptionButtons from "../components/OptionButtons";
import { Notice, QuantityPicker, Screen, Tile } from "../ui/kit";
import CameraBox from "../ui/CameraBox";
import StopButton from "../ui/StopButton";

type Item = "simple" | "vision";
export type SimpleRestore = { kind?: Item; presetId?: string; target?: number | null; targets?: Record<string, string> };

export function useEnabledPresets() {
  const [rows, setRows] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api<Preset[]>("/presets")
      .then((items) => { if (alive) setRows(items.filter((p) => p.enabled)); })
      .catch((e) => { if (alive) setError((e as Error).message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [attempt]);
  return { rows, loading, error, retry: () => setAttempt((v) => v + 1) };
}

export default function SimpleStart() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const restored = (useLocation().state || {}) as SimpleRestore;
  const param = params.get("item");
  const presets = useEnabledPresets();
  const [kind, setKind] = useState<Item | null>(
    restored.kind || (param === "wappen" ? "vision" : param === "clothes" ? "simple" : null),
  );
  const [presetId, setPresetId] = useState(restored.presetId || "");
  const [target, setTarget] = useState<number | null>(restored.target ?? null);
  const [targets, setTargets] = useState<Record<string, string>>(restored.targets || {});
  const [starting, setStarting] = useState(false);
  const [testRun, setTestRun] = useState(params.get("test") === "1");
  const linked = params.get("preset");
  useEffect(() => {
    const row = linked && presets.rows.find((p) => p.id === linked);
    if (!row || (row.kind !== "simple" && row.kind !== "vision")) return;
    setKind(row.kind);
    setPresetId(row.id);
    setTestRun(params.get("test") === "1");
  }, [linked, presets.rows, params]);
  const session = useApp((s) => s.snapshot?.session);
  const online = useApp((s) => s.connected);
  const brands = useApp((s) => s.brands);

  const choices = kind ? presets.rows.filter((p) => p.kind === kind) : [];
  const preset = choices.find((p) => p.id === presetId) ?? (choices.length === 1 ? choices[0] : undefined);
  const brand = preset && preset.brand_id !== "__simple__" ? brands.find((b) => b.id === preset.brand_id)?.source : undefined;
  const wappenReady = presets.rows.some((p) => p.kind === "vision");
  const pickPreset = kind && choices.length > 1 && !preset;
  const ready = !!kind && !presets.loading && !presets.error && (kind === "simple" || !!preset) &&
    (!brand || brand.options.every((o) => o.values.includes(targets[o.key])));

  const back = () => {
    if (kind && presetId && choices.length > 1) setPresetId("");
    else if (kind) {
      setKind(null);
      setPresetId("");
    } else nav("/");
  };

  const start = async () => {
    if (!kind || starting) return;
    setStarting(true);
    try {
      await startSession(
        {
          mode: kind,
          countMode: target ? "target" : "continuous",
          target,
          presetId: preset?.id,
          presetRevision: preset?.revision,
          brandId: preset?.brand_id,
          targets,
          testRun,
        },
        true,
      );
      nav("/run");
    } catch (e) {
      reportError(e);
      if (!ended(useApp.getState().snapshot?.session)) nav("/run");
    } finally {
      setStarting(false);
    }
  };

  if (!ended(session) && !starting)
    return (
      <Screen title="단순 계수" onBack={() => nav("/")}>
        <div className="flex h-full flex-col items-center justify-center gap-8">
          <Notice tone="warn">진행 중인 작업 있음</Notice>
          <button className="btn btn-go btn-xl" onClick={() => nav("/run")}>
            <Play size={44} strokeWidth={3} />
            이어서 하기
          </button>
        </div>
      </Screen>
    );

  const title = kind === "simple" ? "옷 계수" : kind === "vision" ? "와펜 계수" : "단순 계수";
  return (
    <Screen
      title={title}
      onBack={back}
      backLabel={kind ? "이전" : "처음"}
      right={testRun ? <span className="rounded-2xl border-2 border-ink-500 px-5 py-3 text-[28px] font-extrabold">시험</span> : undefined}
      footer={
        kind && !pickPreset ? (
          <>
            {preset && choices.length > 1 && <span className="text-[32px] font-extrabold">{preset.name}</span>}
            <div className="ml-auto flex gap-5">
              {starting && <StopButton />}
              <button className="btn btn-go btn-xl min-w-[440px]" disabled={!ready || !online || starting} onClick={start}>
                <Play size={48} strokeWidth={3} />
                {starting ? "시작하는 중" : "시작"}
              </button>
            </div>
          </>
        ) : undefined
      }
    >
      {presets.error && (
        <div className="mb-6 flex items-center gap-4">
          <Notice>{presets.error}</Notice>
          <button className="btn btn-outline btn-lg" onClick={presets.retry}>다시 불러오기</button>
        </div>
      )}
      {!kind && (
        <div className="grid h-full grid-cols-2 content-center gap-8">
          <Tile icon={Shirt} label="옷" onClick={() => setKind("simple")} />
          <Tile
            icon={Award}
            label="와펜"
            status={!presets.loading && !wappenReady ? "설정 필요" : undefined}
            disabled={presets.loading || !wappenReady}
            onClick={() => setKind("vision")}
          />
        </div>
      )}
      {pickPreset && (
        <div className="grid grid-cols-2 gap-6 pt-4">
          {choices.map((p) => (
            <button key={p.id} className="choice min-h-[160px] w-full !text-[44px]" onClick={() => setPresetId(p.id)}>
              {p.name}
            </button>
          ))}
        </div>
      )}
      {kind && !pickPreset && (
        <div className="grid gap-10 pt-4" style={{ gridTemplateColumns: kind === "vision" ? "minmax(0,1.2fr) minmax(0,1fr)" : "1fr" }}>
          <div className="space-y-10">
            {brand?.options.map((option) => (
              <OptionButtons
                key={option.key}
                option={option}
                value={targets[option.key] || ""}
                onChange={(value) => setTargets((old) => ({ ...old, [option.key]: value }))}
              />
            ))}
            <QuantityPicker value={target} onChange={setTarget} />
          </div>
          {kind === "vision" && <CameraBox className="h-[460px]" />}
        </div>
      )}
    </Screen>
  );
}
