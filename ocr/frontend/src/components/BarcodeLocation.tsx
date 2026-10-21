export type Locator = "yolo26" | "stripes" | "opencv";
export type LocationDiagnostics = {
  locator?: Locator; source_width?: number; source_height?: number;
  detection_width?: number; detection_height?: number;
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
      <option value="yolo26">택 검출과 바코드 분할</option>
      <option value="stripes">줄무늬 검출 (G 채널)</option>
      <option value="opencv">기존 OpenCV 검출</option>
    </select>
  </label>;
}

export function BarcodeOverlay({ diagnostics }: { diagnostics?: LocationDiagnostics }) {
  if (!diagnostics?.source_width || !diagnostics.source_height || !diagnostics.regions?.length) return null;
  return <svg aria-label="검출한 바코드 위치" role="img" className="pointer-events-none absolute inset-0 h-full w-full"
    viewBox={`0 0 ${diagnostics.source_width} ${diagnostics.source_height}`} preserveAspectRatio="xMidYMid meet">
    {diagnostics.regions.map((region, i) => <polygon key={i} points={region.quad.map(point => point.join(",")).join(" ")}
      fill="none" stroke="#16a34a" strokeWidth={2} vectorEffect="non-scaling-stroke"/>)}
  </svg>;
}

export function LocationSummary({ diagnostics }: { diagnostics?: LocationDiagnostics }) {
  if (!diagnostics) return null;
  const rows = diagnostics.stages.filter(row => row.stage === "stripes" || row.stage === "yolo26");
  return <div className="space-y-1 text-base">
    <p>{diagnostics.locator === "yolo26" ? "택 검출 후 바코드 분할" : diagnostics.locator === "stripes" ? "G 채널 추출 후 국소 명암 정규화" : "기존 OpenCV 검출"}</p>
    {diagnostics.locator === "yolo26" && <p>촬영 원본 {diagnostics.source_width} x {diagnostics.source_height}, 위치 탐색 {diagnostics.detection_width} x {diagnostics.detection_height}. 글자는 촬영 원본에서 추출합니다.</p>}
    <p>검출 위치 {diagnostics.regions?.length ?? 0}곳{diagnostics.regions?.length ? " (사진의 초록색 테두리)" : ""}</p>
    {rows.map((row, i) => <p key={i}>탐색 {row.working_width} x {row.working_height}, 전처리 {(row.preprocess_ms ?? 0).toFixed(1)} ms,
      위치 검출 합계 {row.detect_ms.toFixed(1)} ms</p>)}
    {rows.filter(row => row.stage === "yolo26").map((row, i) => <p key={i}>택 {row.tag_count}개,
      택 검출 {(row.tag_ms ?? 0).toFixed(1)} ms, 바코드 분할 {(row.segment_ms ?? 0).toFixed(1)} ms,
      문자 위치 {(row.text_ms ?? 0).toFixed(1)} ms</p>)}
  </div>;
}
