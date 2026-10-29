import { useRef } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from "lucide-react";
import { useApp } from "../lib/store";
import { useCameraPreview } from "./useCameraPreview";

type Roi = [number, number, number, number];
type Drag = { mode: "move" | "resize" | "line"; x: number; y: number; roi: Roi; line: number };

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const round = (v: number) => Math.round(v * 100) / 100;

// Area and counting line share the counter's frame-normalized coordinates.
export default function RoiEditor({
  roi,
  line,
  axis,
  direction,
  onChange,
}: {
  roi: Roi;
  line: number;
  axis: "x" | "y";
  direction: 1 | -1;
  onChange: (patch: { roi?: Roi; line?: number }) => void;
}) {
  const connected = useApp((s) => s.equipment?.camera?.connected === true);
  const { url } = useCameraPreview(connected);
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const point = (e: React.PointerEvent) => {
    const r = box.current!.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
  const begin = (mode: Drag["mode"]) => (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const [x, y] = point(e);
    drag.current = { mode, x, y, roi: [...roi] as Roi, line };
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const [x, y] = point(e);
    const dx = x - d.x, dy = y - d.y;
    const [rx, ry, rw, rh] = d.roi;
    if (d.mode === "move")
      onChange({ roi: [round(clamp(rx + dx, 0, 1 - rw)), round(clamp(ry + dy, 0, 1 - rh)), rw, rh] });
    else if (d.mode === "resize")
      onChange({ roi: [rx, ry, round(clamp(rw + dx, 0.05, 1 - rx)), round(clamp(rh + dy, 0.05, 1 - ry))] });
    else onChange({ line: round(clamp(axis === "x" ? x : y, 0.02, 0.98)) });
  };
  const end = () => {
    drag.current = null;
  };
  const Arrow = axis === "y" ? (direction === 1 ? ArrowDown : ArrowUp) : direction === 1 ? ArrowRight : ArrowLeft;
  const [x, y, w, h] = roi;
  return (
    <div
      ref={box}
      aria-label="검출 영역과 계수선"
      className="relative aspect-[4/3] w-full touch-none select-none overflow-hidden rounded-2xl bg-ink-900"
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
    >
      {url ? (
        <img src={url} alt="" className="pointer-events-none h-full w-full object-fill" draggable={false} />
      ) : (
        <span className="absolute inset-0 flex items-center justify-center text-[28px] font-extrabold text-white/70">카메라 꺼짐</span>
      )}
      <div
        className="absolute cursor-move border-4 border-[#22c55e] bg-[#22c55e]/10"
        style={{ left: x * 100 + "%", top: y * 100 + "%", width: w * 100 + "%", height: h * 100 + "%" }}
        onPointerDown={begin("move")}
      >
        <span
          aria-label="영역 크기"
          className="absolute -bottom-5 -right-5 h-10 w-10 cursor-nwse-resize rounded-lg border-4 border-white bg-[#22c55e]"
          onPointerDown={begin("resize")}
        />
      </div>
      <div
        aria-label="계수선"
        className={"absolute flex items-center justify-center " + (axis === "y" ? "inset-x-0 h-10 -translate-y-1/2 cursor-ns-resize" : "inset-y-0 w-10 -translate-x-1/2 cursor-ew-resize")}
        style={axis === "y" ? { top: line * 100 + "%" } : { left: line * 100 + "%" }}
        onPointerDown={begin("line")}
      >
        <span className={"bg-[#facc15] " + (axis === "y" ? "h-1.5 w-full" : "h-full w-1.5")} />
        <span className="absolute flex h-14 w-14 items-center justify-center rounded-full bg-[#facc15] text-ink-900">
          <Arrow size={36} strokeWidth={3} />
        </span>
      </div>
    </div>
  );
}
