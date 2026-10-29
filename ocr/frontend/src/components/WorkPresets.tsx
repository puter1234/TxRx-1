import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../station/shared";
import { reportError } from "../lib/station";
import RoiEditor from "./RoiEditor";
import { useApp } from "../lib/store";

export type Preset = {
  id: string;
  name: string;
  revision: number;
  enabled: boolean;
  kind: "simple" | "condition" | "vision";
  brand_id: string;
  channels: string[];
  barcode_targets?: ("tag" | "poly")[];
  flow: Record<string, any>;
};
export const defaults = {
  low_speed_ms: 500,
  capture_delay_ms: 100,
  capture_count: 1,
  capture_interval_ms: 100,
  rfid_delay_ms: 100,
  rfid_attempts: 3,
  rfid_interval_ms: 100,
  result_timeout_ms: 5000,
  departure_timeout_ms: 10000,
  reconnect_interval_ms: 2000,
  di1_debounce_ms: 20,
  di2_debounce_ms: 20,
  counter: "sensor",
  model_path: "",
  confidence: 0.5,
  classes: [],
  image_size: 640,
  threshold: 127,
  invert: false,
  min_area: 100,
  roi: [0, 0, 1, 1],
  axis: "y",
  direction: 1,
  line: 0.5,
  hysteresis: 0.02,
  match_distance: 0.15,
  track_lost_ms: 500,
};
const fresh = (): Preset => ({
  id: "work-" + Date.now().toString(36),
  name: "단순 계수",
  revision: 1,
  enabled: true,
  kind: "simple",
  brand_id: "__simple__",
  channels: [],
  flow: { ...defaults },
});

const retainedDrafts = new Map<string, Preset>();

export default function WorkPresets({ brandId }: { brandId?: string }) {
  const [kind, setKind] = useState<"simple" | "vision">("simple");
  if (brandId)
    return <PresetEditor key={brandId} brandId={brandId} kind="condition" />;
  return (
    <div className="space-y-6">
      <div className="flex gap-4" role="tablist" aria-label="계수 설정">
        {(
          [
            ["simple", "옷"],
            ["vision", "와펜"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={kind === id}
            className={"btn btn-lg min-w-[200px] " + (kind === id ? "btn-primary" : "btn-outline")}
            onClick={() => setKind(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div hidden={kind !== "simple"}>
        <PresetEditor kind="simple" />
      </div>
      <div hidden={kind !== "vision"}>
        <PresetEditor kind="vision" />
      </div>
    </div>
  );
}

function PresetEditor({
  brandId,
  kind,
}: {
  brandId?: string;
  kind: Preset["kind"];
}) {
  const cacheKey = brandId || kind;
  const initial = (): Preset => ({
    ...fresh(),
    kind,
    name:
      kind === "simple"
        ? "단순 계수"
        : kind === "vision"
          ? "와펜 계수"
          : "기본 설정",
    brand_id: brandId || "__simple__",
    channels: kind === "condition" ? ["ocr"] : [],
    flow: { ...defaults, counter: kind === "vision" ? "cvzone" : "sensor" },
  });
  const nav = useNavigate();
  const brands = useApp((s) => s.brands);
  const [rows, setRows] = useState<Preset[]>([]),
    [draft, setDraft] = useState<Preset | null>(
      retainedDrafts.get(cacheKey) || null,
    );
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true),
    [loadError, setLoadError] = useState(""),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError("");
    api<Preset[]>("/presets")
      .then((r) => {
        if (!alive) return;
        const rows = r.map(p => ({ ...p, flow: { ...defaults, ...p.flow } })).filter(
          (p) => p.kind === kind && (!brandId || p.brand_id === brandId),
        );
        setRows(rows);
        setDraft((d) => d || rows[0] || initial());
      })
      .catch((e) => { if (alive) setLoadError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [attempt]);
  useEffect(() => {
    if (draft) retainedDrafts.set(cacheKey, draft);
  }, [draft]);
  const changed = (next: Partial<Preset>) => {
    setMessage("");
    setDraft((d) => d && { ...d, ...next });
  };
  const flow = (key: string, value: any) =>
    draft && changed({ flow: { ...draft.flow, [key]: value } });
  const original = rows.find((r) => r.id === draft?.id);
  const dirty = JSON.stringify(original) !== JSON.stringify(draft);
  const save = async () => {
    if (!draft || busy) return;
    setBusy(true);
    try {
      const result = await api<Preset>("/presets", {
        preset: brandId
          ? {
              ...draft,
              channels: Object.entries(
                brands.find((b) => b.id === brandId)?.caps || {},
              )
                .filter(([, v]) => v)
                .map(([k]) => (k.startsWith("barcode_") ? "barcode" : k))
                .filter((v, i, a) => a.indexOf(v) === i),
              barcode_targets: [
                brands.find((b) => b.id === brandId)?.caps.barcode_tag && "tag",
                brands.find((b) => b.id === brandId)?.caps.barcode_poly &&
                  "poly",
              ].filter(Boolean),
            }
          : draft,
        expected_revision: original ? draft.revision : null,
      });
      setRows((r) => [...r.filter((x) => x.id !== result.id), result]);
      setDraft(result);
      setMessage("저장됨");
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  const number = (key: string, label: string, step = 1, min = 0, max?: number) => (
    <label key={key} className="block text-xl font-extrabold">
      {label}
      <input
        className="field mt-1"
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft?.flow[key] ?? ""}
        onChange={(e) =>
          flow(key, e.target.value === "" ? "" : Number(e.target.value))
        }
      />
    </label>
  );
  if (loadError) return <div role="alert" className="space-y-3"><p className="text-xl font-bold">{loadError}</p><button className="btn btn-outline" onClick={() => setAttempt(v => v + 1)}>다시 불러오기</button></div>;
  if (loading || !draft) return <p role="status" className="text-xl font-bold">불러오는 중</p>;
  return (
    <div className="max-w-6xl space-y-6">
      <section className="card space-y-5 p-6">
        <div className="flex flex-wrap items-center gap-4">
          {!brandId && (
            <h2 className="mr-auto text-[32px] font-black">
              {kind === "simple" ? "옷 계수 설정" : "와펜 계수 설정"}
            </h2>
          )}
          {rows.length > 1 && (
            <label className="flex items-center gap-3 text-xl font-extrabold">
              저장된 설정
              <select
                aria-label="저장된 설정"
                className="field !w-80"
                value={original ? draft.id : ""}
                disabled={busy}
                onChange={(e) => {
                  if (dirty && !window.confirm("저장하지 않은 변경을 버릴까요?"))
                    return;
                  const row = rows.find((r) => r.id === e.target.value);
                  if (row) {
                    setDraft(row);
                    setMessage("");
                  }
                }}
              >
                {!original && <option value="">작성 중</option>}
                {rows.map((r, i) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                    {rows.filter((v) => v.name === r.name).length > 1 ? ` (${i + 1})` : ""}
                    {!r.enabled ? " (사용 안 함)" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="grid grid-cols-2 gap-5">
          <label className="text-xl font-extrabold">
            설정 이름
            <input
              className="field mt-2"
              value={draft.name}
              onChange={(e) => changed({ name: e.target.value })}
            />
          </label>
          {!brandId && draft.kind !== "simple" && (
            <label className="text-xl font-extrabold">
              브랜드
              <select
                aria-label="브랜드"
                className="field mt-2"
                value={draft.brand_id}
                onChange={(e) => changed({ brand_id: e.target.value })}
              >
                <option value="__simple__">브랜드 없음</option>
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-3 rounded-2xl border-2 border-line px-5 py-3 text-xl font-extrabold">
            <input
              type="checkbox"
              className="h-8 w-8 accent-brand-600"
              checked={draft.enabled}
              onChange={(e) => changed({ enabled: e.target.checked })}
            />
            작업자 화면에 표시
          </label>
          <button
            className="btn btn-outline ml-auto"
            disabled={busy}
            onClick={() => {
              if (dirty && !window.confirm("저장하지 않은 변경을 버릴까요?")) return;
              setDraft({ ...initial(), name: "" });
              setMessage("");
            }}
          >
            설정 추가
          </button>
          <button
            className="btn btn-outline"
            disabled={dirty || busy || !original}
            onClick={() => {
              setDraft({ ...draft, id: fresh().id, name: draft.name + " 복사", revision: 1 });
              setMessage("");
            }}
          >
            현재 설정 복사
          </button>
        </div>
      </section>
      {draft.kind === "vision" && (
        <section className="card space-y-5 p-6">
          <h2 className="text-[28px] font-black">와펜 계수</h2>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <RoiEditor
              roi={draft.flow.roi}
              line={draft.flow.line}
              axis={draft.flow.axis}
              direction={draft.flow.direction}
              onChange={(patch) => changed({ flow: { ...draft.flow, ...patch } })}
            />
            <div className="space-y-5">
              <label className="block text-xl font-extrabold">
                계수 방법
                <select
                  aria-label="계수 방법"
                  className="field mt-2"
                  value={draft.flow.counter}
                  onChange={(e) => flow("counter", e.target.value)}
                >
                  <option value="cvzone">CVZone</option>
                  <option value="yolo">YOLO</option>
                </select>
              </label>
              <label className="block text-xl font-extrabold">
                이동 방향
                <select
                  aria-label="이동 방향"
                  className="field mt-2"
                  value={draft.flow.axis + draft.flow.direction}
                  onChange={(e) =>
                    changed({
                      flow: {
                        ...draft.flow,
                        axis: e.target.value[0],
                        direction: Number(e.target.value.slice(1)),
                      },
                    })
                  }
                >
                  <option value="y1">위에서 아래</option>
                  <option value="y-1">아래에서 위</option>
                  <option value="x1">왼쪽에서 오른쪽</option>
                  <option value="x-1">오른쪽에서 왼쪽</option>
                </select>
              </label>
              {draft.flow.counter === "yolo" ? (
                <>
                  <label className="block text-xl font-extrabold">
                    모델 파일 (.pt, .onnx)
                    <input
                      className="field mt-2"
                      value={draft.flow.model_path}
                      onChange={(e) => flow("model_path", e.target.value)}
                      placeholder="/opt/txrx/models/wappen.onnx"
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-4">
                    {number("confidence", "검출 신뢰도", 0.05)}
                    {number("image_size", "입력 크기")}
                  </div>
                  <label className="block text-xl font-extrabold">
                    클래스 번호
                    <input
                      className="field mt-2"
                      value={draft.flow.classes.join(",")}
                      placeholder="전체"
                      onChange={(e) =>
                        flow("classes", e.target.value ? e.target.value.split(",").map(Number) : [])
                      }
                    />
                  </label>
                </>
              ) : (
                <div className="grid grid-cols-2 gap-4">
                  {number("threshold", "밝기 기준 (0~255)")}
                  {number("min_area", "최소 면적 (픽셀)")}
                  <label className="col-span-2 flex items-center gap-3 text-xl font-extrabold">
                    <input
                      type="checkbox"
                      className="h-8 w-8 accent-brand-600"
                      checked={draft.flow.invert}
                      onChange={(e) => flow("invert", e.target.checked)}
                    />
                    어두운 물체 검출
                  </label>
                </div>
              )}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-4">
            {["왼쪽", "위", "너비", "높이"].map((label, i) => (
              <label key={label} className="text-xl font-extrabold">
                영역 {label} (0~1)
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  className="field mt-2"
                  value={draft.flow.roi[i]}
                  onChange={(e) =>
                    flow(
                      "roi",
                      draft.flow.roi.map((v: number, n: number) => (n === i ? Number(e.target.value) : v)),
                    )
                  }
                />
              </label>
            ))}
            {number("line", "계수선 위치 (0~1)", 0.01)}
            {number("hysteresis", "계수선 여유 (0~1)", 0.01)}
            {number("match_distance", "추적 최대 이동 (0~1)", 0.01)}
            {number("track_lost_ms", "추적 유지 (ms)")}
          </div>
        </section>
      )}
      <section className="card space-y-5 p-6">
        <h2 className="text-[28px] font-black">DI1 감지 후 실행 시간</h2>
        <div className="grid grid-cols-3 gap-4">
          {number("low_speed_ms", "저속 유지 (ms)")}
          {draft.kind !== "simple" && number("capture_delay_ms", "첫 촬영 (ms)")}
        </div>
        {draft.kind !== "simple" && (
          <div className="grid grid-cols-3 gap-4">
            <label className="text-xl font-extrabold">
              촬영 방식
              <select
                aria-label="촬영 방식"
                className="field mt-2"
                value={draft.flow.capture_count === 1 ? "single" : "multiple"}
                onChange={(e) => flow("capture_count", e.target.value === "single" ? 1 : 3)}
              >
                <option value="single">한 장</option>
                <option value="multiple">여러 장</option>
              </select>
            </label>
            {draft.flow.capture_count !== 1 && (
              <>
                {number("capture_count", "촬영 장수")}
                {number("capture_interval_ms", "촬영 간격 (ms)")}
              </>
            )}
          </div>
        )}
        {(brandId
          ? brands.find((b) => b.id === brandId)?.caps.rfid
          : draft.channels.includes("rfid")) && (
          <div className="grid grid-cols-3 gap-4">
            {number("rfid_delay_ms", "RFID 첫 읽기 (ms)")}
            {number("rfid_attempts", "RFID 최대 횟수", 1, 1, 100)}
            {number("rfid_interval_ms", "RFID 읽기 간격 (ms)", 1, 20, 10000)}
          </div>
        )}
      </section>
      <section className="card space-y-5 p-6">
        <h2 className="text-[28px] font-black">센서와 연결</h2>
        <div className="grid grid-cols-3 gap-4">
          {number("di1_debounce_ms", "DI1 신호 유지 (ms)")}
          {number("di2_debounce_ms", "DI2 신호 유지 (ms)")}
          {number("departure_timeout_ms", "DI2 도착 제한 (ms)")}
          {number("result_timeout_ms", "검사 완료 제한 (ms)")}
          {number("reconnect_interval_ms", "카메라 재연결 간격 (ms)")}
        </div>
      </section>
      <footer className="sticky bottom-0 z-10 flex items-center gap-4 rounded-2xl border-2 border-line bg-white p-5 shadow-lg">
        <p role="status" className="mr-auto text-[26px] font-extrabold">
          {dirty ? "변경됨" : message || "저장됨"}
        </p>
        <button
          className="btn btn-outline btn-lg"
          disabled={!dirty || busy}
          onClick={() => setDraft(original || rows[0] || initial())}
        >
          변경 취소
        </button>
        <button
          className="btn btn-primary btn-lg"
          disabled={!dirty || busy || !draft.name.trim()}
          onClick={save}
        >
          저장
        </button>
        <button
          className="btn btn-outline btn-lg"
          disabled={dirty || busy || !draft.enabled}
          onClick={() =>
            nav(
              (draft.kind === "condition" ? "/condition" : "/simple") +
                "?preset=" +
                encodeURIComponent(draft.id) +
                "&test=1",
            )
          }
        >
          시험 계수
        </button>
      </footer>
    </div>
  );
}
