import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, CreditCard, ScanText, Settings } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended, reportError } from "../lib/station";
import Help from "../components/Help";
import { Equipment as EquipmentDetails } from "../station/StationApp";
import { BenchHeader, CameraTest, OutputTests, SensorTest, useBench } from "../components/DeviceTests";

type OcrLine = {
  text: string; confidence: number; min_char: number; ms: number;
  crop_width: number; crop_height: number; preview: string;
  chars: { ch: string; p: number }[];
};
type OcrResult = { ok: boolean; mode?: "ocr_only"; reads: { barcode: string | null; barcode_format: string | null;
  verdict: string; verdict_label: string; verdict_detail: string; stage: string; lines: OcrLine[] }[];
  error: string | null; capture_ms: number; processing_ms: number;
  ms_model_load: number; ms_barcode: number; ms_ocr: number;
  frame_width?: number; frame_height?: number; preview_url?: string; original_url?: string;
  barcode_diagnostics?: { status: string; decoded: number; prepare_ms: number; align_ms: number;
    stages: { stage: string; candidates: number; attempted: number; decoded: number; detect_ms: number; decode_ms: number }[];
    runtime: { opencv: string; zxing: string; python: string; source: string; report_version: number } } };
const barcodeStages: Record<string, string> = {
  small: "축소본 위치 검출", full: "원본 위치 검출", tiled: "분할 위치 검출", "whole-image": "원본 전체 판독",
};
export function OcrLiveTest({ bench, locked, checkOcr, ocr, ocrBusy }: {
  bench: ReturnType<typeof useBench>; locked: boolean;
  checkOcr: () => void; ocr: { ok: boolean; detail: string } | null; ocrBusy: boolean;
}) {
  const connected = bench.state?.camera?.connected === true;
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<OcrResult | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
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
    try { setResult(await api<OcrResult>("/bench/ocr/read", {})); }
    catch (e) { setError(e instanceof Error ? e.message : "OCR 검사 실패"); }
    finally { setBusy(false); await bench.refresh().catch(() => {}); }
  };
  const canRead = connected && !!url && !locked && !busy;
  return <section className="card space-y-5 p-5">
    <div className="flex items-center gap-3"><ScanText size={26}/><h2 className="text-xl font-extrabold">OCR 촬영 시험</h2>
      <Help text="바코드 위치를 기준으로 택을 정렬하고 주변 인쇄 문자를 읽습니다. 바코드 값은 판독하지 않습니다. 읽은 문자와 사진을 확인하는 시험이며 목표값 합격 판정은 작업 검사에서 진행합니다."/></div>
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
        <div className="flex flex-wrap gap-3">
          <button className="btn btn-primary flex-1" disabled={!canRead} onClick={read}>{busy ? "검사 중" : "현재 영상 OCR 검사"}</button>
        </div>
        {error && <p role="alert" className="text-lg font-bold text-danger">{error}</p>}
        {result && <div className="space-y-3 rounded-xl border border-line p-4">
          <p role="status" className={"text-2xl font-extrabold " + (result.ok ? "text-ok" : "text-danger")}>
            {result.mode === "ocr_only" ? (result.ok ? "문자 읽음" : "문자 미검출") : (result.ok ? "검사 통과" : "검사 실패")}
          </p>
          {result.error && <p role="status" className="text-xl font-bold text-danger">{result.error}</p>}
          {result.preview_url && <div className="space-y-3">
            <div className="flex items-center gap-2"><h3 className="text-xl font-bold">검사한 사진</h3>
              <Help text="이번 판독에 실제로 사용한 프레임입니다. 화면에서는 작게 표시하며 원본 사진 저장은 같은 프레임의 전체 해상도 PNG를 받습니다. 다음 검사 시 이전 사진은 교체됩니다."/></div>
            <img src={result.preview_url} alt="이번 검사에 사용한 사진" className="max-h-[520px] w-full rounded-lg bg-ink-900 object-contain"/>
            <p className="text-lg font-bold">{result.frame_width} × {result.frame_height}</p>
            <a className="btn btn-outline" href={result.original_url} download>검사 원본 사진 저장</a>
          </div>}
          {result.reads.map((read, i) => <div key={i} className="space-y-3">
            {result.mode !== "ocr_only" && <p className={"text-lg font-bold " + (read.verdict === "match" || read.verdict === "match_loose" ? "text-ok" : "text-danger")}>
              {read.verdict_label}{read.barcode ? `  바코드 ${read.barcode}` : ""}
            </p>}
            {read.verdict_detail && <p className="text-base font-bold">{read.verdict_detail}</p>}
            {read.lines.map((line, j) => <div key={j} className="rounded-xl border border-line p-3">
              <img src={line.preview} alt="자동 검출한 글자 줄" className="max-h-72 w-full rounded-lg bg-white object-contain"/>
              <p className="break-all text-3xl font-extrabold">{line.text || "문자 미검출"}</p>
              <p className="text-lg font-bold">인식 신뢰도 {(line.confidence * 100).toFixed(1)}%</p>
            </div>)}
          </div>)}
          {!result.error && result.reads.every(read => !read.lines.length) && <p className="text-xl font-bold">글자를 찾지 못했습니다</p>}
          <p className="text-lg font-bold">프레임 복사 {result.capture_ms.toFixed(1)} ms</p>
          <p className="text-lg font-bold">모델 준비 {result.ms_model_load.toFixed(1)} ms, {result.mode === "ocr_only" ? "위치 검출과 정렬" : "바코드 처리"} {result.ms_barcode.toFixed(1)} ms, OCR {result.ms_ocr.toFixed(1)} ms</p>
          {result.barcode_diagnostics && <details className="space-y-3">
            <summary className="cursor-pointer text-lg font-bold">판독 상세</summary>
            <div className="overflow-x-auto"><table className="w-full text-left text-lg">
              <thead><tr><th>단계</th><th>위치 후보</th>{result.mode !== "ocr_only" && <th>읽은 값</th>}<th>위치 검출</th>{result.mode !== "ocr_only" && <th>값 판독</th>}</tr></thead>
              <tbody>{result.barcode_diagnostics.stages.map((row, i) => <tr key={i}>
                <td className="py-2">{barcodeStages[row.stage] || row.stage}</td><td>{row.candidates}</td>{result.mode !== "ocr_only" && <td>{row.decoded}</td>}
                <td>{row.detect_ms.toFixed(1)} ms</td>{result.mode !== "ocr_only" && <td>{row.decode_ms.toFixed(1)} ms</td>}
              </tr>)}</tbody>
            </table></div>
            <p className="text-lg font-bold">흑백 변환 {result.barcode_diagnostics.prepare_ms.toFixed(1)} ms, OCR 영역 정렬 {result.barcode_diagnostics.align_ms.toFixed(1)} ms</p>
            <p className="text-lg">OpenCV {result.barcode_diagnostics.runtime.opencv}, ZXing {result.barcode_diagnostics.runtime.zxing}</p>
            <button className="btn btn-outline" onClick={() => {
              const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
              const href = URL.createObjectURL(blob), link = document.createElement("a");
              link.href = href; link.download = "barcode-report.json"; link.click();
              setTimeout(() => URL.revokeObjectURL(href), 1000);
            }}>판독 정보 저장</button>
          </details>}
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
