import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Clock, Timer } from 'lucide-react'
import { useApp } from '../lib/store'
import VideoPanel from '../components/VideoPanel'
import JudgeLog from '../components/JudgeLog'
import StatusBanner from '../components/StatusBanner'
import ControlBar from '../components/ControlBar'

function useElapsed(startedAt: string | null, ticking: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!ticking) return
    const t = setInterval(() => setTick((v) => v + 1), 1000)
    return () => clearInterval(t)
  }, [ticking])
  if (!startedAt) return '00:00:00'
  const sec = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000))
  const p = (n: number) => String(n).padStart(2, '0')
  return p(Math.floor(sec / 3600)) + ':' + p(Math.floor((sec % 3600) / 60)) + ':' + p(sec % 60)
}

function InfoRow({ icon: Icon, label, value }: { icon: typeof Clock; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-3.5">
      <span className="flex items-center gap-2.5 text-lg font-bold text-ink-700">
        <Icon size={22} className="text-brand-600" /> {label}
      </span>
      <span className="text-xl font-extrabold tabular-nums">{value}</span>
    </div>
  )
}

export default function SimpleCount() {
  const nav = useNavigate()
  const session = useApp((s) => s.server?.session)
  const count = session?.mode ? session.count : 0
  const elapsed = useElapsed(session?.startedAt ?? null, session?.status === 'running')

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">단순 계수</h1>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1.25fr_1fr] gap-5 p-6">
        <div className="flex min-h-0 flex-col gap-5">
          <VideoPanel />
          <JudgeLog />
        </div>

        <div className="flex min-h-0 flex-col gap-5 overflow-y-auto">
          <div className="card p-6 text-center">
            <div className="text-lg font-bold text-ink-500">현재 수량</div>
            <div className="flex items-end justify-center gap-3">
              <span className="text-[104px] font-black leading-none tabular-nums text-brand-800">{count}</span>
              <span className="pb-3 text-3xl font-extrabold text-brand-600">벌</span>
            </div>
            <div className="mt-5 border-t border-line">
              <div className="divide-y divide-line">
                <InfoRow icon={Timer} label="작업 시간" value={elapsed} />
                <InfoRow icon={Clock} label="최근 통과" value={session?.lastPassAt ?? '—'} />
              </div>
            </div>
          </div>
          <StatusBanner />
        </div>
      </div>

      <ControlBar mode="simple" />
    </div>
  )
}
