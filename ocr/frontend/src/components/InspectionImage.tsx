import { useState } from "react";
import { BarcodeOverlay, type LocationDiagnostics } from "./BarcodeLocation";

type Props = { src: string; diagnostics?: LocationDiagnostics; actualSize?: boolean; alt?: string };
export default function InspectionImage({ src, diagnostics, actualSize = false, alt = "검사에 사용한 원본 사진" }: Props) {
  const [mode, setMode] = useState("original");
  const [input, setInput] = useState("tag_input:0");
  const [failed, setFailed] = useState(false);
  const inputs = diagnostics?.locator === "yolo26" ? [
    { id: "tag_input:0", label: "택 검출 입력" },
    ...(diagnostics.tags || []).map((_, i) => ({ id: `barcode_input:${i}`, label: `바코드 입력 ${i + 1}` })),
  ] : [];
  const url = new URL(src, window.location.origin);
  if (mode === "processed") {
    const [view, region] = input.split(":");
    url.searchParams.set("view", view); url.searchParams.set("region", region);
  }
  const change = (next: string) => { setMode(next); setFailed(false); };
  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2" role="group" aria-label="검사 사진 보기">
      {[["original", "원본"], ["processed", "전처리"], ["detections", "검출 결과"]].map(([id, label]) =>
        <button key={id} className={"btn btn-sm " + (mode === id ? "btn-primary" : "btn-outline")}
          aria-pressed={mode === id} disabled={id === "processed" && !inputs.length} onClick={() => change(id)}>{label}</button>)}
    </div>
    {mode === "processed" && <div className="flex flex-wrap gap-2" role="group" aria-label="전처리 단계">
      {inputs.map(item => <button key={item.id} className={"btn btn-sm " + (input === item.id ? "btn-primary" : "btn-outline")}
        aria-pressed={input === item.id} onClick={() => { setInput(item.id); setFailed(false); }}>{item.label}</button>)}
    </div>}
    {mode === "detections" && <p className="text-sm">택: 파랑 / 바코드: 초록 / 문자: 주황</p>}
    <div className="max-h-[600px] overflow-auto rounded-lg bg-ink-900">
      <div className={actualSize ? "relative w-max" : "relative"}>
        <img key={url.href} src={url.pathname + url.search} alt={mode === "processed" ? "모델 입력 전처리 결과" : alt}
          onError={() => setFailed(true)} className={actualSize ? "max-w-none" : "max-h-[600px] w-full object-contain"}/>
        {mode === "detections" && <BarcodeOverlay diagnostics={diagnostics} showAll/>}
      </div>
    </div>
    {failed && <p role="alert">사진을 불러오지 못했습니다.</p>}
    {mode === "detections" && !diagnostics?.regions?.length && !diagnostics?.tags?.length && <p>검출된 영역이 없습니다.</p>}
  </div>;
}
