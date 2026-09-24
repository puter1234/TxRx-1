import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, CreditCard, ScanText, Settings } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended, reportError } from "../lib/station";
import Help from "../components/Help";
import { Equipment as EquipmentDetails } from "../station/StationApp";
import { BenchHeader, CameraTest, OutputTests, SensorTest, useBench } from "../components/DeviceTests";

type Correction = { gain: number; offset: number; gamma: number; contrast: number; clahe: boolean };
type OcrResult = {
  text: string; confidence: number; min_char: number; ms: number;
  capture_ms?: number; processing_ms?: number;
  crop_width: number; crop_height: number; preview: string;
  chars: { ch: string; p: number }[];
};
const initialCorrection: Correction = { gain: 1, offset: 0, gamma: 1, contrast: 1, clahe: false };

export function OcrLiveTest({ bench, locked, checkOcr, ocr, ocrBusy }: {
  bench: ReturnType<typeof useBench>; locked: boolean;
  checkOcr: () => void; ocr: { ok: boolean; detail: string } | null; ocrBusy: boolean;
}) {
  const connected = bench.state?.camera?.connected === true;
  const [url, setUrl] = useState("");
  const [box, setBox] = useState<[number, number, number, number]>([0.1, 0.1, 0.8, 0.25]);
  const [rotation, setRotation] = useState(0);
  const [correction, setCorrection] = useState<Correction>(initialCorrection);
  const [result, setResult] = useState<OcrResult | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [saved, setSaved] = useState("");
  const start = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    api<Partial<Correction>>("/bench/ocr/correction")
      .then(value => setCorrection({ ...initialCorrection, ...value })).catch(() => {});
  }, []);
  useEffect(() => {
    if (!connected) { setUrl(""); return; }
    let alive = true, current = "", timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const next = async () => {
      try {
        const response = await fetch("/api/camera/frame", { signal: abort.signal, cache: "no-store" });
        if (!response.ok) throw new Error("영상 수신 실패");
        const nextUrl = URL.createObjectURL(await response.blob());
        if (!alive) { URL.revokeObjectURL(nextUrl); return; }
        if (current) URL.revokeObjectURL(current);
        current = nextUrl; setUrl(nextUrl);
      } catch { if (alive) setUrl(""); }
      if (alive) timer = setTimeout(next, 700);
    };
    void next();
    return () => { alive = false; abort.abort(); clearTimeout(timer); if (current) URL.revokeObjectURL(current); };
  }, [connected]);

  const point = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    const end = point(event), begin = start.current;
    setBox([Math.min(begin.x, end.x), Math.min(begin.y, end.y), Math.abs(begin.x - end.x), Math.abs(begin.y - end.y)]);
  };
  const read = async () => {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api<OcrResult>("/bench/ocr/read", { box, rotation, correction })); }
    catch (e) { setError(e instanceof Error ? e.message : "OCR 검사 실패"); }
    finally { setBusy(false); await bench.refresh().catch(() => {}); }
  };
  const save = async () => {
    setBusy(true); setError(""); setSaved("");
    try { await api("/bench/ocr/correction", correction, "PUT"); setSaved("보정값 저장 완료. 다음 작업부터 적용됩니다."); }
    catch (e) { setError(e instanceof Error ? e.message : "보정값 저장 실패"); }
    finally { setBusy(false); await bench.refresh().catch(() => {}); }
  };
  const slider = (key: "gain" | "offset" | "gamma" | "contrast", label: string, min: number, max: number, step: number) =>
    <label className="block text-lg font-bold" key={key}>{label} {correction[key].toFixed(2)}
      <input className="mt-2 w-full" type="range" min={min} max={max} step={step} value={correction[key]}
        onChange={e => { setCorrection(v => ({ ...v, [key]: Number(e.target.value) })); setSaved(""); }} />
    </label>;
  const canRead = connected && !!url && box[2] >= 0.02 && box[3] >= 0.02 && !locked && !busy;
  return <section className="card space-y-5 p-5">
    <div className="flex items-center gap-3"><ScanText size={26}/><h2 className="text-xl font-extrabold">OCR 촬영 시험</h2>
      <Help text="영상에서 글자 영역을 드래그하고 보정값을 조절한 뒤 검사하세요. 촬영 사진은 저장하지 않습니다. 보정값을 저장하면 다음 작업의 OCR에도 적용됩니다."/></div>
    <div className="grid gap-5 xl:grid-cols-2">
      <div className="space-y-3">
        <div className="rounded-xl bg-ink-900 p-2">
          {connected && url ? <div className="relative mx-auto w-fit max-w-full">
            <img src={url} alt="OCR 영역 선택용 카메라 영상" className="block max-h-[520px] max-w-full select-none" draggable={false}/>
            <div className="absolute inset-0 cursor-crosshair touch-none" aria-label="OCR 영역 선택"
              onPointerDown={event => { start.current = point(event); event.currentTarget.setPointerCapture(event.pointerId); move(event); }}
              onPointerMove={move} onPointerUp={event => { move(event); start.current = null; }}
              onPointerCancel={() => { start.current = null; }}>
              <div className="pointer-events-none absolute border-4 border-yellow-300 bg-yellow-300/15"
                style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${box[2] * 100}%`, height: `${box[3] * 100}%` }}/>
            </div>
          </div> : <p className="p-8 text-center text-2xl font-bold text-white">{connected ? "영상 수신 중" : "카메라 미연결"}</p>}
        </div>
        <p className="text-lg font-bold">글자 영역을 영상 위에서 드래그하세요.</p>
        <button className="btn btn-outline" disabled={locked || ocrBusy || busy} onClick={checkOcr}>{ocrBusy ? "모델 확인 중" : "OCR 모델 확인"}</button>
        {ocr && <p role="status" className={"text-lg font-bold " + (ocr.ok ? "text-ok" : "text-danger")}>{ocr.detail}</p>}
      </div>
      <div className="space-y-4">
        <h3 className="text-xl font-bold">영상 보정</h3>
        <label className="block text-lg font-bold">글자 방향
          <select className="field mt-2" value={rotation} onChange={e => setRotation(Number(e.target.value))}>
            <option value={0}>그대로</option><option value={90}>90도</option><option value={180}>180도</option><option value={270}>270도</option>
          </select>
        </label>
        {slider("gain", "밝기 증폭", 0.5, 8, 0.1)}
        {slider("offset", "밝기 이동", -64, 128, 1)}
        {slider("gamma", "감마", 0.25, 2, 0.05)}
        {slider("contrast", "대비", 0.5, 3, 0.1)}
        <label className="flex items-center gap-3 text-lg font-bold"><input type="checkbox" className="h-6 w-6" checked={correction.clahe}
          onChange={e => { setCorrection(v => ({ ...v, clahe: e.target.checked })); setSaved(""); }}/>국소 대비 보정</label>
        <div className="flex flex-wrap gap-3">
          <button className="btn btn-primary flex-1" disabled={!canRead} onClick={read}>{busy ? "검사 중" : "촬영하고 OCR 검사"}</button>
          <button className="btn btn-outline flex-1" disabled={locked || busy} onClick={save}>보정값 저장</button>
        </div>
        {error && <p role="alert" className="text-lg font-bold text-danger">{error}</p>}
        {saved && <p role="status" className="text-lg font-bold text-ok">{saved}</p>}
        {result && <div className="space-y-3 rounded-xl border border-line p-4">
          <h3 className="text-xl font-bold">인식한 영역 {result.crop_width} × {result.crop_height}</h3>
          <img src={result.preview} alt="OCR에 사용한 보정 영역" className="max-h-72 w-full rounded-lg bg-white object-contain"/>
          <p className="break-all text-3xl font-extrabold">{result.text || "문자 미검출"}</p>
          <p className="text-lg font-bold">인식 신뢰도 {(result.confidence * 100).toFixed(1)}%</p>
          <p className="text-lg font-bold">최저 문자 신뢰도 {(result.min_char * 100).toFixed(1)}%</p>
          {result.processing_ms !== undefined && <p className="text-lg font-bold">촬영 대기 {result.capture_ms?.toFixed(1)} ms, OCR 처리 {result.processing_ms.toFixed(1)} ms</p>}
          <details><summary className="cursor-pointer text-lg font-bold">문자별 결과</summary>
            <div className="mt-3 flex flex-wrap gap-2">{result.chars.map((item, i) => <span key={i} className="rounded-lg border border-line px-3 py-2 text-lg font-bold">{item.ch} {(item.p * 100).toFixed(0)}%</span>)}</div>
          </details>
        </div>}
      </div>
    </div>
  </section>;
}

export default function Equipment() {
  const nav = useNavigate(), bench = useBench();
  const state = useApp(s => s.snapshot), online = useApp(s => s.connected);
  const [ocr, setOcr] = useState<{ok: boolean; detail: string} | null>(null);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [rfidBusy, setRfidBusy] = useState(false);
  const [rfidError, setRfidError] = useState("");
  const rfidLocked = !online || !ended(state?.session) || bench.busy || !!bench.state?.native_busy || !!bench.state?.rfid_busy || rfidBusy;
  const locked = !online || !ended(state?.session) || bench.busy || !!bench.state?.native_busy || !!bench.state?.runs?.motor || bench.state?.run?.target === "motor";
  const rfid = bench.state?.rfid;
  const readRfid = async () => {
    setRfidError(""); setRfidBusy(true);
    try { await api("/bench/rfid", {}); }
    catch (error) { setRfidError(error instanceof Error ? error.message : "RFID 읽기 실패"); }
    finally { setRfidBusy(false); await bench.refresh().catch(() => {}); }
  };
  const checkOcr = () => bench.action(async () => {
    setOcr(null);
    setOcrBusy(true);
    try {
      setOcr(await api("/bench/ocr", {}));
    } catch (error) {
      setOcr({ ok: false, detail: error instanceof Error ? error.message : "OCR 모델을 불러오지 못했습니다." });
    } finally {
      setOcrBusy(false);
    }
  });
  return <div className="flex h-full flex-col">
    <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
      <button className="btn btn-outline btn-sm" onClick={() => nav("/")}><ArrowLeft size={20}/>처음 화면</button>
      <h1 className="text-2xl font-extrabold">장비 점검</h1>
      <button className="btn btn-outline ml-auto" onClick={() => nav("/settings?tab=devices")}><Settings size={22}/>연결 설정</button>
    </div>
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
      <BenchHeader bench={bench}/>
      <div className="grid gap-5 md:grid-cols-2"><OutputTests bench={bench}/></div>
      <SensorTest bench={bench}/>
      <CameraTest bench={bench}/>
      <div className="grid gap-5 md:grid-cols-2">
        <section className="card space-y-4 p-5">
          <div className="flex items-center gap-3"><CreditCard size={26}/><h2 className="text-xl font-extrabold">RFID 확인</h2>
            <Help text="설정한 직렬 포트에서 실제 태그를 읽습니다. EPC와 읽은 횟수를 표시하며 생산 수량에는 반영하지 않습니다."/></div>
          <button className="btn btn-primary w-full" disabled={rfidLocked} onClick={readRfid}>{rfidBusy || bench.state?.rfid_busy ? "태그 읽는 중" : "태그 읽기"}</button>
          {rfidError && <p role="alert" className="text-lg font-bold text-danger">{rfidError}</p>}
          {!rfidBusy && !rfidError && (rfid ? <div className="space-y-3"><p className="text-xl font-bold">{rfid.detail}</p>
            {rfid.tags.map((tag: any) => <div key={tag.epc} className="space-y-2 rounded-xl bg-panel p-4">
              <p className="break-all font-mono text-xl font-bold">{tag.epc}</p>
              <p className="text-lg font-bold">읽은 횟수 {tag.count}회</p>
              <p className="text-lg">최대 RSSI {tag.max_rssi}, 중앙 RSSI {tag.median_rssi}</p>
            </div>)}
          </div> : <p className="text-lg font-bold">읽은 태그 없음</p>)}
        </section>
      </div>
      <OcrLiveTest bench={bench} locked={locked} checkOcr={checkOcr} ocr={ocr} ocrBusy={ocrBusy}/>
      <details className="card p-5">
        <summary className="cursor-pointer text-xl font-bold">상세 장비 정보</summary>
        <div className="mt-5"><EquipmentDetails action={async fn => { try { await fn(); } catch(e) { reportError(e); } }} role="operator"/></div>
      </details>
    </div>
  </div>;
}
