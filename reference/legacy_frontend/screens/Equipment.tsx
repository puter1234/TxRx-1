import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Play, Square, Loader2, CreditCard, ScanText, Signal } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'
import PipelineDiagram, { PipelineLegend } from '../components/PipelineDiagram'

type TestKind = 'sensor' | 'rfid' | 'ocr'

interface TestResult {
  ok: boolean
  detail: string
}

function TestCard({
  icon: Icon, title, desc, kind, busy, result, onRun, runLabel,
}: {
  icon: LucideIcon
  title: string
  desc: string
  kind: TestKind
  busy: TestKind | null
  result: TestResult | null
  onRun: (k: TestKind) => void
  runLabel: string
}) {
  const isBusy = busy === kind
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
          <Icon size={24} />
        </span>
        <div>
          <h3 className="text-lg font-extrabold">{title}</h3>
          <p className="text-[15px] font-semibold text-ink-500">{desc}</p>
        </div>
      </div>
      <div className="mt-4 min-h-[56px]">
        {isBusy ? (
          <div className="flex items-center gap-2.5 rounded-xl bg-warn-bg px-4 py-3 text-base font-bold text-warn">
            <Loader2 size={22} className="animate-spin" /> 인식 확인 중…
          </div>
        ) : result ? (
          <div
            className={
              'rounded-xl px-4 py-3 text-base font-bold ' +
              (result.ok ? 'bg-ok-bg text-ok' : 'bg-danger-bg text-danger')
            }
          >
            {result.detail}
          </div>
        ) : (
          <div className="rounded-xl bg-panel px-4 py-3 text-base font-semibold text-ink-500">아직 테스트하지 않았습니다</div>
        )}
      </div>
      <button className="btn btn-outline mt-3 w-full" onClick={() => onRun(kind)} disabled={busy !== null}>
        {runLabel}
      </button>
    </div>
  )
}

export default function Equipment() {
  const nav = useNavigate()
  const server = useApp((s) => s.server)
  const [busy, setBusy] = useState<TestKind | null>(null)
  const [results, setResults] = useState<Record<TestKind, TestResult | null>>({ sensor: null, rfid: null, ocr: null })

  const conveyorRunning = server?.pipeline?.conveyor === 'active'
  const sessionActive = server?.session?.status === 'running'

  const runTest = async (kind: TestKind) => {
    setBusy(kind)
    try {
      const res = await api<TestResult>('/api/device/test/' + kind, {})
      setResults((r) => ({ ...r, [kind]: res }))
    } catch {
      setResults((r) => ({ ...r, [kind]: { ok: false, detail: '테스트 요청에 실패했습니다' } }))
    } finally {
      setBusy(null)
    }
  }

  const toggleConveyor = () => api('/api/device/conveyor', { run: !conveyorRunning })

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">장비 점검</h1>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
        <div className="card p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-extrabold">전체 파이프라인</h2>
            <PipelineLegend />
          </div>
          <PipelineDiagram nodes={server?.pipeline} />
        </div>

        <div className="grid grid-cols-4 gap-5">
          <div className="card flex flex-col p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                {conveyorRunning ? <Square size={24} /> : <Play size={24} />}
              </span>
              <div>
                <h3 className="text-lg font-extrabold">컨베이어 제어</h3>
                <p className="text-[15px] font-semibold text-ink-500">계수와 별도로 벨트를 제어합니다</p>
              </div>
            </div>
            <div className="mt-4 min-h-[56px]">
              <div
                className={
                  'rounded-xl px-4 py-3 text-base font-bold ' +
                  (conveyorRunning ? 'bg-warn-bg text-warn' : 'bg-panel text-ink-500')
                }
              >
                {conveyorRunning ? '벨트 가동 중' : '벨트 정지됨'}
              </div>
            </div>
            <button
              className={'btn mt-3 w-full ' + (conveyorRunning ? 'btn-danger' : 'btn-primary')}
              onClick={toggleConveyor}
              disabled={sessionActive}
            >
              {conveyorRunning ? '벨트 정지' : '벨트 가동'}
            </button>
            {sessionActive && (
              <p className="mt-2 text-[15px] font-bold text-warn">계수 진행 중에는 별도 제어할 수 없습니다</p>
            )}
          </div>

          <TestCard
            icon={Signal}
            title="광센서 감지"
            desc="감지 신호 응답을 확인합니다"
            kind="sensor"
            busy={busy}
            result={results.sensor}
            onRun={runTest}
            runLabel="감지 테스트"
          />
          <TestCard
            icon={CreditCard}
            title="TEST RFID 카드"
            desc="테스트 카드 태그를 인식합니다"
            kind="rfid"
            busy={busy}
            result={results.rfid}
            onRun={runTest}
            runLabel="카드 인식 테스트"
          />
          <TestCard
            icon={ScanText}
            title="OCR 인식 확인"
            desc="카메라 문자 판독을 확인합니다"
            kind="ocr"
            busy={busy}
            result={results.ocr}
            onRun={runTest}
            runLabel="OCR 테스트"
          />
        </div>
      </div>
    </div>
  )
}
