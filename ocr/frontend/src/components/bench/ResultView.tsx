import { useEffect, useState } from "react";
import InspectionImage from "../InspectionImage";
import { LocationSummary, type LocationDiagnostics } from "../BarcodeLocation";

export type Shown = {
  title: string;
  url: string;
  download?: string;
  diagnostics?: LocationDiagnostics;
  lines?: { text: string; image?: string; confidence?: number }[];
  note?: string;
  size?: { width: number; height: number };
  // The full OCR result, kept for the details section and its report download.
  report?: Record<string, any>;
};

const STAGES: Record<string, string> = {
  yolo26: "택 검출과 바코드 분할",
  stripes: "줄무늬 위치 검출",
  small: "축소본 위치 검출", full: "원본 위치 검출", tiled: "분할 위치 검출", "whole-image": "원본 전체 판독",
};
const ms = (v: unknown) => (typeof v === "number" ? `${v.toFixed(1)} ms` : "");

// A photo, text reading or process-test frame, shown in a sheet over the test screen.
export default function ResultView({ shown }: { shown: Shown }) {
  const [actual, setActual] = useState(false);
  // Only the latest reading's photo is kept; an older one is gone.
  const [gone, setGone] = useState(false);
  useEffect(() => setGone(false), [shown.url]);
  return (
    <section aria-label="결과" className="space-y-4">
      {shown.note && <p role="alert" className="text-[24px] font-extrabold text-danger">{shown.note}</p>}
      {typeof shown.report?.after_trigger_ms === "number" && (
        <p className="text-[24px] font-extrabold">감지 후 {Math.round(shown.report.after_trigger_ms)} ms</p>
      )}
      {shown.lines && (
        <div className="space-y-3">
          {shown.lines.map((line, i) => (
            <div key={i} className="space-y-2 rounded-2xl border-2 border-line p-3">
              {line.image && <img src={line.image} alt="읽은 글자 부분" className="max-h-32 max-w-full rounded-lg bg-white object-contain" />}
              <p className="break-all text-[40px] font-black">{line.text || "못 읽음"}</p>
              {typeof line.confidence === "number" && (
                <p className="text-[20px] font-bold text-ink-700">신뢰도 {(line.confidence * 100).toFixed(1)}%</p>
              )}
            </div>
          ))}
          {!shown.lines.length && <p className="text-[32px] font-black text-danger">글자 못 찾음</p>}
        </div>
      )}
      {shown.url && (
        <>
          <div className="flex justify-end gap-2">
            <button className={"btn btn-sm " + (actual ? "btn-primary" : "btn-outline")} aria-pressed={actual} onClick={() => setActual((v) => !v)}>
              {actual ? "화면에 맞춤" : "원본 크기"}
            </button>
            {shown.download && <a className="btn btn-sm btn-outline" href={shown.download} download>원본 저장</a>}
          </div>
          {shown.diagnostics ? (
            <InspectionImage key={shown.url} src={shown.url} diagnostics={shown.diagnostics} actualSize={actual} />
          ) : gone ? (
            <p className="rounded-xl bg-ink-900 p-10 text-center text-[28px] font-black text-white">사진 없음</p>
          ) : (
            <div className="max-h-[62vh] overflow-auto rounded-xl bg-ink-900">
              <img key={shown.url} src={shown.url} alt={shown.title} className={actual ? "max-w-none" : "max-h-[62vh] w-full object-contain"}
                style={actual && shown.size ? { width: shown.size.width, height: shown.size.height } : undefined}
                onError={() => setGone(true)} />
            </div>
          )}
        </>
      )}
      {shown.report && <ReadDetails report={shown.report} />}
    </section>
  );
}

function ReadDetails({ report }: { report: Record<string, any> }) {
  const diagnostics = report.barcode_diagnostics;
  const save = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = "barcode-report.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  };
  return (
    <details className="space-y-3 rounded-2xl border-2 border-line p-4 text-[20px] font-bold">
      <summary className="cursor-pointer text-[22px] font-extrabold">판독 상세</summary>
      {report.frame_width && <p>{report.frame_width} × {report.frame_height}</p>}
      {typeof report.capture_ms === "number" && <p>프레임 복사 {ms(report.capture_ms)}</p>}
      {typeof report.ms_ocr === "number" && (
        <p>{([["모델 준비", report.ms_model_load], ["위치 검출과 정렬", report.ms_barcode], ["OCR", report.ms_ocr]] as const)
          .filter(([, v]) => typeof v === "number").map(([name, v]) => `${name} ${ms(v)}`).join(", ")}</p>
      )}
      {report.ocr_device && <p>{String(report.ocr_device).startsWith("cuda") ? `OCR GPU 사용: ${report.ocr_gpu_name || report.ocr_device}` : "OCR CPU 사용 중"}</p>}
      {diagnostics?.stages && <LocationSummary diagnostics={diagnostics} />}
      {!!diagnostics?.stages?.length && (
        <table className="w-full text-left">
          <thead><tr><th>단계</th><th>위치 후보</th><th>위치 검출</th></tr></thead>
          <tbody>
            {diagnostics.stages.map((row: any, i: number) => (
              <tr key={i}><td className="py-1">{STAGES[row.stage] || row.stage}</td><td>{row.candidates}</td><td>{ms(row.detect_ms)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {diagnostics?.runtime && <p>OpenCV {diagnostics.runtime.opencv}, ZXing {diagnostics.runtime.zxing}</p>}
      <button className="btn btn-sm btn-outline" onClick={save}>판독 정보 저장</button>
    </details>
  );
}
