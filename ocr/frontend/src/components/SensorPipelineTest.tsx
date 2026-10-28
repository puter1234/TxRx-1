import { useEffect, useRef, useState } from "react";
import { Play, Square } from "lucide-react";
import { api } from "../station/shared";
import InspectionImage from "./InspectionImage";
import Help from "./Help";
import type { BenchHook, BenchState } from "./DeviceTests";
import { LocatorSelect, LocationSummary, type Locator, type LocationDiagnostics } from "./BarcodeLocation";

type Line = { text: string; confidence: number };
type Frame = {
  seq: number; after_trigger_ms: number; state: string; image_available: boolean; crop_count: number;
  result: null | { error: string | null; ms_barcode: number; ms_ocr: number; ms_total: number;
    ocr_device?: string; ocr_gpu_name?: string; reads: { lines: Line[] }[]; barcode_diagnostics?: LocationDiagnostics };
};
type Job = { id: string; number: number; state: string; counted: boolean; collecting: boolean;
  frames: Frame[]; missed_frames: number; capture_error: string | null; matched_text: string | null };
type Settings = { conveyor_sync: boolean; low_speed_ms: number; capture_delay_ms: number;
  capture_interval_ms: number; departure_timeout_ms: number; frame_count: number;
  sensor_channel: number; active_raw: number; pattern: string; locator: Locator };
type State = { active: boolean; busy: boolean; error: string | null; detected: number; count: number;
  passed: number; failed: number; sensor_raw: number | null; await_clear: boolean; jobs: Job[]; settings?: Settings };
const states: Record<string, string> = {
  waiting: "대기", reading: "OCR 중", passed: "성공", failed: "미검출", cancelled: "중지",
  skipped: "OCR 생략", no_match: "미일치",
};

export default function SensorPipelineTest({ bench, locked }: { bench: BenchHook; locked: boolean }) {
  const [count, setCount] = useState(3), [channel, setChannel] = useState(1);
  const [activeRaw, setActiveRaw] = useState<number | null>(null), [pattern, setPattern] = useState("");
  const [linked, setLinked] = useState(true), [lowMs, setLowMs] = useState(500);
  const [delayMs, setDelayMs] = useState(100), [intervalMs, setIntervalMs] = useState(100);
  const [departureMs, setDepartureMs] = useState(10000), [message, setMessage] = useState("");
  const initialized = useRef(false), edited = useRef(false);
  const [state, setState] = useState<State | null>(null), [error, setError] = useState("");
  const [selection, setSelection] = useState<{ job: string; seq: number } | null>(null);
  const [actualSize, setActualSize] = useState(false);
  const [locator, setLocator] = useState<Locator>("yolo26");
  useEffect(() => {
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const next = await api<State>("/bench/pipeline"); if (alive) {
        setState(next); setError("");
        if (!initialized.current) {
          initialized.current = true;
          if (next.settings && !edited.current) {
            const s = next.settings;
            setLinked(s.conveyor_sync); setCount(s.frame_count); setChannel(s.sensor_channel);
            setActiveRaw(s.active_raw); setPattern(s.pattern); setLowMs(s.low_speed_ms);
            setLocator(s.locator ?? "yolo26");
            setDelayMs(s.capture_delay_ms); setIntervalMs(s.capture_interval_ms); setDepartureMs(s.departure_timeout_ms);
          }
        }
      } }
      catch (e) { if (alive) setError((e as Error).message); }
      if (alive) timer = setTimeout(poll, 500);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const signal = activeRaw ?? bench.state?.setup?.sensor_active_raw?.[channel - 1] ?? 0;
  const running = !!state?.busy;
  const motorWait = Math.ceil((bench.state?.cooldown_ms?.motor || 0) / 1000);
  const manualOutputs = linked && !running && Object.keys(bench.state?.runs || {}).length > 0;
  const settings: Settings = { conveyor_sync: linked, low_speed_ms: lowMs, capture_delay_ms: delayMs,
    capture_interval_ms: intervalMs, departure_timeout_ms: departureMs, frame_count: count,
    sensor_channel: linked ? 1 : channel, active_raw: linked ? 0 : signal, pattern, locator };
  const valid = Number.isInteger(count) && count >= 1 && count <= 100 && (!linked || (
    [lowMs, delayMs, intervalMs, departureMs].every(Number.isInteger) && lowMs >= 0 && lowMs <= 60000 &&
    delayMs >= 0 && delayMs <= 60000 && intervalMs >= 0 && intervalMs <= 10000 &&
    departureMs >= 100 && departureMs <= 120000 && delayMs + (count - 1) * intervalMs < departureMs));
  const save = () => bench.action(async () => {
    await api("/bench/pipeline/settings", settings, "PUT"); setMessage("설정을 저장했습니다.");
  });
  const start = () => bench.action(async () => {
    const next = await api<BenchState>("/bench/pipeline/start", settings);
    await bench.adoptRuns(next);
    setSelection(null);
    setState(await api<State>("/bench/pipeline"));
  }, true);
  const job = state?.jobs.find(j => j.id === selection?.job) ?? state?.jobs[0];
  const frame = job?.frames.find(f => f.seq === selection?.seq) ?? job?.frames[0];
  const frameUrl = job && frame ? `/api/bench/pipeline/frames/${job.id}/${frame.seq}` : "";
  const lines = frame?.result?.reads.flatMap(read => read.lines) ?? [];
  return <section className="card space-y-5 p-5" onChangeCapture={() => { edited.current = true; setMessage(""); }}>
    <div className="flex items-center gap-3"><h2 className="text-2xl font-extrabold">센서 연동 OCR 시험</h2>
      <Help text="컨베이어 연동은 DI1에서 저속 전환과 LED 점등, 설정 시간에 촬영, DI2에서 소등과 계수를 진행합니다. 저속 유지 시간이 끝나면 고속으로 돌아갑니다. OCR 성공 시 나머지 사진의 판독을 생략합니다. 문자를 읽지 못해도 결과를 남기고 운전은 계속합니다. 사진과 계수는 시험 결과로만 표시합니다. 센서 촬영 방식은 기존처럼 선택한 센서의 해제에서 계수합니다."/></div>
    <label className="block space-y-2 text-lg font-bold">시험 방식
      <select aria-label="시험 방식" className="field block w-full" disabled={running} value={linked ? "conveyor" : "sensor"} onChange={e => setLinked(e.target.value === "conveyor")}>
        <option value="conveyor">컨베이어 연동</option><option value="sensor">센서 촬영</option>
      </select>
    </label>
    <LocatorSelect value={locator} onChange={setLocator} disabled={running}/>
    {linked && <div className="space-y-3">
      <p className="text-lg">DI1에서 저속과 LED 켜기, DI2에서 LED 끄기와 계수</p>
      <div className="grid grid-cols-2 gap-3">
        <label className="font-bold">저속 유지 (ms)<input className="field mt-1 w-full" type="number" min={0} max={60000} disabled={running} value={lowMs} onChange={e => setLowMs(Number(e.target.value))}/></label>
        <label className="font-bold">촬영 지연 (ms)<input className="field mt-1 w-full" type="number" min={0} max={60000} disabled={running} value={delayMs} onChange={e => setDelayMs(Number(e.target.value))}/></label>
      </div>
      <p className="font-bold">DI1 {bench.state?.sensors.find(s => s.channel === 1)?.raw ?? "미확인"}, DI2 {bench.state?.sensors.find(s => s.channel === 2)?.raw ?? "미확인"}</p>
    </div>}
    <div className="flex flex-wrap items-end gap-4">
      <label className="space-y-2 text-lg font-bold">OCR 촬영 방식
        <select aria-label="OCR 촬영 방식" className="field block" disabled={running} value={count === 1 ? "single" : "multiple"} onChange={e => setCount(e.target.value === "single" ? 1 : 3)}>
          <option value="single">한 장</option><option value="multiple">여러 장</option>
        </select></label>
      <label className="space-y-2 text-lg font-bold">프레임 수
        <input aria-label="센서 감지 후 프레임 수" className="field block w-28 text-2xl" type="number" min={1} max={100}
          disabled={running} value={count} onChange={e => setCount(Number(e.target.value))}/></label>
      {linked && count > 1 && <label className="space-y-2 text-lg font-bold">OCR 촬영 간격 (ms)
        <input className="field block w-32" type="number" min={0} max={10000} disabled={running} value={intervalMs} onChange={e => setIntervalMs(Number(e.target.value))}/></label>}
      {!linked && <><label className="space-y-2 text-lg font-bold">센서
        <select className="field block" disabled={running} value={channel} onChange={e => { setChannel(Number(e.target.value)); setActiveRaw(null); }}>
          <option value={1}>DI1</option><option value={2}>DI2</option>
        </select></label>
      <label className="space-y-2 text-lg font-bold">감지값
        <select className="field block" disabled={running} value={signal} onChange={e => setActiveRaw(Number(e.target.value))}>
          <option value={0}>입력 0</option><option value={1}>입력 1</option>
        </select></label>
      <p className="py-3 text-xl font-bold">현재 입력 {bench.state?.sensors.find(s => s.channel === channel)?.raw ?? "미확인"}</p></>}
    </div>
    {linked && <details><summary className="cursor-pointer font-bold">DI2 대기 시간</summary>
      <label className="mt-2 block font-bold">DI2 도착 제한 (ms)<input className="field mt-1 w-full" type="number" min={100} max={120000} disabled={running} value={departureMs} onChange={e => setDepartureMs(Number(e.target.value))}/></label>
    </details>}
    <details className="space-y-3">
      <summary className="cursor-pointer text-lg font-bold">상품코드 형식</summary>
      <div className="flex items-center gap-2"><label htmlFor="sensor-ocr-pattern" className="text-lg font-bold">확인할 형식</label>
        <Help text="문자를 읽으면 해당 제품의 나머지 사진 판독을 생략합니다. 형식을 입력하면 형식에 맞는 문자를 읽었을 때 생략합니다. 모터 운전은 계속합니다. [A-Z]는 대문자, [0-9]는 숫자, [A-Z0-9]는 영문 또는 숫자입니다. {4}는 네 글자입니다. OCR 값의 공백은 비교할 때 제외합니다."/></div>
      <input id="sensor-ocr-pattern" className="field w-full text-lg" disabled={running} value={pattern}
        onChange={e => setPattern(e.target.value)} placeholder="[A-Z]{4}[0-9][A-Z][0-9]{3}[A-Z0-9]{2}[0-9]{3}"/>
    </details>
    <div className="flex items-center gap-3"><button className="btn btn-outline" onClick={save} disabled={locked || running || !valid}>설정 저장</button>{message && <p role="status">{message}</p>}</div>
    {!bench.state?.connected && <p>위쪽의 입력 연결을 누르세요.</p>}
    {!bench.state?.camera?.connected && <p>카메라를 연결하면 시험을 시작할 수 있습니다.</p>}
    {manualOutputs && <p>수동 출력 시험이 켜져 있습니다. 위쪽의 시험 비상정지로 끈 뒤 연동 시험을 시작하세요.</p>}
    {!running && motorWait > 0 && <p role="status">모터 재시작까지 {motorWait}초</p>}
    {!valid && <p role="alert" className="font-bold text-danger">촬영 장수와 시간을 확인하세요. 마지막 촬영은 DI2 도착 제한 시간보다 빨라야 합니다.</p>}
    <div className="grid grid-cols-2 gap-3">
      <button className="btn btn-primary !min-h-[72px] text-xl" onClick={start}
        disabled={locked || running || manualOutputs || motorWait > 0 || !bench.state?.connected || !bench.state?.camera?.connected || !valid}>
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
        <p className="text-xl font-bold">{job.counted ? "통과 계수 완료" : state?.settings?.conveyor_sync ? "DI2 통과 대기" : "센서 해제 대기"}, 확보 {job.frames.length}장</p>
        {job.capture_error && <p className="text-lg font-bold text-danger">{job.capture_error}</p>}
        {job.missed_frames > 0 && <p className="text-lg font-bold text-danger">수집하지 못한 중간 프레임 {job.missed_frames}개</p>}
        {job.matched_text && <p className="break-all text-3xl font-extrabold">{job.matched_text}</p>}
        <div className="flex flex-wrap gap-2">{job.frames.map((item, i) => <button key={item.seq}
          className={`btn ${item.seq === frame?.seq ? "btn-primary" : "btn-outline"}`}
          onClick={() => setSelection({ job: job.id, seq: item.seq })}>{i + 1}번 {states[item.state] || item.state}</button>)}</div>
        {frame && <>
          <p className="text-lg font-bold">프레임 {frame.seq}　감지 후 {frame.after_trigger_ms.toFixed(1)} ms</p>
          {frame.image_available ? <>
            <div className="flex flex-wrap gap-2">
              <button className={`btn btn-sm ${actualSize ? "btn-outline" : "btn-primary"}`} aria-pressed={!actualSize} onClick={() => setActualSize(false)}>화면 맞춤</button>
              <button className={`btn btn-sm ${actualSize ? "btn-primary" : "btn-outline"}`} aria-pressed={actualSize} onClick={() => setActualSize(true)}>원본 크기</button>
              <a className="btn btn-sm btn-outline" href={`${frameUrl}?original=true`} download>원본 저장</a>
            </div>
            <InspectionImage key={frameUrl} src={frameUrl} alt="센서 감지 후 수집한 프레임" diagnostics={frame.result?.barcode_diagnostics} actualSize={actualSize}/>
          </>
            : <p className="text-lg font-bold">사진이 메모리에서 정리되었습니다</p>}
          {frame.state === "skipped" && <p className="text-lg font-bold">앞 프레임에서 성공하여 OCR 생략</p>}
          {frame.result?.error && <p className="text-lg font-bold text-danger">{frame.result.error}</p>}
          {frame.result && <p className="text-lg font-bold">위치 검출과 정렬 {frame.result.ms_barcode.toFixed(1)} ms, OCR {frame.result.ms_ocr.toFixed(1)} ms</p>}
          <LocationSummary diagnostics={frame.result?.barcode_diagnostics}/>
          {lines.map((line, index) => <div key={index} className="space-y-2 rounded-xl border border-line p-3">
            {frame.image_available && index < frame.crop_count && <div className="max-h-56 overflow-auto">
              <img src={`${frameUrl}?crop=${index}`} alt="OCR에 입력한 글자" className={actualSize ? "max-w-none" : "max-h-56 max-w-full"}/>
            </div>}
            <p className="break-all text-3xl font-extrabold">{line.text || "문자 미검출"}</p>
          </div>)}
        </>}
      </div>}
    </>}
  </section>;
}
