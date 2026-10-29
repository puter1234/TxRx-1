import { useCallback, useEffect, useRef, useState } from "react";
import { api, uuid } from "../station/shared";
import { useCameraPreview } from "./useCameraPreview";

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
  wiring_fixed?: boolean;
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
  const { url, failed, frame } = useCameraPreview(connected);
  return <div><div className="relative flex h-80 items-center justify-center overflow-hidden rounded-xl bg-ink-900">
    {connected && url ? <img src={url} alt="카메라 시험 영상" className="h-full w-full object-contain" />
      : <p className="p-8 text-2xl font-bold text-white">{connected ? "영상 수신 재시도 중" : "카메라 미연결"}</p>}
    {tracking && flow && connected && url && !failed && <svg aria-label="검출 위치와 계수선" className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${tracking.width} ${tracking.height}`} preserveAspectRatio="xMidYMid meet">
      {tracking.boxes.map(([x1,y1,x2,y2], i) => <rect key={i} x={x1*tracking.width} y={y1*tracking.height} width={(x2-x1)*tracking.width} height={(y2-y1)*tracking.height} fill="none" stroke="#22c55e" strokeWidth={2}/>)}
      <line x1={flow.axis === "x" ? flow.line*tracking.width : 0} x2={flow.axis === "x" ? flow.line*tracking.width : tracking.width} y1={flow.axis === "y" ? flow.line*tracking.height : 0} y2={flow.axis === "y" ? flow.line*tracking.height : tracking.height} stroke="#facc15" strokeWidth={2}/>
    </svg>}
  </div>{connected && url && failed && <p role="status" className="mt-2 text-xl font-extrabold text-danger">영상 갱신 지연</p>}{connected && url && !failed && frame.seq && <details className="mt-2 text-lg font-bold text-ink-700"><summary className="cursor-pointer">영상 정보</summary><p>프레임 {frame.seq}, 설정 버전 {frame.revision || "미확인"}</p></details>}</div>;
}
