import { useEffect, useState } from 'react'
import { useApp } from '../lib/store'
import type { DeviceKey, DeviceState } from '../lib/types'

const DEVICE_LABEL: Record<DeviceKey, string> = {
  camera: '카메라',
  sensor: '광센서',
  rfid: 'RFID',
  conveyor: '컨베이어',
}
const STATE_LABEL: Record<DeviceState, string> = {
  ok: '정상',
  idle: '대기',
  busy: '가동',
  fault: '오류',
  off: '꺼짐',
}
const STATE_DOT: Record<DeviceState, string> = {
  ok: 'bg-ok',
  idle: 'bg-slate-400',
  busy: 'bg-warn',
  fault: 'bg-danger',
  off: 'bg-slate-300',
}

function fmt(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '.' + p(d.getMonth() + 1) + '.' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
}

export default function TopBar() {
  const server = useApp((s) => s.server)
  const connected = useApp((s) => s.connected)
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const keys: DeviceKey[] = ['camera', 'sensor', 'rfid', 'conveyor']

  return (
    <header className="flex h-16 shrink-0 items-center gap-5 border-b border-line bg-white px-5">
      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-black tracking-[0.18em] text-brand-800">TXRX</span>
        <span className="text-lg font-bold">자동 계수 시스템</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {!connected && (
          <span className="rounded-full bg-danger px-3.5 py-1.5 text-sm font-bold text-white">서버 연결 끊김</span>
        )}
        {keys.map((k) => {
          const st: DeviceState = server?.devices?.[k] ?? 'off'
          return (
            <span key={k} className="flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 text-sm font-semibold">
              <span className={'h-2.5 w-2.5 rounded-full ' + STATE_DOT[st] + (st === 'busy' ? ' animate-pulse' : '')} />
              {DEVICE_LABEL[k]} {STATE_LABEL[st]}
            </span>
          )
        })}
      </div>
      <div className="text-right leading-tight">
        <div className="text-base font-bold tabular-nums">{fmt(now)}</div>
        <div className="text-sm font-semibold text-ink-500">JOOYOUNG FNC</div>
      </div>
    </header>
  )
}
