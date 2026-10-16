import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../station/shared";
import { reportError } from "../lib/station";
import { useApp } from "../lib/store";

export type Preset = {
  id: string;
  name: string;
  revision: number;
  enabled: boolean;
  kind: "simple" | "condition" | "vision";
  brand_id: string;
  channels: string[];
  flow: Record<string, any>;
};
export const defaults = {
  low_speed_ms: 500,
  capture_delay_ms: 100,
  capture_count: 1,
  capture_interval_ms: 100,
  rfid_delay_ms: 100,
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
  name: "새 작업",
  revision: 1,
  enabled: true,
  kind: "simple",
  brand_id: "__simple__",
  channels: [],
  flow: { ...defaults },
});

let retainedDraft: Preset | null = null;

export default function WorkPresets() {
  const nav = useNavigate();
  const brands = useApp((s) => s.brands);
  const [rows, setRows] = useState<Preset[]>([]),
    [draft, setDraft] = useState<Preset | null>(retainedDraft);
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  useEffect(() => {
    api<Preset[]>("/presets")
      .then((r) => {
        setRows(r);
        setDraft((d) => d || r[0] || fresh());
      })
      .catch(reportError);
  }, []);
  useEffect(() => {
    retainedDraft = draft;
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
        preset: draft,
        expected_revision: original ? draft.revision : null,
      });
      setRows((r) => [...r.filter((x) => x.id !== result.id), result]);
      setDraft(result);
      setMessage("저장했습니다.");
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  const number = (key: string, label: string, step = 1) => (
    <label key={key} className="block font-bold">
      {label}
      <input
        className="field mt-1"
        type="number"
        min={0}
        step={step}
        value={draft?.flow[key] ?? ""}
        onChange={(e) =>
          flow(key, e.target.value === "" ? "" : Number(e.target.value))
        }
      />
    </label>
  );
  if (!draft) return <p>작업 설정을 불러오는 중입니다.</p>;
  return (
    <div className="grid grid-cols-[230px_1fr] gap-5">
      <aside className="space-y-3">
        <h2 className="text-xl font-bold">작업 프리셋</h2>
        {rows.map((r) => (
          <button
            key={r.id}
            className={
              "btn w-full " +
              (r.id === draft.id ? "btn-primary" : "btn-outline")
            }
            disabled={dirty && r.id !== draft.id}
            onClick={() => {
              setDraft(r);
              setMessage("");
            }}
          >
            {r.name}
            {!r.enabled && " (사용 안 함)"}
          </button>
        ))}
        <button
          className="btn btn-outline w-full"
          disabled={dirty}
          onClick={() => setDraft(fresh())}
        >
          새 작업
        </button>
        <button
          className="btn btn-outline w-full"
          disabled={dirty}
          onClick={() =>
            setDraft({
              ...draft,
              id: fresh().id,
              name: draft.name + " 복사",
              revision: 1,
            })
          }
        >
          복사
        </button>
        <button
          className="btn btn-outline w-full"
          onClick={() => nav("/equipment?tab=camera")}
        >
          카메라 테스트
        </button>
      </aside>
      <div className="space-y-5">
        <div className="card grid grid-cols-2 gap-4 p-5">
          <label className="font-bold">
            작업 이름
            <input
              className="field mt-1"
              value={draft.name}
              onChange={(e) => changed({ name: e.target.value })}
            />
          </label>
          <label className="font-bold">
            기능
            <select
              aria-label="기능"
              className="field mt-1"
              value={draft.kind}
              onChange={(e) => {
                const kind = e.target.value as Preset["kind"];
                changed({
                  kind,
                  channels: kind === "condition" ? ["ocr", "rfid"] : [],
                  brand_id: kind === "simple" ? "__simple__" : draft.brand_id,
                  flow: {
                    ...draft.flow,
                    counter: kind === "vision" ? "cvzone" : "sensor",
                  },
                });
              }}
            >
              <option value="simple">단순 계수</option>
              <option value="condition">조건 검사</option>
              <option value="vision">와펜 계수</option>
            </select>
          </label>
          {draft.kind !== "simple" && (
            <label className="font-bold">
              브랜드
              <select
                aria-label="브랜드"
                className="field mt-1"
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
          <label className="flex items-center gap-3 font-bold">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => changed({ enabled: e.target.checked })}
            />
            작업자 화면에 표시
          </label>
          {draft.kind === "condition" && (
            <fieldset className="col-span-2 flex gap-5">
              <legend className="mb-2 font-bold">검사 항목</legend>
              {[
                ["ocr", "OCR"],
                ["rfid", "RFID"],
                ["barcode", "바코드"],
              ].map(([id, label]) => (
                <label key={id} className="flex gap-2">
                  <input
                    type="checkbox"
                    checked={draft.channels.includes(id)}
                    onChange={(e) =>
                      changed({
                        channels: e.target.checked
                          ? [...draft.channels, id]
                          : draft.channels.filter((c) => c !== id),
                      })
                    }
                  />
                  {label}
                </label>
              ))}
            </fieldset>
          )}
        </div>
        <section className="card space-y-4 p-5">
          <h2 className="text-xl font-bold">DI1 감지 후 실행 시간</h2>
          <p>LED는 DI1에서 켜지고 DI2에서 꺼집니다.</p>
          <div className="grid grid-cols-3 gap-4">
            {number("low_speed_ms", "저속 유지 (ms)")}
            {draft.kind !== "simple" &&
              number("capture_delay_ms", "첫 촬영 (ms)")}
            {draft.channels.includes("rfid") &&
              number("rfid_delay_ms", "RFID 확인 (ms)")}
          </div>
          {draft.kind !== "simple" && (
            <div className="grid grid-cols-3 gap-4">
              <label className="font-bold">
                촬영 방식
                <select
                  aria-label="촬영 방식"
                  className="field mt-1"
                  value={draft.flow.capture_count === 1 ? "single" : "multiple"}
                  onChange={(e) =>
                    flow("capture_count", e.target.value === "single" ? 1 : 3)
                  }
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
          {draft.flow.capture_count > 1 && (
            <p>
              마지막 촬영은 DI1 감지 후{" "}
              {Number(draft.flow.capture_delay_ms) +
                (draft.flow.capture_count - 1) * draft.flow.capture_interval_ms}
              ms입니다. 모든 촬영 결과가 일치해야 합니다.
            </p>
          )}
        </section>
        <section className="card space-y-4 p-5">
          <h2 className="text-xl font-bold">센서와 연결</h2>
          <div className="grid grid-cols-3 gap-4">
            {number("di1_debounce_ms", "DI1 신호 유지 (ms)")}
            {number("di2_debounce_ms", "DI2 신호 유지 (ms)")}
            {number("departure_timeout_ms", "DI2 도착 제한 (ms)")}
            {number("result_timeout_ms", "검사 완료 제한 (ms)")}
            {number("reconnect_interval_ms", "카메라 재연결 간격 (ms)")}
          </div>
        </section>
        {draft.kind === "vision" && (
          <section className="card space-y-4 p-5">
            <h2 className="text-xl font-bold">와펜 계수</h2>
            <label className="block font-bold">
              계수 방법
              <select
                aria-label="계수 방법"
                className="field mt-1"
                value={draft.flow.counter}
                onChange={(e) => flow("counter", e.target.value)}
              >
                <option value="cvzone">CVZone</option>
                <option value="yolo">YOLO</option>
              </select>
            </label>
            {draft.flow.counter === "yolo" ? (
              <>
                <label className="block font-bold">
                  모델 파일 (.pt, .onnx)
                  <input
                    className="field mt-1"
                    value={draft.flow.model_path}
                    onChange={(e) => flow("model_path", e.target.value)}
                    placeholder="/opt/txrx/models/wappen.onnx"
                  />
                </label>
                <div className="grid grid-cols-3 gap-4">
                  {number("confidence", "검출 신뢰도", 0.05)}
                  {number("image_size", "입력 크기")}
                </div>
                <label className="block font-bold">
                  클래스 번호 (쉼표 구분, 비우면 전체)
                  <input
                    className="field mt-1"
                    value={draft.flow.classes.join(",")}
                    onChange={(e) =>
                      flow(
                        "classes",
                        e.target.value
                          ? e.target.value.split(",").map(Number)
                          : [],
                      )
                    }
                  />
                </label>
              </>
            ) : (
              <div className="grid grid-cols-3 gap-4">
                {number("threshold", "밝기 기준 (0~255)")}
                {number("min_area", "최소 면적 (픽셀)")}
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={draft.flow.invert}
                    onChange={(e) => flow("invert", e.target.checked)}
                  />
                  어두운 물체 검출
                </label>
              </div>
            )}
            <div className="grid grid-cols-4 gap-3">
              {["왼쪽", "위", "너비", "높이"].map((label, i) => (
                <label key={label} className="font-bold">
                  영역 {label} (0~1)
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    className="field mt-1"
                    value={draft.flow.roi[i]}
                    onChange={(e) =>
                      flow(
                        "roi",
                        draft.flow.roi.map((v: number, n: number) =>
                          n === i ? Number(e.target.value) : v,
                        ),
                      )
                    }
                  />
                </label>
              ))}
            </div>
            <div className="grid grid-cols-3 gap-4">
              <label className="font-bold">
                이동 방향
                <select
                  aria-label="이동 방향"
                  className="field mt-1"
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
              {number("line", "계수선 위치 (0~1)", 0.01)}
              {number("hysteresis", "계수선 여유 (0~1)", 0.01)}
              {number("match_distance", "추적 최대 이동 (0~1)", 0.01)}
              {number("track_lost_ms", "추적 유지 (ms)")}
            </div>
          </section>
        )}
        <footer className="sticky bottom-0 flex items-center gap-3 border-t border-line bg-white p-4">
          <p role="status" className="mr-auto font-bold">
            {dirty
              ? "저장하지 않은 변경이 있습니다."
              : message || "저장된 설정입니다."}
          </p>
          <button
            className="btn btn-outline"
            disabled={!dirty || busy}
            onClick={() => setDraft(original || rows[0] || fresh())}
          >
            변경 취소
          </button>
          <button
            className="btn btn-primary"
            disabled={!dirty || busy}
            onClick={save}
          >
            저장
          </button>
          <button
            className="btn btn-outline"
            disabled={dirty || busy || !draft.enabled}
            onClick={() => nav((draft.kind === "condition" ? "/condition/setup" : draft.kind === "vision" ? "/vision" : "/simple") + "?preset=" + encodeURIComponent(draft.id) + "&test=1")}
          >
            이 설정으로 시험
          </button>
        </footer>
      </div>
    </div>
  );
}
