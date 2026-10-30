import { useEffect, useRef, useState } from "react";
import { api } from "../station/shared";
import type { BenchHook } from "./DeviceTests";

export default function BatchCapture({ bench, locked }: { bench: BenchHook; locked: boolean }) {
  const [count, setCount] = useState(30);
  const [interval, setInterval] = useState(0);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const active = useRef(false);
  // A batch the user stopped is not reported as a failure.
  const stopped = useRef(false);
  const batch = bench.state?.batch;
  useEffect(() => { api("/bench/batches/latest").then(setResult).catch(() => {}); }, []);
  useEffect(() => {
    const cancel = () => {
      if (active.current) void fetch("/api/bench/camera/batch/cancel", { method: "POST", credentials: "same-origin", keepalive: true }).catch(() => {});
    };
    const hidden = () => { if (document.visibilityState === "hidden") cancel(); };
    window.addEventListener("pagehide", cancel);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pagehide", cancel);
      document.removeEventListener("visibilitychange", hidden);
      cancel();
    };
  }, []);
  const shoot = () => bench.action(async () => {
    setError(""); setPending(true); setResult(null); active.current = true; stopped.current = false;
    try { setResult(await api("/bench/camera/batch", { count, interval_ms: interval })); }
    catch (e) { if (!stopped.current) setError((e as Error).message); }
    finally { setPending(false); active.current = false; }
  });
  return <div className="space-y-3">
    <label className="block text-lg font-bold">촬영 장수<input className="field mt-2" type="number" min="1" max="500" step="1" disabled={pending || batch?.active} value={count} onChange={e => setCount(Number(e.target.value))}/></label>
    <label className="block text-lg font-bold">촬영 간격 (ms)<input className="field mt-2" type="number" min="0" max="10000" step="1" disabled={pending || batch?.active} value={interval} onChange={e => setInterval(Number(e.target.value))}/></label>
    <p className="text-lg font-bold tabular-nums">최소 {((count - 1) * interval / 1000).toFixed(1)}초</p>
    <div className="flex flex-wrap gap-3">
      <button className="btn btn-primary" disabled={locked || bench.busy || bench.state?.native_busy || bench.state?.rfid_busy || bench.state?.sensor_ocr?.busy || !bench.state?.camera?.connected || !Number.isInteger(count) || count < 1 || count > 500 || !Number.isInteger(interval) || interval < 0 || interval > 10000 || (count - 1) * interval >= 300000} onClick={shoot}>촬영 시작</button>
      {(pending || batch?.active) && <button className="btn btn-outline" onClick={() => { stopped.current = true; api("/bench/camera/batch/cancel", {}).catch(e => setError(e.message)); }}>촬영 중지</button>}
    </div>
    {(pending || batch?.active) && <p role="status" className="text-xl font-bold">{batch?.completed || 0} / {batch?.target || count}장 저장 중</p>}
    {error && <p role="alert" className="text-lg font-bold text-danger">{error}</p>}
    {result && <div className="space-y-3"><p className="text-xl font-bold">{result.count}장 저장 완료</p>
      <p className="text-lg font-bold">저장 속도 {result.saved_fps} FPS, 건너뛴 프레임 {result.skipped_frames}장</p>
      <a className="btn btn-primary" href={result.url} download>사진 전체 저장 (ZIP)</a></div>}
  </div>;
}
