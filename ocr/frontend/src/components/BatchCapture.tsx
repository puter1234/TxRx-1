import { useEffect, useState } from "react";
import { api } from "../station/shared";
import type { BenchHook } from "./DeviceTests";
import Help from "./Help";

export default function BatchCapture({ bench, locked }: { bench: BenchHook; locked: boolean }) {
  const [count, setCount] = useState(30);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const batch = bench.state?.batch;
  useEffect(() => { api("/bench/batches/latest").then(setResult).catch(() => {}); }, []);
  const shoot = () => bench.action(async () => {
    setError(""); setPending(true); setResult(null);
    try { setResult(await api("/bench/camera/batch", { count })); }
    catch (e) { setError((e as Error).message); }
    finally { setPending(false); }
  });
  return <div className="space-y-3 rounded-xl border border-line p-4">
    <div className="flex items-center gap-3"><h3 className="text-xl font-bold">연속 촬영</h3><Help text="서로 다른 원본 프레임을 지정한 장수만큼 PNG로 저장합니다. ZIP 안에 사진과 촬영 설정이 들어갑니다. 저장이 카메라 속도를 따라가지 못하면 중간 프레임을 건너뛰며 실제 저장 속도와 건너뛴 수를 기록합니다. 최대 500장, 5분입니다."/></div>
    <label className="block text-lg font-bold">촬영 장수<input className="field mt-2" type="number" min="1" max="500" step="1" disabled={pending || batch?.active} value={count} onChange={e => setCount(Number(e.target.value))}/></label>
    <div className="flex flex-wrap gap-3">
      <button className="btn btn-primary" disabled={locked || bench.busy || bench.state?.native_busy || !bench.state?.camera?.connected || !Number.isInteger(count) || count < 1 || count > 500} onClick={shoot}>촬영 시작</button>
      {(pending || batch?.active) && <button className="btn btn-outline" onClick={() => api("/bench/camera/batch/cancel", {}).catch(e => setError(e.message))}>촬영 중지</button>}
    </div>
    {(pending || batch?.active) && <p role="status" className="text-xl font-bold">{batch?.completed || 0} / {batch?.target || count}장 저장 중</p>}
    {error && <p role="alert" className="text-lg font-bold text-danger">{error}</p>}
    {result && <div className="space-y-3"><p className="text-xl font-bold">{result.count}장 저장 완료</p>
      <p className="text-lg font-bold">저장 속도 {result.saved_fps} FPS, 건너뛴 프레임 {result.skipped_frames}장</p>
      <a className="btn btn-primary" href={result.url} download>사진 전체 저장 (ZIP)</a></div>}
  </div>;
}
