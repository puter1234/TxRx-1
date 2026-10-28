import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, Lightbulb, Play, Square, Signal } from "lucide-react";
import { api, uuid } from "../station/shared";
import { useApp } from "../lib/store";
import { cameraEditable, ended } from "../lib/station";
import Help from "./Help";
import BatchCapture from "./BatchCapture";

type BenchRun = { id: string; target: string; remaining_ms: number | null; feedback_checked?: boolean; feedback_error?: string | null };
export type BenchState = {
  motor_test_max_seconds?: number;
  cooldown_ms?: { motor: number; led: number; speed?: number };
  feedback?: { channel: number; line: number; raw: number | null; active: boolean | null; changes: number; changed_at: number | null };
  batch?: { active: boolean; completed: number; target: number };
  sensor_ocr?: { active: boolean; busy: boolean };
  connected: boolean; native_busy: boolean; rfid_busy?: boolean; generation: number; error: string | null;
  run: BenchRun | null;
  runs: Partial<Record<"motor" | "led" | "speed", BenchRun>>;
  io: { km2_on?: boolean; physical_permit?: boolean; motor_requested?: boolean; led_requested?: boolean; speed_requested?: boolean };
  sensors: { channel: number; line: number; raw: number | null; active: boolean | null; changes: number; changed_at: number | null }[];
  events: { channel: number; raw: number; time: number }[];
  output_blockers: string[]; led_blockers?: string[]; setup: any; pins: { motor: number; led: number; speed?: number | null; feedback: number; chip: string };
  camera: any; rfid: any;
};
export function stopTests() {
  return fetch("/api/bench/stop", { method: "POST", credentials: "same-origin", keepalive: true });
}
export function useBench() {
  const [state, setState] = useState<BenchState | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const mounted = useRef(true), ownedRuns = useRef(new Set<string>()), pending = useRef(false), outputPending = useRef(false);
  const refresh = useCallback(async () => {
    const next = await api<BenchState>("/bench");
    if (mounted.current) { setState(next); setConnectionError(""); }
    return next;
  }, []);
  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await refresh(); } catch (e) { if (mounted.current) setConnectionError((e as Error).message); }
      if (mounted.current) timer = setTimeout(poll, 500);
    };
    void poll();
    const stop = () => { ownedRuns.current.clear(); void stopTests().catch(() => {}); };
    const stopOwned = () => { if (ownedRuns.current.size || outputPending.current) stop(); };
    const hidden = () => { if (document.visibilityState === "hidden") stopOwned(); };
    const heartbeat = setInterval(() => {
      if (document.visibilityState !== "hidden") {
        for (const run_id of ownedRuns.current) {
          void api("/bench/heartbeat", { run_id }).then(r => {
            if (!r.active) ownedRuns.current.delete(run_id);
          }).catch(stop);
        }
      }
    }, 400);
    window.addEventListener("pagehide", stopOwned);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      mounted.current = false;
      clearTimeout(timer); clearInterval(heartbeat);
      window.removeEventListener("pagehide", stopOwned);
      document.removeEventListener("visibilitychange", hidden);
      if (ownedRuns.current.size || outputPending.current) stop();
    };
  }, [refresh]);
  const action = async (fn: () => Promise<any>, startsOutputs = false) => {
    if (pending.current) return;
    pending.current = true; outputPending.current = startsOutputs; setBusy(true); setError("");
    try { return await fn(); }
    catch (e) { if (mounted.current) setError((e as Error).message); }
    finally {
      pending.current = false; outputPending.current = false;
      if (mounted.current) { setBusy(false); await refresh().catch(() => {}); }
    }
  };
  const pulse = (target: "motor" | "led" | "speed", seconds: number | null = null) => action(async () => {
    if (!state) return;
    const result = await api<BenchState>("/bench/output", {
      target, seconds, generation: state.generation, request_id: uuid(), issued_at: Date.now() / 1000,
    });
    if (!mounted.current || document.visibilityState === "hidden") {
      await stopTests(); return;
    }
    const started = result.runs[target];
    if (started) ownedRuns.current.add(started.id);
    setState({ ...state, ...result });
  }, true);
  const stop = async () => {
    ownedRuns.current.clear();
    try { await stopTests(); await refresh(); }
    catch { setError("정지 요청을 확인하지 못했습니다. 현장 정지 버튼을 누르세요."); }
  };
  const adoptRuns = async (next: BenchState) => {
    if (!mounted.current || document.visibilityState === "hidden") {
      await stopTests(); return;
    }
    for (const run of Object.values(next.runs)) if (run) ownedRuns.current.add(run.id);
    setState(previous => previous ? { ...previous, ...next } : next);
  };
  const leave = async () => {
    try {
      if (state?.connected || ownedRuns.current.size || outputPending.current) {
        await api("/bench/close", {});
        ownedRuns.current.clear();
      }
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  };
  return { state, busy, error: error || connectionError, action, pulse, stop, refresh, adoptRuns, leave };
}
export type BenchHook = ReturnType<typeof useBench>;

export function CameraView({ connected, tracking, flow }: { connected: boolean; tracking?: {boxes: number[][]; width: number; height: number}; flow?: Record<string, any> }) {
  const [url, setUrl] = useState(""), [failed, setFailed] = useState(false);
  const [frame, setFrame] = useState({ seq: "", revision: "" });
  useEffect(() => {
    if (!connected) { setUrl(""); setFailed(false); return; }
    let alive = true, current = "", timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const next = async () => {
      try {
        const r = await fetch("/api/camera/frame", { signal: abort.signal, cache: "no-store" });
        if (!r.ok) throw new Error();
        const nextUrl = URL.createObjectURL(await r.blob());
        if (!alive) { URL.revokeObjectURL(nextUrl); return; }
        if (current) URL.revokeObjectURL(current);
        current = nextUrl; setUrl(nextUrl); setFailed(false);
        setFrame({ seq: r.headers?.get("X-Camera-Frame") || "", revision: r.headers?.get("X-Camera-Revision") || "" });
      } catch { if (alive) setFailed(true); }
      if (alive) timer = setTimeout(next, 500);
    };
    void next();
    return () => { alive = false; abort.abort(); clearTimeout(timer); if (current) URL.revokeObjectURL(current); };
  }, [connected]);
  return <div><div className="relative flex h-80 items-center justify-center overflow-hidden rounded-xl bg-ink-900">
    {connected && url ? <img src={url} alt="카메라 시험 영상" className="h-full w-full object-contain" />
      : <p className="p-8 text-2xl font-bold text-white">{connected ? "영상 수신 재시도 중" : "카메라 미연결"}</p>}
    {tracking && flow && connected && url && !failed && <svg aria-label="검출 위치와 계수선" className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${tracking.width} ${tracking.height}`} preserveAspectRatio="xMidYMid meet">
      {tracking.boxes.map(([x1,y1,x2,y2], i) => <rect key={i} x={x1*tracking.width} y={y1*tracking.height} width={(x2-x1)*tracking.width} height={(y2-y1)*tracking.height} fill="none" stroke="#22c55e" strokeWidth={2}/>)}
      <line x1={flow.axis === "x" ? flow.line*tracking.width : 0} x2={flow.axis === "x" ? flow.line*tracking.width : tracking.width} y1={flow.axis === "y" ? flow.line*tracking.height : 0} y2={flow.axis === "y" ? flow.line*tracking.height : tracking.height} stroke="#facc15" strokeWidth={2}/>
    </svg>}
  </div>{connected && url && failed && <p role="status" className="mt-2 text-sm">영상 갱신 지연</p>}{connected && url && !failed && frame.seq && <details className="mt-2 text-sm text-ink-700"><summary className="cursor-pointer">영상 정보</summary><p>프레임 {frame.seq}, 설정 버전 {frame.revision || "미확인"}</p></details>}</div>;
}

export function OutputTests({ bench, ledOnly = false, compact = false }: { bench: BenchHook; ledOnly?: boolean; compact?: boolean }) {
  const nav = useNavigate();
  const state = bench.state, session = useApp(s => s.snapshot?.session);
  const locked = !ended(session) || bench.busy || !!state?.native_busy || !!state?.sensor_ocr?.busy;
  const canOutput = !!state && !state.runs.motor && !bench.busy;
  const canLed = !!state && !state.runs.led && !bench.busy;
  const [requestedTarget, setRequestedTarget] = useState<"motor" | "led" | "speed" | null>(null);
  const motorRun = state?.runs.motor;
  const motorOn = state?.io.motor_requested === true;
  const ledOn = state?.io.led_requested === true;
  const motorWait = Math.ceil((state?.cooldown_ms?.motor || 0) / 1000);
  const ledWait = Math.ceil((state?.cooldown_ms?.led || 0) / 1000);
  if (compact) return <div className="card space-y-2 p-3">
    <div className="flex flex-wrap items-center gap-4">
      {(["motor", "led", "speed"] as const).map(target => {
        const on = target === "motor" ? motorOn : target === "led" ? ledOn : state?.io.speed_requested === true;
        const wait = Math.ceil((state?.cooldown_ms?.[target] || 0) / 1000);
        return <div key={target} role="group" aria-label={target === "motor" ? "모터 스위치" : target === "led" ? "LED 스위치" : "속도 선택"} className="flex items-center gap-2">
          <span className="font-extrabold">{target === "motor" ? "모터" : target === "led" ? "LED" : "속도"}</span>
          <button className={"btn btn-sm " + (!on ? "btn-primary" : "btn-outline")} aria-pressed={!on} disabled={locked || (target !== "motor" && wait > 0) || (target === "speed" && state?.pins.speed == null)}
            onClick={() => bench.action(() => api(`/bench/${target}/off`, {}))}>{target === "speed" ? "저속" : "끄기"}</button>
          <button className={"btn btn-sm " + (on ? "btn-primary" : "btn-outline")} aria-pressed={on} disabled={locked || !state || !!state.runs[target] || wait > 0 || (target === "speed" && state?.pins.speed == null)}
            onClick={() => bench.pulse(target)}>{target === "speed" ? "고속" : "켜기"}</button>
        </div>;
      })}
    </div>
    {motorWait > 0 && <p role="status">모터 재시작까지 {motorWait}초</p>}
    {motorRun && <p role="status" className={motorRun.feedback_error ? "font-bold text-danger" : "text-sm"}>{motorRun.feedback_error || (motorRun.feedback_checked ? "DI3 접촉기 응답 확인" : "DI3 응답 대기 (3초)")}</p>}
    {!!state?.output_blockers.length && <details><summary className="cursor-pointer font-bold">모터 시험 준비 필요</summary>
      {state.output_blockers.map(reason => <p key={reason}>{reason}</p>)}
      <button className="btn btn-outline btn-sm" onClick={() => nav("/equipment?tab=connections")}>모터 연결 설정</button>
    </details>}
  </div>;
  return <>
    {!ledOnly && <div className="card space-y-4 p-5">
      <div className="flex items-center gap-3"><Play size={26}/><h2 className="text-xl font-extrabold">모터</h2>
        <Help text="켜기와 끄기를 직접 선택합니다. 끄기는 즉시 작동하고, 끈 뒤 5초가 지나야 다시 켤 수 있습니다. 켠 뒤 3초 후 DI3를 확인하며 미응답은 표시만 합니다. 속도는 US-52에서 조절합니다. 장비 테스트를 종료하거나 통신이 끊기면 시험 출력을 끕니다."/></div>
      <p className="text-xl font-bold">{state?.io.km2_on === true ? "접촉기 켜짐" : state?.io.km2_on === false ? "접촉기 꺼짐" : "접촉기 미확인"}</p>
      <div role="group" aria-label="모터 스위치" className="grid grid-cols-2 gap-2">
        <button aria-pressed={!motorOn} className={`btn !min-h-[72px] text-2xl ${!motorOn ? "btn-primary" : "btn-outline"}`} disabled={locked} onClick={() => bench.action(() => api("/bench/motor/off", {}))}>끄기</button>
        <button aria-pressed={motorOn} className={`btn !min-h-[72px] text-2xl ${motorOn ? "btn-primary" : "btn-outline"}`} disabled={!canOutput || motorWait > 0} onClick={() => { setRequestedTarget("motor"); return bench.pulse("motor"); }}>켜기</button>
      </div>
      {motorWait > 0 && <p role="status">모터 재시작까지 {motorWait}초</p>}
      {requestedTarget === "motor" && bench.error && <p role="alert" className="text-lg font-bold text-danger">{bench.error}</p>}
      {motorRun && <p role="status" className={`text-lg font-bold ${motorRun.feedback_error ? "text-danger" : ""}`}>{motorRun.feedback_error ? `${motorRun.feedback_error} (켜기 명령 유지)` : motorRun.feedback_checked ? "DI3 응답 확인" : "DI3 응답 대기 (3초)"}</p>}
      {!!state?.output_blockers.length && <div className="space-y-2"><p className="text-lg font-bold">가동할 수 없는 이유</p>{state.output_blockers.map(reason => <p className="text-lg" key={reason}>{reason}</p>)}
        <button className="btn btn-outline w-full" onClick={() => nav("/equipment?tab=connections")}>모터 연결 설정</button></div>}
    </div>}
    <div className="card space-y-4 p-5">
      <div className="flex items-center gap-3"><Lightbulb size={26}/><h2 className="text-xl font-extrabold">LED</h2>
        <Help text="DO2로 조명을 켜고 끕니다. 표시값은 출력 명령입니다. 실제 점등은 직접 확인하세요. 장비 테스트를 종료하면 시험 출력을 끕니다. 탭 이동 시에는 유지합니다."/></div>
      <p className="text-xl font-bold">{state?.io.led_requested ? "켜기 명령 중" : "점등 상태는 현장에서 확인"}</p>
      <div role="group" aria-label="LED 스위치" className="grid grid-cols-2 gap-2">
        <button aria-pressed={!ledOn} className={`btn !min-h-[72px] text-2xl ${!ledOn ? "btn-primary" : "btn-outline"}`} disabled={ledWait > 0 || locked} onClick={() => bench.action(() => api("/bench/led/off", {}))}>끄기</button>
        <button aria-pressed={ledOn} className={`btn !min-h-[72px] text-2xl ${ledOn ? "btn-primary" : "btn-outline"}`} disabled={!canLed || ledWait > 0} onClick={() => { setRequestedTarget("led"); return bench.pulse("led"); }}>켜기</button>
      </div>
      {requestedTarget === "led" && bench.error && <p role="alert" className="text-lg font-bold text-danger">{bench.error}</p>}
    </div>
  </>;
}

export function BenchHeader({ bench, compact = false }: { bench: BenchHook; compact?: boolean }) {
  const { state } = bench;
  const snapshot = useApp(s => s.snapshot);
  const locked = !ended(snapshot?.session);
  return <div className={"card " + (compact ? "space-y-2 p-3" : "space-y-4 p-5")}>
    <div className="flex flex-wrap items-center gap-4">
      <span className="text-xl font-extrabold">{state?.connected ? "입력 연결됨" : "입력 미연결"}</span>
      <button className="btn btn-outline" disabled={bench.busy || locked || !!state?.native_busy}
        onClick={() => bench.action(() => api(state?.connected ? "/bench/io/disconnect" : "/bench/io/connect", {}))}>
        {state?.connected ? "입력 연결 종료" : "입력 연결"}
      </button>
      {compact && state && Object.values(state.runs).map(run => run && <span key={run.id} role="status" className="font-bold text-warn">{run.target === "motor" ? "모터 켜기 명령 중" : run.target === "led" ? "LED 켜기 명령 중" : "고속 선택 중"}</span>)}
      <button className="btn btn-danger ml-auto px-6 text-xl" onClick={bench.stop}><Square size={24}/>시험 비상정지</button>
    </div>
    {!compact && state && Object.values(state.runs).map(run => run && <p key={run.id} role="status" className="text-2xl font-extrabold text-warn">{run.target === "motor" ? "모터 켜기 명령 중" : run.target === "led" ? "LED 켜기 명령 중" : "고속 선택 중"}{run.remaining_ms !== null && ` ${Math.ceil(run.remaining_ms / 1000)}초 남음`}</p>)}
    {locked && <p className="font-bold">{cameraEditable(snapshot) ? "준비 중인 작업을 유지하며 카메라를 조정할 수 있습니다. 출력과 센서 시험은 작업 종료 후 가능합니다." : "작업 종료 후 시험할 수 있습니다"}</p>}
    {(bench.error || state?.error) && <p role="alert" className="text-lg font-bold text-danger">{bench.error || state?.error}</p>}
    {state?.error && <div className="flex items-center gap-3">
      <button className="btn btn-primary" disabled={bench.busy || locked || !!state.native_busy || !!state.run}
        onClick={() => bench.action(() => api("/bench/error/clear", {}))}>오류 해제</button>
      <Help text="출력 OFF와 DI3 접촉기 꺼짐을 확인한 뒤 오류를 해제합니다. 자동으로 켜지지 않습니다. 모터는 정지 후 5초, LED는 신호 변경 후 1초가 지나면 다시 시험할 수 있습니다."/>
    </div>}
    {!!state?.output_blockers.length && <div className="flex items-center"><span className="text-lg font-bold">출력 시험 준비 필요</span><Help text={state.output_blockers.join(" ")}/></div>}
  </div>;
}

export function CameraTest({ bench }: { bench: BenchHook }) {
  const [capture, setCapture] = useState<any>(null), [zoom, setZoom] = useState(false);
  const [method, setMethod] = useState("single");
  const s = bench.state, locked = !cameraEditable(useApp(v => v.snapshot));
  const busy = bench.busy || !!s?.native_busy || !!s?.rfid_busy || !!s?.sensor_ocr?.busy;
  useEffect(() => { let alive = true; api("/bench/captures/latest").then(result => { if (alive) setCapture(result); }).catch(() => {}); return () => { alive = false; }; }, []);
  return <section className="card space-y-3 p-4">
    <div className="flex items-center gap-3"><Camera size={24}/><h2 className="text-xl font-extrabold">영상과 사진</h2>
      <button className="btn btn-outline btn-sm ml-auto" disabled={busy || locked || !!s?.runs.motor}
        onClick={() => bench.action(() => api("/bench/camera/" + (s?.camera?.connected ? "disconnect" : "connect"), {}))}>
        {s?.camera?.connected ? "카메라 연결 종료" : "저장한 설정으로 연결"}
      </button></div>
    <div className="flex items-center gap-3">
      <label className="font-bold">촬영 방식<select className="field ml-2 !w-auto" value={method} disabled={busy} onChange={e => setMethod(e.target.value)}>
        <option value="single">한 장</option><option value="multiple">여러 장</option>
      </select></label>
      {method === "single" && <button className="btn btn-primary ml-auto" disabled={busy || locked || !s?.camera?.connected}
        onClick={() => bench.action(async () => { setCapture(await api("/bench/camera/capture", {})); setZoom(false); })}>사진 촬영</button>}
    </div>
    <div className={capture ? "grid gap-3" : ""}>
      <div className="min-w-0"><h3 className="mb-2 font-bold">실시간 영상</h3><CameraView connected={s?.camera?.connected === true}/></div>
      {capture && <div className="min-w-0 space-y-2">
        <h3 className="font-bold">촬영한 사진</h3>
        <div className="h-80 overflow-auto rounded-xl bg-ink-900">
          <img src={capture.url} alt="카메라 시험 촬영 결과" className={zoom ? "max-w-none" : "h-full w-full object-contain"}
            style={zoom ? { width: capture.width, height: capture.height, maxWidth: "none" } : undefined}/>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-outline btn-sm" aria-pressed={zoom} onClick={() => setZoom(v => !v)}>{zoom ? "화면에 맞춤" : "원본 1:1"}</button>
          <a className="btn btn-outline btn-sm" href={capture.url} download={"camera-test-" + capture.id + ".png"}>원본 사진 저장</a>
        </div>
        <details className="text-sm text-ink-700"><summary className="cursor-pointer">촬영 정보</summary>
          <p>{capture.width} × {capture.height}</p><p>프레임 {capture.metadata?.seq ?? "미확인"}, 설정 버전 {capture.metadata?.camera_settings_revision ?? "미확인"}</p>
        </details>
      </div>}
    </div>
    {s?.camera?.error && <p className="text-lg font-bold text-danger">{s.camera.error}</p>}
    <div hidden={method !== "multiple"}><BatchCapture bench={bench} locked={locked}/></div>

  </section>;
}

export function SensorTest({ bench }: { bench: BenchHook }) {
  const feedback = bench.state?.feedback;
  return <section className="card space-y-4 p-5">
    <div className="flex items-center gap-3"><Signal size={26}/><h2 className="text-xl font-extrabold">센서</h2>
      <Help text="감지와 해제 때 입력값 및 변화 횟수가 바뀌는지 확인하세요. 감지 극성을 설정하기 전에는 원시값만 표시합니다."/></div>
    <div className="grid grid-cols-2 gap-4">{bench.state?.sensors.map(s => <div key={s.channel} className="rounded-xl bg-panel p-4">
      <h3 className="text-xl font-extrabold">센서 {s.channel}</h3>
      <p className="my-3 text-2xl font-black">{s.raw === null ? "미연결" : s.active === null ? "입력 " + s.raw : s.active ? "감지" : "감지 없음"}</p>
      <p className="text-lg font-bold">변화 {s.changes}회</p>
      {s.changed_at && <p className="mt-2 text-lg">{new Date(s.changed_at * 1000).toLocaleTimeString("ko-KR")}</p>}
    </div>)}</div>
    <div className="rounded-xl bg-panel p-4 space-y-2">
      <div className="flex items-center gap-3"><h3 className="text-xl font-extrabold">DI3 접촉기 입력</h3><Help text="DI3는 KM2 접촉기 피드백입니다. 문서 기준 입력 0은 접촉기 켜짐, 1은 꺼짐입니다. 실제 벨트 회전을 확인하는 센서는 아닙니다. GPIO 번호는 커넥터의 물리 핀 번호와 다릅니다."/></div>
      <p className="text-2xl font-black">{feedback?.raw == null ? "입력 미확인" : `입력 ${feedback.raw}`}</p>
      <p className="text-xl font-bold">{feedback?.active == null ? "접촉기 미확인" : feedback.active ? "접촉기 켜짐" : "접촉기 꺼짐"}</p>
      <p className="text-lg font-bold">GPIO {feedback?.line ?? bench.state?.pins.feedback ?? "미확인"}, 변화 {feedback?.changes ?? 0}회</p>
      {feedback?.changed_at && <p className="text-lg">최근 변화 {new Date(feedback.changed_at * 1000).toLocaleTimeString("ko-KR")}</p>}
    </div>
  </section>;
}
