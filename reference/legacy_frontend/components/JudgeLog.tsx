import { useEffect, useRef } from 'react'
import { CheckCircle2, XCircle, AlertTriangle, Info } from 'lucide-react'
import { useApp } from '../lib/store'
import type { LogItem } from '../lib/types'

function KindIcon({ kind }: { kind: LogItem['kind'] }) {
  if (kind === 'ok') return <CheckCircle2 size={18} className="shrink-0 text-ok" />
  if (kind === 'error') return <XCircle size={18} className="shrink-0 text-danger" />
  if (kind === 'warn') return <AlertTriangle size={18} className="shrink-0 text-warn" />
  return <Info size={18} className="shrink-0 text-brand-500" />
}

export default function JudgeLog() {
  const logs = useApp((s) => s.logs)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight })
  }, [logs])

  return (
    <div className="card flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line px-5 py-3">
        <h3 className="text-lg font-bold">실시간 판단 정보</h3>
      </div>
      <div ref={ref} className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-4">
        {logs.length === 0 && <p className="text-base font-medium text-ink-500">아직 기록이 없습니다</p>}
        {logs.map((l, i) => (
          <div key={i} className="flex items-center gap-2.5 text-[15px] font-medium">
            <KindIcon kind={l.kind} />
            <span className="tabular-nums text-ink-500">{l.ts}</span>
            <span className={l.kind === 'error' ? 'font-bold text-danger' : ''}>{l.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
