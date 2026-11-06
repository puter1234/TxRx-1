import { useRef, useState } from "react";

type Flow = Record<string, any>;
type Size = { width: number; height: number };

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// The detection area, detected boxes and counting line over a camera image shown
// with object-contain, in the frame's own 0~1 coordinates as the counter uses them.
// With onLine the line can be dragged.
export default function CountOverlay({
  flow,
  size,
  boxes = [],
  onLine,
}: {
  flow: Flow;
  size: Size;
  boxes?: number[][];
  onLine?: (line: number) => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);
  const { width: w, height: h } = size;
  const vertical = flow.axis === "x";
  const at = (vertical ? w : h) * flow.line;
  const place = (e: React.PointerEvent) => {
    if (!dragging.current || !onLine || !svg.current) return;
    // The image is letterboxed inside the box; map the pointer onto the frame.
    const r = svg.current.getBoundingClientRect();
    const scale = Math.min(r.width / w, r.height / h);
    const x = (e.clientX - r.left - (r.width - w * scale) / 2) / (w * scale);
    const y = (e.clientY - r.top - (r.height - h * scale) / 2) / (h * scale);
    onLine(Math.round(clamp(vertical ? x : y, 0.02, 0.98) * 100) / 100);
  };
  const drag = onLine && {
    onPointerDown: (e: React.PointerEvent) => {
      (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
      dragging.current = true;
    },
    onPointerMove: place,
    onPointerUp: () => (dragging.current = false),
    onPointerCancel: () => (dragging.current = false),
    style: { pointerEvents: "auto" as const, cursor: vertical ? "ew-resize" : "ns-resize" },
  };
  const [x1, y1, x2, y2] = vertical ? [at, 0, at, h] : [0, at, w, at];
  const roi = flow.roi as number[] | undefined;
  return (
    <svg
      ref={svg}
      aria-label="검출 위치와 계수선"
      className="pointer-events-none absolute inset-0 h-full w-full"
      style={onLine ? { touchAction: "none" } : undefined}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {roi && (roi[0] > 0 || roi[1] > 0 || roi[2] < 1 || roi[3] < 1) && (
        <rect x={roi[0] * w} y={roi[1] * h} width={roi[2] * w} height={roi[3] * h} fill="none" stroke="#22c55e"
          strokeWidth={3} strokeDasharray="12 8" vectorEffect="non-scaling-stroke" />
      )}
      {boxes.map(([a, b, c, d], i) => (
        <rect key={i} x={a * w} y={b * h} width={(c - a) * w} height={(d - b) * h} fill="none" stroke="#22c55e"
          strokeWidth={4} vectorEffect="non-scaling-stroke" />
      ))}
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#facc15" strokeWidth={4} vectorEffect="non-scaling-stroke" />
      {drag && (
        <g aria-label="계수선 이동" {...drag}>
          <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={56} vectorEffect="non-scaling-stroke" />
          <circle cx={(x1 + x2) / 2} cy={(y1 + y2) / 2} r={Math.min(w, h) * 0.04} fill="#facc15" />
        </g>
      )}
    </svg>
  );
}

// The size of the picture an <img> shows, kept as one object while it stays the same.
export function useImageSize() {
  const [size, setSize] = useState<Size | null>(null);
  const onLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const { naturalWidth: width, naturalHeight: height } = e.currentTarget;
    if (width && height) setSize((old) => (old?.width === width && old.height === height ? old : { width, height }));
  };
  return [size, onLoad] as const;
}

// The counting line's position as a whole percentage of the frame.
export function LinePercent({ value, onChange }: { value: number | ""; onChange: (line: number | "") => void }) {
  return (
    <label className="block text-xl font-extrabold">
      판정선 위치 (%)
      <input
        aria-label="판정선 위치"
        className="field mt-2"
        type="number"
        min={1}
        max={99}
        step={1}
        value={value === "" ? "" : Math.round(value * 100)}
        onChange={(e) => onChange(e.target.value === "" ? "" : clamp(Math.round(Number(e.target.value)), 1, 99) / 100)}
      />
    </label>
  );
}
