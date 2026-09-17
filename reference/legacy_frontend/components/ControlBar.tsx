import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Play, Pause, Plus, Minus, RotateCcw, Square, AlertTriangle, ShieldCheck } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'
import Modal from './Modal'
import type { Job } from '../lib/types'

export default function ControlBar({ mode }: { mode: 'simple' | 'condition' }) {
  const nav = useNavigate()
  const session = useApp((s) => s.server?.session)
  const [stopJob, setStopJob] = useState<Job | null>(null)
  const [stopped, setStopped] = useState(false)

  const status = session?.status ?? 'idle'
  const active = session?.mode != null && status !== 'idle'
  const running = status === 'running'
  const canPause = running || status === 'paused' || status === 'mismatch'

  const start = () => api('/api/session/start', { mode: 'simple', countMode: 'continuous' })
  const pauseResume = () => api(running ? '/api/session/pause' : '/api/session/resume', {})
  const adjust = (delta: number) => api('/api/session/adjust', { delta })
  const resetCount = () => api('/api/session/reset-count', {})
  const emergency = () => api('/api/session/emergency', {})
  const release = () => api('/api/session/emergency-release', {})

  const stop = async () => {
    const res = await api<{ ok: boolean; job: Job | null }>('/api/session/stop', {})
    setStopJob(res.job)
    setStopped(true)
  }

  const closeStop = () => {
    setStopped(false)
    setStopJob(null)
    nav('/')
  }

  const stopLabel = mode === 'condition' ? '검사 종료' : '계수 종료'

  return (
    <>
      <div className="flex shrink-0 items-center gap-3 border-t border-line bg-white px-6 py-4">
        {mode === 'simple' && (
          <button className="btn btn-primary" onClick={start} disabled={active}>
            <Play size={22} /> 계수 시작
          </button>
        )}
        <button className="btn btn-outline" onClick={pauseResume} disabled={!canPause}>
          {running ? <Pause size={22} /> : <Play size={22} />}
          {running ? '일시정지' : '재개'}
        </button>
        <button className="btn btn-outline" onClick={() => adjust(-1)} disabled={!active}>
          <Minus size={22} /> 수동 -1
        </button>
        <button className="btn btn-outline" onClick={() => adjust(1)} disabled={!active}>
          <Plus size={22} /> 수동 +1
        </button>
        {mode === 'simple' && (
          <button className="btn btn-outline" onClick={resetCount} disabled={!active}>
            <RotateCcw size={22} /> 수량 초기화
          </button>
        )}
        <button className="btn btn-outline" onClick={stop} disabled={!active}>
          <Square size={20} /> {stopLabel}
        </button>
        <div className="ml-auto" />
        {status === 'emergency' ? (
          <button className="btn btn-warn" onClick={release}>
            <ShieldCheck size={22} /> 긴급 정지 해제
          </button>
        ) : (
          <button className="btn btn-danger" onClick={emergency} disabled={!active}>
            <AlertTriangle size={22} /> 긴급 정지
          </button>
        )}
      </div>

      {stopped && (
        <Modal title="작업이 종료되었습니다" onClose={closeStop}>
          {stopJob ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-xl bg-panel px-4 py-3">
                <span className="text-base font-bold text-ink-700">총 계수 수량</span>
                <span className="text-2xl font-black text-brand-800">{stopJob.count}벌</span>
              </div>
              <div className="rounded-xl bg-panel px-4 py-3">
                <div className="text-base font-bold text-ink-700">결과 저장 위치 (날짜별 폴더)</div>
                <div className="mt-1 break-all text-[15px] font-semibold">{stopJob.dir}</div>
              </div>
            </div>
          ) : (
            <p className="text-base font-semibold text-ink-700">계수된 수량이 없어 저장하지 않았습니다.</p>
          )}
          <button className="btn btn-primary mt-5 w-full" onClick={closeStop}>
            확인
          </button>
        </Modal>
      )}
    </>
  )
}
