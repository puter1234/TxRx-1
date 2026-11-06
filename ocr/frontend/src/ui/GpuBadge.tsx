// TEMP: GPU indicator. Remove with `inference` in station/app.py and station/vision.py.
import { useApp } from "../lib/store";

export default function GpuBadge() {
  const d = useApp((s) => s.snapshot?.inference);
  const show = (v?: string | null) => v || "-";
  return (
    <span aria-label="추론 장치" className="rounded-2xl border-2 border-dashed border-ink-500 px-4 py-2 text-[22px] font-extrabold text-ink-700">
      OCR {show(d?.ocr)} · 글자찾기 {show(d?.detector)} · 와펜 {show(d?.wappen)}
    </span>
  );
}
