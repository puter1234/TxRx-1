import { useEffect, useRef, useState } from "react";
import { Image as ImageIcon, Play, Square } from "lucide-react";
import { api } from "../../station/shared";
import type { BenchHook, BenchState } from "../DeviceTests";
import type { Locator, LocationDiagnostics } from "../BarcodeLocation";
import type { Shown } from "./ResultView";

type Line = { text: string; confidence: number };
type Frame = {
  seq: number; after_trigger_ms: number; state: string; image_available: boolean; crop_count: number;
  result: null | { error: string | null; reads: { lines: Line[] }[]; barcode_diagnostics?: LocationDiagnostics };
};
type Job = { id: string; number: number; state: string; counted: boolean; frames: Frame[];
  missed_frames: number; capture_error: string | null; matched_text: string | null };
export type ProcessSettings = { conveyor_sync: boolean; low_speed_ms: number; capture_delay_ms: number;
  capture_interval_ms: number; departure_timeout_ms: number; frame_count: number;
  sensor_channel: number; active_raw: number; pattern: string; locator: Locator; text_finder: TextFinder;
  sensor_gap_ms: number };
type TextFinder = "basic" | "lines" | "detector";
type State = { active: boolean; busy: boolean; error: string | null; stop_reason?: string | null; detected: number;
  count: number; passed: number; failed: number; await_clear: boolean; jobs: Job[]; settings?: ProcessSettings };

// Stops the user asked for need no message.
const USER_STOPS = new Set(["정지", "공정 시험 중지", "점검 종료"]);

const JOB_STATE: Record<string, string> = {
  waiting: "대기", reading: "읽는 중", passed: "읽음", failed: "못 읽음", cancelled: "중지", skipped: "생략", no_match: "형식 다름",
};

// What is wrong with the settings, in the words of the field, or "" when they can run.
const settingsProblem = (s: ProcessSettings) => {
  const within = (v: number, min: number, max: number) => Number.isInteger(v) && v >= min && v <= max;
  if (!within(s.frame_count, 1, 100)) return "사진 장수 1~100";
  if (s.frame_count > 1 && !within(s.capture_interval_ms, 0, 10000)) return "사진 간격 0~10000";
  if (!s.conveyor_sync) return "";
  if (!within(s.low_speed_ms, 0, 60000)) return "저속 유지 0~60000";
  if (!within(s.capture_delay_ms, 0, 60000)) return "촬영 지연 0~60000";
  if (!within(s.departure_timeout_ms, 100, 120000)) return "DI2 도착 제한 100~120000";
  if (!within(s.sensor_gap_ms ?? 300, 0, 5000)) return "센서 끊김 허용 0~5000";
  if (s.capture_delay_ms + (s.frame_count - 1) * s.capture_interval_ms >= s.departure_timeout_ms)
    return "마지막 사진 시각이 DI2 도착 제한보다 늦음";
  return "";
};
const validSettings = (s: ProcessSettings) => !settingsProblem(s);

// Sensor-linked OCR test on the conveyor. One button starts it; the server opens
// the inputs, turns the camera on and takes over manual outputs by itself.
export default function ProcessTest({ bench, locked, onShow, onSettings }: {
  bench: BenchHook; locked: boolean; onShow: (shown: Shown | null) => void; onSettings: (s: ProcessSettings) => void;
}) {
  const [state, setState] = useState<State | null>(null);
  const [draft, setDraft] = useState<ProcessSettings | null>(null);
  const [saved, setSaved] = useState<"" | "saving" | "saved">("");
  const [saveError, setSaveError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    let alive = true;
    let poll: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const next = await api<State>("/bench/pipeline");
        if (!alive) return;
        setState(next);
        setDraft((d) => d || next.settings || null);
      } catch {
        // The device poll in the header already shows connection problems.
      }
      if (alive) poll = setTimeout(tick, 500);
    };
    void tick();
    return () => {
      alive = false;
      clearTimeout(poll);
      clearTimeout(timer.current);
    };
  }, []);
  useEffect(() => {
    if (draft) onSettings(draft);
  }, [draft]);

  const running = !!state?.busy;
  const pendingRef = useRef<ProcessSettings | null>(null);
  const saveNow = async (next: ProcessSettings) => {
    pendingRef.current = null;
    setSaved("saving");
    try {
      await api("/bench/pipeline/settings", next, "PUT");
      setSaved("saved");
    } catch (e) {
      setSaved("");
      setSaveError((e as Error).message);
    }
  };
  const change = (patch: Partial<ProcessSettings>) => {
    if (!draft) return;
    const next = { ...draft, ...patch };
    setDraft(next);
    setSaved("");
    setSaveError("");
    clearTimeout(timer.current);
    pendingRef.current = null;
    if (!validSettings(next)) return;
    pendingRef.current = next;
    timer.current = setTimeout(() => void saveNow(next), 500);
  };
  // Leaving within the wait still saves the last change.
  useEffect(() => () => {
    if (pendingRef.current) void saveNow(pendingRef.current);
  }, []);

  // The latest product follows automatically until the user picks one.
  const jobs = state?.jobs ?? [];
  const job = jobs.find((j) => j.id === selected) ?? [...jobs].reverse().find((j) => j.frames.length) ?? null;
  const show = (job: Job, frame: Frame) => {
    const url = `/api/bench/pipeline/frames/${job.id}/${frame.seq}`;
    const lines = frame.result?.reads.flatMap((r) => r.lines) ?? [];
    onShow({
      title: `${job.number}번 제품, ${job.frames.indexOf(frame) + 1}번 사진`,
      url: frame.image_available ? url : "",
      download: frame.image_available ? url + "?original=true" : undefined,
      diagnostics: frame.result?.barcode_diagnostics,
      lines: frame.result ? lines.map((line, i) => ({ text: line.text, confidence: line.confidence,
        image: frame.image_available && i < frame.crop_count ? `${url}?crop=${i}` : undefined })) : undefined,
      note: frame.result?.error || job.capture_error || undefined,
      report: frame.result ? { after_trigger_ms: frame.after_trigger_ms, ...frame.result } : undefined,
    });
  };

  if (!draft) return <p role="status" className="text-[24px] font-extrabold">불러오는 중</p>;
  const di = (channel: number) => bench.state?.sensors.find((s) => s.channel === channel)?.raw;
  const occupied = draft.conveyor_sync && bench.state?.connected && (di(1) === 0 || di(2) === 0);
  const motorWait = Math.ceil((bench.state?.cooldown_ms?.motor || 0) / 1000);
  const problem = settingsProblem(draft);
  const valid = !problem;
  const blocked = locked ? "작업 진행 중" : occupied ? "센서 앞 제품 치우기" : motorWait > 0 ? `모터 재시작 ${motorWait}초` : !valid ? "시험 설정 확인" : "";
  const start = () =>
    bench.action(async () => {
      const next = await api<BenchState>("/bench/pipeline/start", draft);
      await bench.adoptRuns(next);
      setSelected(null);
      setState(await api<State>("/bench/pipeline"));
    }, true);
  const summary = [draft.conveyor_sync ? "컨베이어 연동" : "센서 촬영", `사진 ${draft.frame_count}장`,
    draft.conveyor_sync ? `촬영 지연 ${draft.capture_delay_ms}ms` : ""].filter(Boolean).join(", ");
  const number = (key: keyof ProcessSettings, label: string, min: number, max: number) => (
    <label className="block space-y-2 text-[22px] font-extrabold">
      {label}
      <input className="field" type="number" min={min} max={max} disabled={running} value={draft[key] as number}
        onChange={(e) => change({ [key]: Number(e.target.value) } as Partial<ProcessSettings>)} />
    </label>
  );
  return (
    <div className="space-y-6">
      {running ? (
        <button className="btn btn-danger btn-xl w-full" onClick={() => bench.stop()}>
          <Square size={40} fill="currentColor" />
          시험 정지
        </button>
      ) : (
        <button className="btn btn-go btn-xl w-full" disabled={!!blocked || bench.busy} onClick={start}>
          <Play size={40} strokeWidth={3} />
          {blocked || "시험 시작"}
        </button>
      )}
      {!valid && !running && <p role="alert" className="text-[24px] font-extrabold text-danger">{problem}</p>}
      {(state?.error || (state?.stop_reason && !USER_STOPS.has(state.stop_reason))) && !running && (
        <p role="alert" className="text-[24px] font-extrabold text-danger">{state.error || state.stop_reason}</p>
      )}
      <p role="status" className="text-[26px] font-black">
        {state?.active ? (state.await_clear ? "센서 해제 대기" : "시험 중") : running ? "멈추는 중" : "대기"}
      </p>
      <div className="grid grid-cols-4 gap-3">
        {([["통과", state?.count], ["감지", state?.detected], ["읽음", state?.passed], ["못 읽음", state?.failed]] as const).map(([label, value]) => (
          <div key={label} className="rounded-2xl border-2 border-line bg-white p-3 text-center">
            <p className="text-[20px] font-extrabold text-ink-700">{label}</p>
            <p className="text-[40px] font-black tabular-nums leading-tight">{value ?? 0}</p>
          </div>
        ))}
      </div>
      {!!jobs.length && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {[...jobs].reverse().map((item) => (
              <button key={item.id} className={"btn " + (job?.id === item.id ? "btn-primary" : "btn-outline")}
                aria-pressed={job?.id === item.id} onClick={() => setSelected(item.id)}>
                {item.number}번 {JOB_STATE[item.state] || item.state}
              </button>
            ))}
          </div>
          {job?.matched_text && <p className="break-all text-[40px] font-black">{job.matched_text}</p>}
          {job && (
            <div className="flex flex-wrap gap-2" aria-label="사진">
              {job.frames.map((item, i) => (
                <button key={item.seq} className="btn btn-outline" onClick={() => show(job, item)}>
                  <ImageIcon size={26} />
                  {i + 1}번 사진 {JOB_STATE[item.state] || item.state}
                </button>
              ))}
            </div>
          )}
          {!!job?.missed_frames && <p className="text-[22px] font-extrabold text-danger">놓친 사진 {job.missed_frames}장</p>}
        </div>
      )}
      <details className="rounded-2xl border-2 border-line bg-white p-4">
        <summary className="cursor-pointer text-[24px] font-extrabold">
          시험 설정 <span className="text-[20px] text-ink-700">{summary}</span>
          {saveError ? <span className="ml-3 text-[20px] text-danger">{saveError}</span>
            : saved && <span className="ml-3 text-[20px] text-ok">{saved === "saving" ? "저장 중" : "저장됨"}</span>}
        </summary>
        <div className="mt-5 space-y-5">
          <div role="group" aria-label="시험 방식" className="grid grid-cols-2 gap-3">
            {([[true, "컨베이어 연동"], [false, "센서 촬영"]] as const).map(([value, label]) => (
              <button key={label} className={"btn btn-lg " + (draft.conveyor_sync === value ? "btn-primary" : "btn-outline")}
                aria-pressed={draft.conveyor_sync === value} disabled={running} onClick={() => change({ conveyor_sync: value })}>{label}</button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4">
            {draft.conveyor_sync && number("low_speed_ms", "저속 유지 (ms)", 0, 60000)}
            {draft.conveyor_sync && number("capture_delay_ms", "촬영 지연 (ms)", 0, 60000)}
            {number("frame_count", "사진 장수", 1, 100)}
            {draft.frame_count > 1 && number("capture_interval_ms", "사진 간격 (ms)", 0, 10000)}
            {draft.conveyor_sync && number("departure_timeout_ms", "DI2 도착 제한 (ms)", 100, 120000)}
            {draft.conveyor_sync && number("sensor_gap_ms", "센서 끊김 허용 (ms)", 0, 5000)}
          </div>
          {!draft.conveyor_sync && (
            <div className="grid grid-cols-2 gap-4">
              <label className="block space-y-2 text-[22px] font-extrabold">
                센서
                <select className="field" disabled={running} value={draft.sensor_channel} onChange={(e) => change({ sensor_channel: Number(e.target.value) })}>
                  <option value={1}>DI1</option>
                  <option value={2}>DI2</option>
                </select>
              </label>
              <label className="block space-y-2 text-[22px] font-extrabold">
                감지 신호
                <select className="field" disabled={running} value={draft.active_raw} onChange={(e) => change({ active_raw: Number(e.target.value) })}>
                  <option value={0}>0</option>
                  <option value={1}>1</option>
                </select>
              </label>
            </div>
          )}
          <label className="block space-y-2 text-[22px] font-extrabold">
            바코드 위치 찾기
            <select className="field" disabled={running} value={draft.locator} onChange={(e) => change({ locator: e.target.value as Locator })}>
              <option value="yolo26">모델</option>
              <option value="stripes">줄무늬</option>
              <option value="opencv">기존 방식</option>
            </select>
          </label>
          {draft.locator === "yolo26" && (
            <label className="block space-y-2 text-[22px] font-extrabold">
              글자 위치 찾기
              <select className="field" disabled={running} value={draft.text_finder ?? "basic"} onChange={(e) => change({ text_finder: e.target.value as TextFinder })}>
                <option value="basic">기존 방식</option>
                <option value="lines">A 줄 찾기 개선</option>
                <option value="detector">B 글자 검출 모델</option>
              </select>
            </label>
          )}
          <label className="block space-y-2 text-[22px] font-extrabold">
            상품코드 형식
            <input className="field" disabled={running} value={draft.pattern} placeholder="[A-Z]{4}[0-9]{3}"
              onChange={(e) => change({ pattern: e.target.value })} />
          </label>
        </div>
      </details>
    </div>
  );
}
