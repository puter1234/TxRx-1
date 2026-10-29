import { useState } from "react";
import { BarcodeOverlay, type LocationDiagnostics } from "./BarcodeLocation";

type Props = { src: string; diagnostics?: LocationDiagnostics; actualSize?: boolean; alt?: string };
export default function InspectionImage({ src, diagnostics, actualSize = false, alt = "검사에 사용한 원본 사진" }: Props) {
  const [mode, setMode] = useState("original");
  const [input, setInput] = useState("tag_input:0");
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState(0);
  const inputs = diagnostics?.locator === "yolo26" ? [
    { id: "tag_input:0", label: "택 검출 입력" },
    ...(diagnostics.tags || []).map((_, i) => ({ id: `barcode_input:${i}`, label: `바코드 입력 ${i + 1}` })),
    ...(diagnostics.ocr_preprocessing ? [{ id: "ocr_input:0", label: "OCR 전처리" }] : []),
  ] : [];
  const regions = diagnostics?.regions || [];
  const barcodeUrl = new URL(src, window.location.origin);
  barcodeUrl.searchParams.set("view", "barcode_crop");
  barcodeUrl.searchParams.set("region", String(selected));
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
    {mode === "detections" && <div className="flex flex-wrap items-center gap-2">
      <span>바코드 {regions.length}개</span>
      {regions.map((_, i) => <button key={i} className={"btn btn-sm " + (selected === i ? "btn-primary" : "btn-outline")}
        aria-pressed={selected === i} onClick={() => { setSelected(i); setFailed(false); }}>바코드 {i + 1}</button>)}
    </div>}
    <div className="max-h-[600px] overflow-auto rounded-lg bg-ink-900">
      <div className={actualSize ? "relative w-max" : "relative"}>
        <img key={url.href} src={url.pathname + url.search} alt={mode === "processed" ? "모델 입력 전처리 결과" : alt}
          onError={() => setFailed(true)} className={actualSize ? "max-w-none" : "max-h-[600px] w-full object-contain"}/>
        {mode === "detections" && <BarcodeOverlay diagnostics={diagnostics} showAll selected={selected}/>}
      </div>
    </div>
    {mode === "detections" && regions.length > 0 && <figure className="space-y-2">
      <figcaption>바코드 {selected + 1} 확대</figcaption>
      <div className="overflow-auto rounded-lg bg-ink-900 p-2">
        <img key={barcodeUrl.href} src={barcodeUrl.pathname + barcodeUrl.search} alt={`검출된 바코드 ${selected + 1}`}
          onError={() => setFailed(true)} className="mx-auto max-h-64 max-w-full object-contain"/>
      </div>
    </figure>}
    {failed && <p role="alert">사진 없음</p>}
    {mode === "detections" && !regions.length && <p>검출된 바코드 없음</p>}
  </div>;
}
