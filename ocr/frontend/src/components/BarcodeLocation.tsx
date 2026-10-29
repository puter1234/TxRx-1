export type Locator = "yolo26" | "stripes" | "opencv";
export type LocationDiagnostics = {
  tags?: { roi: number[] }[];
  texts?: { quad: number[][] }[];
  locator?: Locator; source_width?: number; source_height?: number;
  detection_width?: number; detection_height?: number;
  ocr_preprocessing?: { mode: string; gain: number; width: number; height: number; ms: number };
  regions?: { quad: number[][]; stage: string }[];
  stages: { stage: string; candidates: number; detect_ms: number;
    attempted: number; decoded: number; decode_ms: number;
    preprocess_ms?: number; refine_ms?: number; working_width?: number; working_height?: number;
    tag_count?: number; tag_ms?: number; segment_ms?: number; text_ms?: number }[];
};

export function LocatorSelect({ value, onChange, disabled = false }: {
  value: Locator; onChange: (value: Locator) => void; disabled?: boolean;
}) {
  return <label className="block space-y-2 text-lg font-bold">바코드 위치 검출
    <select aria-label="바코드 위치 검출" className="field block w-full" value={value} disabled={disabled} onChange={e => onChange(e.target.value as Locator)}>
      <option value="yolo26">모델 검출</option>
      <option value="stripes">줄무늬 검출</option>
      <option value="opencv">기존 검출</option>
    </select>
  </label>;
}

export function BarcodeOverlay({ diagnostics, showAll = false, selected = 0 }: { diagnostics?: LocationDiagnostics; showAll?: boolean; selected?: number }) {
  if (!diagnostics?.source_width || !diagnostics.source_height || (!showAll && !diagnostics.regions?.length)) return null;
  return <svg aria-label="검출한 바코드 위치" role="img" className="pointer-events-none absolute inset-0 z-10 h-full w-full"
    viewBox={`0 0 ${diagnostics.source_width} ${diagnostics.source_height}`} preserveAspectRatio="xMidYMid meet">
    {showAll && diagnostics.tags?.map((tag, i) => {
      const sx = diagnostics.source_width! / (diagnostics.detection_width || diagnostics.source_width!);
      const sy = diagnostics.source_height! / (diagnostics.detection_height || diagnostics.source_height!);
      const [x1,y1,x2,y2] = tag.roi;
      return <rect key={"tag" + i} x={x1*sx} y={y1*sy} width={(x2-x1)*sx} height={(y2-y1)*sy}
        fill="none" stroke="#2563eb" strokeWidth={2} vectorEffect="non-scaling-stroke"/>;
    })}
    {showAll && diagnostics.texts?.map((text, i) => <polygon key={"text" + i} points={text.quad.map(point => point.join(",")).join(" ")}
      fill="none" stroke="#f97316" strokeWidth={2} vectorEffect="non-scaling-stroke"/>)}
    {diagnostics.regions?.map((region, i) => {
      const size = Math.max(16, diagnostics.source_width! / 65);
      const x = Math.max(0, Math.min(...region.quad.map(point => point[0])));
      const y = Math.max(size, Math.min(...region.quad.map(point => point[1])) - size / 4);
      return <g key={i} aria-label={`바코드 ${i + 1}`}>
        <polygon points={region.quad.map(point => point.join(",")).join(" ")}
          fill="#16a34a" fillOpacity={selected === i ? .2 : .06} stroke="#22c55e"
          strokeWidth={selected === i ? 4 : 2} vectorEffect="non-scaling-stroke"/>
        <text x={x} y={y} fontSize={size} fontWeight={600} fill="white" stroke="#14532d"
          strokeWidth={3} paintOrder="stroke" vectorEffect="non-scaling-stroke">{i + 1}</text>
      </g>;
    })}
  </svg>;
}

export function LocationSummary({ diagnostics }: { diagnostics?: LocationDiagnostics }) {
  if (!diagnostics) return null;
  const rows = diagnostics.stages.filter(row => row.stage === "stripes" || row.stage === "yolo26");
  return <details className="space-y-1 text-base"><summary className="cursor-pointer font-bold">검출 상세</summary>
    <p>검출 위치 {diagnostics.regions?.length ?? 0}곳{diagnostics.regions?.length ? " (사진의 초록색 테두리)" : ""}</p>
    {rows.map((row, i) => <p key={i}>탐색 {row.working_width} x {row.working_height}, 전처리 {(row.preprocess_ms ?? 0).toFixed(1)} ms,
      위치 검출 합계 {row.detect_ms.toFixed(1)} ms</p>)}
    {rows.filter(row => row.stage === "yolo26").map((row, i) => <p key={i}>택 {row.tag_count}개,
      택 검출 {(row.tag_ms ?? 0).toFixed(1)} ms, 바코드 분할 {(row.segment_ms ?? 0).toFixed(1)} ms,
      문자 위치 {(row.text_ms ?? 0).toFixed(1)} ms</p>)}
  </details>;
}
