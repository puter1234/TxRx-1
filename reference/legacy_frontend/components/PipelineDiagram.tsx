import type { NodeState, PipelineNode } from '../lib/types'

const COLOR: Record<NodeState, string> = {
  idle: '#8d99ab',
  active: '#e8a200',
  ok: '#12934f',
  fault: '#d92c2c',
}
const TINT: Record<NodeState, string> = {
  idle: '#f1f4f8',
  active: '#fdf3d9',
  ok: '#e7f6ee',
  fault: '#fdeaea',
}
const WORD: Record<NodeState, string> = {
  idle: '대기',
  active: '진행',
  ok: '완료',
  fault: '오류',
}

function Badge({ cx, y, state }: { cx: number; y: number; state: NodeState }) {
  return (
    <g>
      <rect x={cx - 32} y={y} width={64} height={27} rx={13.5} fill={COLOR[state]} />
      <text x={cx} y={y + 19} textAnchor="middle" fontSize={14} fontWeight={800} fill="#ffffff">
        {WORD[state]}
      </text>
    </g>
  )
}

function Label({ cx, text }: { cx: number; text: string }) {
  return (
    <text x={cx} y={292} textAnchor="middle" fontSize={17} fontWeight={700} fill="#101828">
      {text}
    </text>
  )
}

export default function PipelineDiagram({ nodes }: { nodes?: Record<PipelineNode, NodeState> }) {
  const st = (k: PipelineNode): NodeState => nodes?.[k] ?? 'idle'
  const cls = (k: PipelineNode) => (st(k) === 'active' ? 'node-active' : undefined)

  return (
    <svg viewBox="0 0 1040 340" className="w-full" role="img" aria-label="전체 파이프라인 도식">
      {/* 바닥 */}
      <line x1={10} y1={312} x2={1030} y2={312} stroke="#d0d7e2" strokeWidth={2} />

      {/* 컨베이어 벨트 */}
      <g className={cls('conveyor')}>
        <rect x={130} y={210} width={780} height={26} rx={7} fill="#3d485f" stroke={COLOR[st('conveyor')]} strokeWidth={3} />
        {Array.from({ length: 14 }, (_, i) => (
          <circle key={i} cx={158 + i * 56} cy={248} r={8} fill="#98a3b8" />
        ))}
        <rect x={190} y={256} width={10} height={54} fill="#b7c0cf" />
        <rect x={840} y={256} width={10} height={54} fill="#b7c0cf" />
      </g>

      {/* 이동 중인 의류 (컨베이어 가동 시) */}
      {st('conveyor') === 'active' && (
        <g className="belt-item">
          <rect x={134} y={170} width={64} height={38} rx={6} fill="none" stroke="#2f6bff" strokeWidth={2} strokeDasharray="6 4" />
          <rect x={140} y={176} width={52} height={26} rx={6} fill="#22437a" />
        </g>
      )}

      {/* 투입부 */}
      <g className={cls('infeed')}>
        <polygon points="25,150 130,206 130,236 25,180" fill={TINT[st('infeed')]} stroke={COLOR[st('infeed')]} strokeWidth={3} />
        <rect x={38} y={118} width={54} height={13} rx={4} fill="#22437a" />
        <rect x={34} y={132} width={54} height={13} rx={4} fill="#31599c" />
        <rect x={42} y={104} width={54} height={13} rx={4} fill="#31599c" />
      </g>
      <Label cx={75} text="투입부" />
      <Badge cx={75} y={300} state={st('infeed')} />

      <Label cx={215} text="컨베이어" />
      <Badge cx={215} y={300} state={st('conveyor')} />

      {/* 광센서 */}
      <g className={cls('sensor')}>
        <rect x={352} y={112} width={6} height={98} fill="#b7c0cf" />
        <rect x={298} y={112} width={54} height={28} rx={6} fill={TINT[st('sensor')]} stroke={COLOR[st('sensor')]} strokeWidth={3} />
        <line x1={322} y1={140} x2={322} y2={208} stroke={COLOR[st('sensor')]} strokeWidth={3} strokeDasharray="7 6" />
        <circle cx={322} cy={146} r={4} fill={COLOR[st('sensor')]} />
      </g>
      <Label cx={325} text="광센서" />
      <Badge cx={325} y={300} state={st('sensor')} />

      {/* 카메라 (OCR·바코드) */}
      <g className={cls('camera')}>
        <rect x={610} y={86} width={8} height={124} fill="#b7c0cf" />
        <rect x={560} y={90} width={58} height={8} fill="#b7c0cf" />
        <rect x={530} y={74} width={64} height={36} rx={8} fill={TINT[st('camera')]} stroke={COLOR[st('camera')]} strokeWidth={3} />
        <circle cx={562} cy={112} r={7} fill={COLOR[st('camera')]} />
        <polygon points="548,122 576,122 600,206 524,206" fill={TINT[st('camera')]} opacity={0.55} stroke={COLOR[st('camera')]} strokeWidth={2} strokeDasharray="5 5" />
      </g>
      <Label cx={562} text="카메라 (OCR·바코드)" />
      <Badge cx={562} y={300} state={st('camera')} />

      {/* RFID 리더 */}
      <g className={cls('rfid')}>
        <rect x={766} y={144} width={8} height={66} fill="#b7c0cf" />
        <rect x={740} y={96} width={60} height={48} rx={8} fill={TINT[st('rfid')]} stroke={COLOR[st('rfid')]} strokeWidth={3} />
        <path d="M 758,158 A 12,12 0 0 0 782,158" fill="none" stroke={COLOR[st('rfid')]} strokeWidth={3} />
        <path d="M 748,166 A 22,22 0 0 0 792,166" fill="none" stroke={COLOR[st('rfid')]} strokeWidth={3} />
        <path d="M 738,174 A 32,32 0 0 0 802,174" fill="none" stroke={COLOR[st('rfid')]} strokeWidth={3} />
      </g>
      <Label cx={770} text="RFID 리더" />
      <Badge cx={770} y={300} state={st('rfid')} />

      {/* 적재부 */}
      <g className={cls('outfeed')}>
        <path d="M 925,152 L 925,232 L 1025,232 L 1025,152" fill={TINT[st('outfeed')]} stroke={COLOR[st('outfeed')]} strokeWidth={3} />
        <rect x={940} y={210} width={70} height={12} rx={4} fill="#22437a" />
        <rect x={944} y={196} width={70} height={12} rx={4} fill="#31599c" />
        <rect x={936} y={182} width={70} height={12} rx={4} fill="#4a76c4" />
      </g>
      <Label cx={975} text="적재부" />
      <Badge cx={975} y={300} state={st('outfeed')} />
    </svg>
  )
}

export function PipelineLegend() {
  const items: { state: NodeState; label: string }[] = [
    { state: 'idle', label: '대기' },
    { state: 'active', label: '진행 중' },
    { state: 'ok', label: '완료' },
    { state: 'fault', label: '오류 · 정지' },
  ]
  return (
    <div className="flex items-center gap-3">
      {items.map((it) => (
        <span key={it.state} className="flex items-center gap-2 rounded-full border border-line bg-white px-3.5 py-1.5 text-[15px] font-bold">
          <span className="h-3.5 w-3.5 rounded-full" style={{ background: COLOR[it.state] }} />
          {it.label}
        </span>
      ))}
    </div>
  )
}
