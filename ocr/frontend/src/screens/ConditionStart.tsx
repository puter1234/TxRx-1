import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Play, Search } from "lucide-react";
import { useApp } from "../lib/store";
import { ended, refreshBrands, reportError, startSession } from "../lib/station";
import { optionColorStyle } from "../lib/optionColors";
import type { Checks } from "../lib/types";
import { Notice, QuantityPicker, Screen } from "../ui/kit";
import CameraBox from "../ui/CameraBox";
import StopButton from "../ui/StopButton";
import { needsCamera } from "../lib/jobs";
import { useEnabledPresets } from "./SimpleStart";

const CHECKS: { key: keyof Checks; label: string }[] = [
  { key: "ocr", label: "문자" },
  { key: "rfid", label: "RFID" },
  { key: "barcode_tag", label: "가격택 바코드" },
  { key: "barcode_poly", label: "폴리백 바코드" },
];

export default function ConditionStart() {
  const nav = useNavigate();
  const brands = useApp((s) => s.brands);
  const w = useApp((s) => s.wizard);
  const setW = useApp((s) => s.setWizard);
  const session = useApp((s) => s.snapshot?.session);
  const hardware = useApp((s) => s.snapshot?.mode === "HARDWARE");
  const online = useApp((s) => s.connected);
  const presets = useEnabledPresets();
  // null follows the first unfinished step; otherwise an explicit step chosen by
  // the back button or a tapped summary chip.
  const [view, setView] = useState<"brand" | "preset" | { option: string; jump?: boolean } | null>(null);
  const [query, setQuery] = useState("");
  const [starting, setStarting] = useState(false);
  useEffect(() => {
    refreshBrands().catch(reportError);
  }, []);
  const [params] = useSearchParams();
  const linked = useRef(false);
  useEffect(() => {
    const id = params.get("preset");
    const row = id && presets.rows.find((p) => p.id === id && p.kind === "condition");
    const b = row && brands.find((x) => x.id === row.brand_id);
    if (linked.current || !row || !b) return;
    linked.current = true;
    setW({ brandId: b.id, presetId: row.id, testRun: params.get("test") === "1", targets: {}, checks: { ...b.caps } });
  }, [params, presets.rows, brands, setW]);

  const brand = brands.find((b) => b.id === w.brandId) ?? null;
  const options = brand?.source.options ?? [];
  const brandPresets = presets.rows.filter((p) => p.kind === "condition" && p.brand_id === w.brandId);
  const preset = brandPresets.find((p) => p.id === w.presetId) ?? (brandPresets.length === 1 ? brandPresets[0] : undefined);
  const missing = options.find((o) => !o.values.includes(w.targets[o.key]));
  const editing = view && typeof view === "object" ? view.option : null;
  const current = editing ? options.find((o) => o.key === editing) : undefined;
  const step = !brand || view === "brand"
    ? "brand"
    : (brandPresets.length > 1 && !preset) || view === "preset"
      ? "preset"
      : current || missing
        ? "option"
        : "final";
  const option = current || missing;
  const target = w.countMode === "target" ? w.target : null;
  const anyCheck = CHECKS.some((c) => w.checks[c.key]);
  const filtered = useMemo(
    () => brands.filter((b) => b.name.toLowerCase().includes(query.trim().toLowerCase())),
    [brands, query],
  );

  const chooseBrand = (id: string) => {
    const b = brands.find((x) => x.id === id);
    if (!b) return;
    if (id !== w.brandId) setW({ brandId: id, presetId: "", targets: {}, checks: { ...b.caps } });
    setView(null);
  };
  const choose = (key: string, value: string) => {
    setW({ targets: { ...w.targets, [key]: value } });
    const next = options[options.findIndex((o) => o.key === key) + 1];
    // After "이전" the following options are visited in order again; a value
    // changed from its summary chip returns straight to the last step.
    setView(editing && next && !(typeof view === "object" && view?.jump) ? { option: next.key } : null);
  };
  const beforeOptions = () => setView(brandPresets.length > 1 ? "preset" : "brand");
  const back = () => {
    if (step === "final") options.length ? setView({ option: options[options.length - 1].key }) : beforeOptions();
    else if (step === "option" && option) {
      const index = options.indexOf(option);
      if (index > 0) setView({ option: options[index - 1].key });
      else beforeOptions();
    } else if (step === "preset") setView("brand");
    else nav("/");
  };
  const start = async () => {
    if (!brand || starting) return;
    setStarting(true);
    try {
      await startSession(
        {
          mode: "condition",
          presetId: preset?.id,
          presetRevision: preset?.revision,
          testRun: w.testRun,
          brandId: brand.id,
          brandName: brand.name,
          checks: w.checks,
          countMode: target ? "target" : "continuous",
          target,
          targets: w.targets,
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
      <Screen title="조건 계수" onBack={() => nav("/")}>
        <div className="flex h-full flex-col items-center justify-center gap-8">
          <Notice tone="warn">진행 중인 작업 있음</Notice>
          <button className="btn btn-go btn-xl" onClick={() => nav("/run")}>
            <Play size={44} strokeWidth={3} />
            이어서 하기
          </button>
        </div>
      </Screen>
    );

  const picked = brand && (
    <div className="flex flex-wrap items-center gap-3" aria-label="선택한 조건">
      <button className="choice !min-h-[72px] !text-[28px]" aria-label={`${brand.name} 다시 고르기`} onClick={() => setView("brand")}>
        {brand.name}
      </button>
      {options.filter((o) => w.targets[o.key] && o.values.includes(w.targets[o.key])).map((o) => (
        <button
          key={o.key}
          className="choice !min-h-[72px] !text-[28px]"
          aria-label={`${o.label} ${w.targets[o.key]} 다시 고르기`}
          aria-pressed={editing === o.key}
          style={optionColorStyle(o, w.targets[o.key])}
          onClick={() => setView({ option: o.key, jump: true })}
        >
          {w.targets[o.key]}
        </button>
      ))}
    </div>
  );

  return (
    <Screen
      title={step === "brand" ? "브랜드" : step === "preset" ? "작업 설정" : step === "option" && option ? option.label : "수량"}
      onBack={back}
      backLabel={step === "brand" ? "처음" : "이전"}
      right={
        <>
          {w.testRun && <span className="rounded-2xl border-2 border-ink-500 px-5 py-3 text-[28px] font-extrabold">시험</span>}
          {step !== "brand" && picked}
        </>
      }
      footer={
        step === "final" ? (
          <div className="ml-auto flex gap-5">
            {starting && <StopButton />}
            <button
              className="btn btn-go btn-xl min-w-[440px]"
              disabled={!online || starting || !anyCheck || presets.loading || !!presets.error}
              onClick={start}
            >
              <Play size={48} strokeWidth={3} />
              {starting ? "시작하는 중" : "시작"}
            </button>
          </div>
        ) : undefined
      }
    >
      {presets.error && (
        <div className="mb-6 flex items-center gap-4">
          <Notice>{presets.error}</Notice>
          <button className="btn btn-outline btn-lg" onClick={presets.retry}>다시 불러오기</button>
        </div>
      )}
      {step === "brand" && (
        <div className="space-y-6 pt-2">
          {brands.length > 12 && (
            <label className="relative block max-w-2xl">
              <Search size={36} className="absolute left-5 top-1/2 -translate-y-1/2" aria-hidden="true" />
              <input className="field !min-h-[84px] pl-20 !text-[32px]" aria-label="브랜드 검색" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
          )}
          <div className="grid grid-cols-3 gap-6">
            {filtered.map((b) => (
              <button key={b.id} className="choice min-h-[180px] w-full !text-[52px]" aria-pressed={b.id === w.brandId} onClick={() => chooseBrand(b.id)}>
                {b.name}
              </button>
            ))}
          </div>
          {!brands.length && <Notice tone="warn">등록된 브랜드 없음</Notice>}
        </div>
      )}
      {step === "preset" && (
        <div className="grid grid-cols-2 gap-6 pt-2">
          {brandPresets.map((p) => (
            <button key={p.id} className="choice min-h-[160px] w-full !text-[44px]" aria-pressed={p.id === w.presetId} onClick={() => { setW({ presetId: p.id }); setView(null); }}>
              {p.name}
            </button>
          ))}
        </div>
      )}
      {step === "option" && option && (
        <OptionStep key={option.key} option={option} value={w.targets[option.key] || ""} onPick={(v) => choose(option.key, v)} />
      )}
      {step === "final" && brand && (
        <div className="grid gap-10 pt-2" style={{ gridTemplateColumns: hardware && needsCamera("condition", checkedChannels(w.checks)) ? "minmax(0,1.2fr) minmax(0,1fr)" : "1fr" }}>
          <div className="space-y-10">
            <QuantityPicker
              value={target}
              onChange={(v) => setW(v === null ? { countMode: "continuous" } : { countMode: "target", target: v })}
            />
            {CHECKS.filter((c) => brand.caps[c.key]).length > 1 && <section aria-labelledby="checks-title">
              <h2 id="checks-title" className="mb-5 text-[36px] font-black">검사</h2>
              <div role="group" aria-labelledby="checks-title" className="flex flex-wrap gap-4">
                {CHECKS.filter((c) => brand.caps[c.key]).map((c) => (
                  <button
                    key={c.key}
                    className="choice !min-h-[124px] !text-[40px]"
                    aria-pressed={w.checks[c.key]}
                    disabled={w.checks[c.key] && CHECKS.filter((x) => w.checks[x.key]).length === 1}
                    onClick={() => setW({ checks: { ...w.checks, [c.key]: !w.checks[c.key] } })}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </section>}
          </div>
          {hardware && needsCamera("condition", checkedChannels(w.checks)) && <CameraBox className="h-[460px]" />}
        </div>
      )}
    </Screen>
  );
}

const checkedChannels = (checks: Checks) =>
  [checks.ocr && "ocr", checks.rfid && "rfid", (checks.barcode_tag || checks.barcode_poly) && "barcode"].filter(Boolean) as string[];

function OptionStep({
  option,
  value,
  onPick,
}: {
  option: { key: string; label: string; values: string[]; display?: "buttons" | "colors" | null; colors?: Record<string, string> };
  value: string;
  onPick: (value: string) => void;
}) {
  const [query, setQuery] = useState("");
  const values = option.values.filter((v) => v.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  // Columns are as wide as the longest value so codes such as HUTS6C612 stay on one line.
  const longest = Math.max(3, ...option.values.map((v) => v.length));
  return (
    <div className="space-y-6 pt-2">
      {option.values.length > 24 && (
        <label className="relative block max-w-2xl">
          <Search size={36} className="absolute left-5 top-1/2 -translate-y-1/2" aria-hidden="true" />
          <input className="field !min-h-[84px] pl-20 !text-[32px]" aria-label={option.label + " 검색"} value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
      )}
      <div
        role="group"
        aria-label={option.label}
        className="grid gap-5 text-[44px]"
        style={{ gridTemplateColumns: `repeat(auto-fill, minmax(min(100%, max(220px, calc(${longest * 1.2}ch + 4rem))), 1fr))` }}
      >
        {values.map((v) => (
          <button
            key={v}
            className="choice min-h-[140px] w-full !text-[44px]"
            aria-pressed={value === v}
            style={optionColorStyle(option, v)}
            onClick={() => onPick(v)}
          >
            {v}
          </button>
        ))}
      </div>
    </div>
  );
}
