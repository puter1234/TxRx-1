import { Hand, Activity, Pause, AlertTriangle, CheckCircle2, OctagonX } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'

export default function StatusBanner() {
  const session = useApp((s) => s.server?.session)
  if (!session) return null

  const base = 'card flex items-center gap-4 p-5'

  if (session.status === 'running') {
    return (
      <div className={base + ' border-ok bg-ok-bg'}>
        <Activity size={34} className="animate-pulse text-ok" />
        <div>
          <div className="text-xl font-extrabold text-ok">
            {session.mode === 'condition' ? '정상 검사 진행 중' : '계수 진행 중'}
          </div>
          <div className="text-base font-semibold text-ink-700">의류 통과를 감지하고 있습니다</div>
        </div>
      </div>
    )
  }
  if (session.status === 'paused') {
    return (
      <div className={base + ' border-warn bg-warn-bg'}>
        <Pause size={34} className="text-warn" />
        <div>
          <div className="text-xl font-extrabold text-warn">일시정지됨</div>
          <div className="text-base font-semibold text-ink-700">재개 버튼을 눌러 계속하세요</div>
        </div>
      </div>
    )
  }
  if (session.status === 'mismatch') {
    const m = session.mismatch
    return (
      <div className={base + ' flex-col items-stretch border-danger bg-danger-bg'}>
        <div className="flex items-center gap-4">
          <AlertTriangle size={34} className="text-danger" />
          <div>
            <div className="text-xl font-extrabold text-danger">조건 불일치 — 컨베이어 정지</div>
            {m && (
              <div className="text-base font-bold text-ink-700">
                {m.field} · 기대값 <span className="text-ok">{m.expected}</span> → 판독값{' '}
                <span className="text-danger">{m.actual}</span>
              </div>
            )}
          </div>
        </div>
        <button className="btn btn-warn w-full" onClick={() => api('/api/session/resume', {})}>
          해당 제품 제외하고 계속 진행
        </button>
      </div>
    )
  }
  if (session.status === 'emergency') {
    return (
      <div className={base + ' border-danger bg-danger-bg'}>
        <OctagonX size={34} className="text-danger" />
        <div>
          <div className="text-xl font-extrabold text-danger">긴급 정지됨</div>
          <div className="text-base font-semibold text-ink-700">긴급 정지 해제 후 재개할 수 있습니다</div>
        </div>
      </div>
    )
  }
  if (session.status === 'done') {
    return (
      <div className={base + ' border-ok bg-ok-bg'}>
        <CheckCircle2 size={34} className="text-ok" />
        <div>
          <div className="text-xl font-extrabold text-ok">목표 수량 도달</div>
          <div className="text-base font-semibold text-ink-700">컨베이어가 정지되었습니다 · 결과가 저장되었습니다</div>
        </div>
      </div>
    )
  }
  return (
    <div className={base + ' border-brand-200 bg-brand-50'}>
      <Hand size={34} className="text-brand-600" />
      <div>
        <div className="text-xl font-extrabold text-brand-700">계수 대기 중</div>
        <div className="text-base font-semibold text-ink-700">계수 시작 버튼을 눌러주세요</div>
      </div>
    </div>
  )
}
