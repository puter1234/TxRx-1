import { useEffect, useState } from "react";
import { Play, Square } from "lucide-react";
import { api } from "../station/shared";
import Help from "./Help";
import type { BenchHook, BenchState } from "./DeviceTests";

type Line = { text: string; confidence: number };
type Frame = {
  seq: number; after_trigger_ms: number; state: string; image_available: boolean; crop_count: number;
  result: null | { error: string | null; ms_barcode: number; ms_ocr: number; ms_total: number;
    ocr_device?: string; ocr_gpu_name?: string; reads: { lines: Line[] }[] };
};
type Job = { id: string; number: number; state: string; counted: boolean; collecting: boolean;
  frames: Frame[]; missed_frames: number; capture_error: string | null; matched_text: string | null };
type State = { active: boolean; busy: boolean; error: string | null; detected: number; count: number;
  passed: number; failed: number; sensor_raw: number | null; await_clear: boolean; jobs: Job[] };
const states: Record<string, string> = {
  waiting: "대기", reading: "OCR 중", passed: "성공", failed: "미검출", cancelled: "중지",
  skipped: "OCR 생략", no_match: "미일치",
};

export default function SensorPipelineTest({ bench, locked }: { bench: BenchHook; locked: boolean }) {
  const [count, setCount] = useState(3), [channel, setChannel] = useState(1);
  const [activeRaw, setActiveRaw] = useState<number | null>(null), [pattern, setPattern] = useState("");
  const [state, setState] = useState<State | null>(null), [error, setError] = useState("");
  const [selection, setSelection] = useState<{ job: string; seq: number } | null>(null);
  useEffect(() => {
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const next = await api<State>("/bench/pipeline"); if (alive) { setState(next); setError(""); } }
      catch (e) { if (alive) setError((e as Error).message); }
      if (alive) timer = setTimeout(poll, 500);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const signal = activeRaw ?? bench.state?.setup?.sensor_active_raw?.[channel - 1] ?? 0;
  const running = !!state?.busy;
  const start = () => bench.action(async () => {
    const next = await api<BenchState>("/bench/pipeline/start", {
      frame_count: count, sensor_channel: channel, active_raw: signal, pattern,
    });
    await bench.adoptRuns(next);
    setSelection(null);
    setState(await api<State>("/bench/pipeline"));
  });
  const job = state?.jobs.find(j => j.id === selection?.job) ?? state?.jobs[0];
  const frame = job?.frames.find(f => f.seq === selection?.seq) ?? job?.frames[0];
  const frameUrl = job && frame ? `/api/bench/pipeline/frames/${job.id}/${frame.seq}` : "";
  const lines = frame?.result?.reads.flatMap(read => read.lines) ?? [];
  return <section className="card space-y-5 p-5">
    <div className="flex items-center gap-3"><h2 className="text-2xl font-extrabold">센서 연동 OCR 시험</h2>
      <Help text="시작하면 모터와 LED가 켜집니다. 센서 감지 후 들어오는 새 프레임을 메모리에 모으면서 순서대로 OCR합니다. 성공하면 나머지 프레임의 OCR을 생략합니다. 센서가 해제되면 통과 수를 한 번 올립니다. 사진과 시험 계수는 생산 기록에 저장하지 않습니다. 입력 감시는 10ms 주기이며, 프레임 시간은 PC가 받은 시각입니다."/></div>
    <div className="flex flex-wrap items-end gap-4">
      <label className="space-y-2 text-lg font-bold">프레임 수
        <input aria-label="센서 감지 후 프레임 수" className="input block w-28 text-2xl" type="number" min={1} max={100}
          disabled={running} value={count} onChange={e => setCount(Number(e.target.value))}/></label>
      <label className="space-y-2 text-lg font-bold">센서
        <select className="input block" disabled={running} value={channel} onChange={e => { setChannel(Number(e.target.value)); setActiveRaw(null); }}>
          <option value={1}>DI1</option><option value={2}>DI2</option>
        </select></label>
      <label className="space-y-2 text-lg font-bold">감지값
        <select className="input block" disabled={running} value={signal} onChange={e => setActiveRaw(Number(e.target.value))}>
          <option value={0}>입력 0</option><option value={1}>입력 1</option>
        </select></label>
      <p className="py-3 text-xl font-bold">현재 입력 {bench.state?.sensors.find(s => s.channel === channel)?.raw ?? "미확인"}</p>
    </div>
    <details className="space-y-3">
      <summary className="cursor-pointer text-lg font-bold">상품코드 형식</summary>
      <div className="flex items-center gap-2"><label htmlFor="sensor-ocr-pattern" className="text-lg font-bold">확인할 형식</label>
        <Help text="비워두면 문자가 읽힌 프레임에서 중단합니다. 형식을 입력하면 그 형식에 맞는 문자열이 나올 때 중단합니다. [A-Z]는 대문자, [0-9]는 숫자, [A-Z0-9]는 영문 또는 숫자입니다. {4}는 네 글자입니다. OCR 값의 공백은 비교할 때 제외합니다."/></div>
      <input id="sensor-ocr-pattern" className="input w-full text-lg" disabled={running} value={pattern}
        onChange={e => setPattern(e.target.value)} placeholder="[A-Z]{4}[0-9][A-Z][0-9]{3}[A-Z0-9]{2}[0-9]{3}"/>
    </details>
    <div className="grid grid-cols-2 gap-3">
      <button className="btn btn-primary !min-h-[72px] text-xl" onClick={start}
        disabled={locked || running || !bench.state?.connected || !bench.state?.camera?.connected || !Number.isInteger(count) || count < 1 || count > 100}>
        <Play size={24}/>시험 시작</button>
      <button className="btn btn-danger !min-h-[72px] text-xl" onClick={() => bench.stop()}><Square size={24}/>시험 정지</button>
    </div>
    <p role="status" className="text-2xl font-extrabold">{state?.active ? state.await_clear ? "센서 해제 대기" : "시험 중" : running ? "중지 중" : "대기"}</p>
    {(error || state?.error) && <p role="alert" className="text-lg font-bold text-danger">{error || state?.error}</p>}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {[['통과 수', state?.count ?? 0], ['감지 수', state?.detected ?? 0], ['OCR 성공', state?.passed ?? 0], ['OCR 미검출', state?.failed ?? 0]].map(([label, value]) =>
        <div className="rounded-xl border border-line p-4" key={label}><p className="text-lg font-bold">{label}</p><p className="text-4xl font-extrabold">{value}</p></div>)}
    </div>
    {!!state?.jobs.length && <>
      <div className="flex flex-wrap gap-2">{state.jobs.map(item => <button key={item.id}
        className={`btn ${job?.id === item.id ? "btn-primary" : "btn-outline"}`}
        onClick={() => setSelection({ job: item.id, seq: item.frames[0]?.seq ?? -1 })}>
        {item.number}번 제품 {states[item.state] || item.state}
      </button>)}</div>
      {job && <div className="space-y-4 rounded-xl border border-line p-4">
        <p className="text-xl font-bold">{job.counted ? "통과 계수 완료" : "센서 해제 대기"}　확보 {job.frames.length}장</p>
        {job.capture_error && <p className="text-lg font-bold text-danger">{job.capture_error}</p>}
        {job.missed_frames > 0 && <p className="text-lg font-bold text-danger">수집하지 못한 중간 프레임 {job.missed_frames}개</p>}
        {job.matched_text && <p className="break-all text-3xl font-extrabold">{job.matched_text}</p>}
        <div className="flex flex-wrap gap-2">{job.frames.map((item, i) => <button key={item.seq}
          className={`btn ${item.seq === frame?.seq ? "btn-primary" : "btn-outline"}`}
          onClick={() => setSelection({ job: job.id, seq: item.seq })}>{i + 1}번 {states[item.state] || item.state}</button>)}</div>
        {frame && <>
          <p className="text-lg font-bold">프레임 {frame.seq}　감지 후 {frame.after_trigger_ms.toFixed(1)} ms</p>
          {frame.image_available ? <img src={frameUrl} alt="센서 감지 후 수집한 프레임" className="max-h-[600px] w-full rounded-xl object-contain"/>
            : <p className="text-lg font-bold">사진이 메모리에서 정리되었습니다</p>}
          {frame.state === "skipped" && <p className="text-lg font-bold">앞 프레임에서 성공하여 OCR 생략</p>}
          {frame.result?.error && <p className="text-lg font-bold text-danger">{frame.result.error}</p>}
          {frame.result && <p className="text-lg font-bold">위치 검출과 정렬 {frame.result.ms_barcode.toFixed(1)} ms, OCR {frame.result.ms_ocr.toFixed(1)} ms</p>}
          {lines.map((line, index) => <div key={index} className="space-y-2 rounded-xl border border-line p-3">
            {frame.image_available && index < frame.crop_count && <img src={`${frameUrl}?crop=${index}`} alt="OCR에 입력한 글자" className="max-h-56 max-w-full"/>}
            <p className="break-all text-3xl font-extrabold">{line.text || "문자 미검출"}</p>
          </div>)}
        </>}
      </div>}
    </>}
  </section>;
}
