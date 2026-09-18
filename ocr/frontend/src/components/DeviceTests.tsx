import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, Lightbulb, Play, Square, Signal, Settings } from "lucide-react";
import { api, uuid } from "../station/shared";
import { useApp } from "../lib/store";
import { ended } from "../lib/station";
import Help from "./Help";

export type BenchState = {
  cooldown_ms?: { motor: number; led: number };
  feedback?: { channel: number; line: number; raw: number | null; active: boolean | null; changes: number; changed_at: number | null };
  batch?: { active: boolean; completed: number; target: number };
  connected: boolean; native_busy: boolean; generation: number; error: string | null;
  run: { id: string; target: string; remaining_ms: number } | null;
  io: { km2_on?: boolean; physical_permit?: boolean; motor_requested?: boolean; led_requested?: boolean };
  sensors: { channel: number; line: number; raw: number | null; active: boolean | null; changes: number; changed_at: number | null }[];
  events: { channel: number; raw: number; time: number }[];
  output_blockers: string[]; setup: any; pins: { motor: number; led: number; feedback: number; chip: string };
  camera: any; rfid: any;
};
export function stopTests() {
  return fetch("/api/bench/stop", { method: "POST", credentials: "same-origin", keepalive: true });
}
export function useBench() {
  const [state, setState] = useState<BenchState | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const mounted = useRef(true), ownedRun = useRef<string | null>(null), pending = useRef(false);
  const refresh = useCallback(async () => {
    const next = await api<BenchState>("/bench");
    if (mounted.current) setState(next);
    return next;
  }, []);
  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await refresh(); } catch (e) { if (mounted.current) setError((e as Error).message); }
      if (mounted.current) timer = setTimeout(poll, 500);
    };
    void poll();
    const stop = () => { ownedRun.current = null; void stopTests().catch(() => {}); };
    const stopOwned = () => { if (ownedRun.current || pending.current) stop(); };
    const hidden = () => { if (document.visibilityState === "hidden") stopOwned(); };
    const heartbeat = setInterval(() => {
      const run_id = ownedRun.current;
      if (run_id && document.visibilityState !== "hidden") {
        void api("/bench/heartbeat", { run_id }).then(r => {
          if (!r.active) ownedRun.current = null;
        }).catch(stop);
      }
    }, 400);
    window.addEventListener("pagehide", stopOwned);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      mounted.current = false;
      clearTimeout(timer); clearInterval(heartbeat);
      window.removeEventListener("pagehide", stopOwned);
      document.removeEventListener("visibilitychange", hidden);
      if (ownedRun.current || pending.current) stop();
    };
  }, [refresh]);
  const action = async (fn: () => Promise<any>) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try { return await fn(); }
    catch (e) { if (mounted.current) setError((e as Error).message); }
    finally {
      pending.current = false;
      if (mounted.current) { setBusy(false); await refresh().catch(() => {}); }
    }
  };
  const pulse = (target: "motor" | "led", seconds: number) => action(async () => {
    if (!state) return;
    const result = await api<BenchState>("/bench/output", {
      target, seconds, generation: state.generation, request_id: uuid(), issued_at: Date.now() / 1000,
    });
    if (!mounted.current || document.visibilityState === "hidden") {
      await stopTests(); return;
    }
    ownedRun.current = result.run?.id || null;
    setState({ ...state, ...result });
  });
  const stop = async () => {
    ownedRun.current = null;
    try { await stopTests(); await refresh(); }
    catch { setError("정지 요청을 확인하지 못했습니다. 현장 정지 버튼을 누르세요."); }
  };
  return { state, busy, error, action, pulse, stop, refresh };
}
export type BenchHook = ReturnType<typeof useBench>;

export function CameraView({ connected }: { connected: boolean }) {
  const [url, setUrl] = useState(""), [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!connected) { setUrl(""); return; }
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
      } catch { if (alive) { setFailed(true); setUrl(""); } }
      if (alive) timer = setTimeout(next, 500);
    };
    void next();
    return () => { alive = false; abort.abort(); clearTimeout(timer); if (current) URL.revokeObjectURL(current); };
  }, [connected]);
  return <div className="flex min-h-64 items-center justify-center overflow-hidden rounded-xl bg-ink-900">
    {connected && url && !failed ? <img src={url} alt="카메라 시험 영상" className="max-h-[480px] w-full object-contain" />
      : <p className="p-8 text-2xl font-bold text-white">{failed ? "영상 연결 끊김" : "카메라 미연결"}</p>}
  </div>;
}

export function OutputTests({ bench, ledOnly = false }: { bench: BenchHook; ledOnly?: boolean }) {
  const [motorTime, setMotorTime] = useState(1), [ledTime, setLedTime] = useState(10);
  const state = bench.state, session = useApp(s => s.snapshot?.session);
  const locked = !ended(session) || bench.busy || !!state?.native_busy;
  const canOutput = !!state && state.connected && !state.output_blockers.length && !state.run && !locked;
  const motorWait = Math.ceil((state?.cooldown_ms?.motor || 0) / 1000);
  const ledWait = Math.ceil((state?.cooldown_ms?.led || 0) / 1000);
  return <>
    {!ledOnly && <div className="card space-y-4 p-5">
      <div className="flex items-center gap-3"><Play size={26}/><h2 className="text-xl font-extrabold">모터</h2>
        <Help text="DO1로 짧게 가동합니다. 속도는 US-52에서 조절합니다. 접촉기 상태는 실제 벨트 속도와 다릅니다."/></div>
      <p className="text-xl font-bold">{state?.io.km2_on === true ? "접촉기 켜짐" : state?.io.km2_on === false ? "접촉기 꺼짐" : "접촉기 미확인"}</p>
      <label className="block text-lg font-bold">시험 시간
        <select className="field mt-2" value={motorTime} onChange={e => setMotorTime(Number(e.target.value))}>
          {[0.5, 1, 2, 5].map(n => <option key={n} value={n}>{n}초</option>)}
        </select></label>
      <button className="btn btn-primary w-full" disabled={!canOutput || motorWait > 0} onClick={() => bench.pulse("motor", motorTime)}>{motorWait > 0 ? `${motorWait}초 후 가동 가능` : "모터 시험 가동"}</button>
    </div>}
    <div className="card space-y-4 p-5">
      <div className="flex items-center gap-3"><Lightbulb size={26}/><h2 className="text-xl font-extrabold">LED</h2>
        <Help text="DO2로 조명을 켜고 끕니다. 표시값은 출력 명령입니다. 실제 점등은 직접 확인하세요. 화면을 벗어나면 시험 출력을 끕니다."/></div>
      <p className="text-xl font-bold">{state?.io.led_requested ? "켜기 명령 중" : "끄기 명령"}</p>
      <label className="block text-lg font-bold">점등 시간
        <select className="field mt-2" value={ledTime} onChange={e => setLedTime(Number(e.target.value))}>
          {[5, 10, 30, 60].map(n => <option key={n} value={n}>{n}초</option>)}
        </select></label>
      <button className="btn btn-primary w-full" disabled={!canOutput || ledWait > 0} onClick={() => bench.pulse("led", ledTime)}>{ledWait > 0 ? `${ledWait}초 후 점등 가능` : "LED 켜기"}</button>
      <button className="btn btn-outline w-full" onClick={bench.stop}>LED 끄기</button>
    </div>
  </>;
}

export function BenchHeader({ bench }: { bench: BenchHook }) {
  const { state } = bench;
  const locked = !ended(useApp(s => s.snapshot?.session));
  return <div className="card space-y-4 p-5">
    <div className="flex flex-wrap items-center gap-4">
      <span className="text-xl font-extrabold">{state?.connected ? "입력 연결됨" : "입력 미연결"}</span>
      <button className="btn btn-outline" disabled={bench.busy || locked || !!state?.native_busy}
        onClick={() => bench.action(() => api(state?.connected ? "/bench/io/disconnect" : "/bench/io/connect", {}))}>
        {state?.connected ? "입력 연결 종료" : "입력 연결"}
      </button>
      <button className="btn btn-danger ml-auto !min-h-[60px] px-8 text-xl" onClick={bench.stop}><Square size={24}/>시험 전체 정지</button>
    </div>
    {state?.run && <p role="status" className="text-2xl font-extrabold text-warn">{state.run.target === "motor" ? "모터 가동" : "LED 점등"} {Math.ceil(state.run.remaining_ms / 1000)}초 남음</p>}
    {locked && <p className="text-xl font-bold">작업 종료 후 시험할 수 있습니다</p>}
    {(bench.error || state?.error) && <p role="alert" className="text-lg font-bold text-danger">{bench.error || state?.error}</p>}
    {!!state?.output_blockers.length && <div className="flex items-center"><span className="text-lg font-bold">출력 시험 준비 필요</span><Help text={state.output_blockers.join(" ")}/></div>}
  </div>;
}

export function CameraTest({ bench }: { bench: BenchHook }) {
  const nav = useNavigate(), [capture, setCapture] = useState<any>(null);
  const s = bench.state, locked = !ended(useApp(v => v.snapshot?.session));
  useEffect(() => { api("/bench/captures/latest").then(setCapture).catch(() => {}); }, []);
  return <section className="card space-y-4 p-5">
    <div className="flex items-center gap-3"><Camera size={26}/><h2 className="text-xl font-extrabold">카메라</h2>
      <button className="btn btn-outline ml-auto" onClick={() => nav("/settings?tab=devices")}><Settings size={22}/>카메라 설정</button></div>
    <CameraView connected={s?.camera?.connected === true}/>
    <div className="flex flex-wrap gap-3">
      <button className="btn btn-outline" disabled={bench.busy || locked} onClick={() => bench.action(() => api("/bench/camera/" + (s?.camera?.connected ? "disconnect" : "connect"), {}))}>
        {s?.camera?.connected ? "카메라 연결 종료" : "저장한 설정으로 연결"}
      </button>
      <button className="btn btn-primary" disabled={bench.busy || locked || !s?.camera?.connected || s?.run?.target === "motor"}
        onClick={() => bench.action(async () => setCapture(await api("/bench/camera/capture", {})))}>사진 촬영</button>
      {s?.camera?.width && <span className="self-center text-lg font-bold">{s.camera.width} × {s.camera.height} / {Number(s.camera.mean_received_fps || 0).toFixed(1)} fps</span>}
    </div>
    {s?.camera?.error && <p className="text-lg font-bold text-danger">{s.camera.error}</p>}
    {capture && <div className="space-y-3"><p className="text-lg font-bold">촬영 결과 {capture.width} × {capture.height}</p>
      <a className="btn btn-outline" href={capture.url} download={"camera-test-" + capture.id + ".png"}>원본 사진 저장</a>
      <img src={capture.url} alt="카메라 시험 촬영 결과" className="max-h-96 rounded-xl object-contain"/></div>}
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
