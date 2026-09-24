import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, CreditCard, ScanText, Settings } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended, reportError } from "../lib/station";
import Help from "../components/Help";
import { Equipment as EquipmentDetails } from "../station/StationApp";
import { BenchHeader, CameraTest, OutputTests, SensorTest, useBench } from "../components/DeviceTests";

type Correction = { gain: number; offset: number; gamma: number; contrast: number; clahe: boolean };
type OcrLine = {
  text: string; confidence: number; min_char: number; ms: number;
  crop_width: number; crop_height: number; preview: string;
  chars: { ch: string; p: number }[];
};
type OcrResult = { reads: { barcode: string | null; verdict: string; lines: OcrLine[] }[];
  error: string | null; capture_ms: number; processing_ms: number;
  ms_model_load: number; ms_barcode: number; ms_ocr: number };
const initialCorrection: Correction = { gain: 1, offset: 0, gamma: 1, contrast: 1, clahe: false };

export function OcrLiveTest({ bench, locked, checkOcr, ocr, ocrBusy }: {
  bench: ReturnType<typeof useBench>; locked: boolean;
  checkOcr: () => void; ocr: { ok: boolean; detail: string } | null; ocrBusy: boolean;
}) {
  const connected = bench.state?.camera?.connected === true;
  const [url, setUrl] = useState("");
  const [correction, setCorrection] = useState<Correction>(initialCorrection);
  const [result, setResult] = useState<OcrResult | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [saved, setSaved] = useState("");

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

  const read = async () => {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api<OcrResult>("/bench/ocr/read", { correction })); }
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
  const canRead = connected && !!url && !locked && !busy;
  return <section className="card space-y-5 p-5">
    <div className="flex items-center gap-3"><ScanText size={26}/><h2 className="text-xl font-extrabold">OCR 촬영 시험</h2>
      <Help text="카메라에서 새 영상을 받아 글자 줄을 자동으로 찾습니다. 촬영 사진은 저장하지 않습니다. 보정값을 저장하면 다음 작업에도 적용됩니다."/></div>
    <div className="grid gap-5 xl:grid-cols-2">
      <div className="space-y-3">
        <div className="rounded-xl bg-ink-900 p-2">
          {connected && url ? <img src={url} alt="카메라 영상" className="mx-auto block max-h-[520px] max-w-full"/>
            : <p className="p-8 text-center text-2xl font-bold text-white">{connected ? "영상 수신 중" : "카메라 미연결"}</p>}
        </div>
        <button className="btn btn-outline" disabled={locked || ocrBusy || busy} onClick={checkOcr}>{ocrBusy ? "모델 확인 중" : "OCR 모델 확인"}</button>
        {ocr && <p role="status" className={"text-lg font-bold " + (ocr.ok ? "text-ok" : "text-danger")}>{ocr.detail}</p>}
      </div>
      <div className="space-y-4">
        <h3 className="text-xl font-bold">영상 보정</h3>
        {slider("gain", "밝기 증폭", 0.5, 8, 0.1)}
        {slider("offset", "밝기 이동", -64, 128, 1)}
        {slider("gamma", "감마", 0.25, 2, 0.05)}
        {slider("contrast", "대비", 0.5, 3, 0.1)}
        <label className="flex items-center gap-3 text-lg font-bold"><input type="checkbox" className="h-6 w-6" checked={correction.clahe}
          onChange={e => { setCorrection(v => ({ ...v, clahe: e.target.checked })); setSaved(""); }}/>국소 대비 보정</label>
        <div className="flex flex-wrap gap-3">
          <button className="btn btn-primary flex-1" disabled={!canRead} onClick={read}>{busy ? "검사 중" : "현재 영상 OCR 검사"}</button>
          <button className="btn btn-outline flex-1" disabled={locked || busy} onClick={save}>보정값 저장</button>
        </div>
        {error && <p role="alert" className="text-lg font-bold text-danger">{error}</p>}
        {saved && <p role="status" className="text-lg font-bold text-ok">{saved}</p>}
        {result && <div className="space-y-3 rounded-xl border border-line p-4">
          {result.error && <p role="status" className="text-xl font-bold text-danger">{result.error}</p>}
          {result.reads.map((read, i) => <div key={i} className="space-y-3">
            {read.barcode && <p className="text-lg font-bold">바코드 {read.barcode}</p>}
            {read.lines.map((line, j) => <div key={j} className="rounded-xl border border-line p-3">
              <img src={line.preview} alt="자동 검출한 글자 줄" className="max-h-72 w-full rounded-lg bg-white object-contain"/>
              <p className="break-all text-3xl font-extrabold">{line.text || "문자 미검출"}</p>
              <p className="text-lg font-bold">인식 신뢰도 {(line.confidence * 100).toFixed(1)}%</p>
            </div>)}
          </div>)}
          {!result.error && result.reads.every(read => !read.lines.length) && <p className="text-xl font-bold">글자를 찾지 못했습니다</p>}
          <p className="text-lg font-bold">프레임 복사 {result.capture_ms.toFixed(1)} ms</p>
          <p className="text-lg font-bold">모델 준비 {result.ms_model_load.toFixed(1)} ms, 바코드 검출 {result.ms_barcode.toFixed(1)} ms, OCR {result.ms_ocr.toFixed(1)} ms</p>
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
