import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Clock, Timer, SlidersHorizontal, Check } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'
import VideoPanel from '../components/VideoPanel'
import JudgeLog from '../components/JudgeLog'
import StatusBanner from '../components/StatusBanner'
import ControlBar from '../components/ControlBar'
import Modal from '../components/Modal'
import type { Brand, Checks } from '../lib/types'

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

function CondRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line py-2.5 last:border-b-0">
      <span className="text-base font-bold text-ink-500">{label}</span>
      <span className="text-lg font-extrabold">{value}</span>
    </div>
  )
}

function checksLabel(c: Checks | undefined): string {
  if (!c) return '—'
  const parts = [
    c.rfid && 'RFID',
    c.ocr && 'OCR',
    c.barcode_tag && '가격택 바코드',
    c.barcode_poly && '폴리백 바코드',
  ].filter(Boolean)
  return parts.length ? parts.join(' + ') : '—'
}

function EditCheck({ label, checked, disabled, onToggle }: { label: string; checked: boolean; disabled?: boolean; onToggle: () => void }) {
  return (
    <button
      className={
        'flex w-full items-center gap-3 rounded-xl border-2 px-4 py-3 text-left ' +
        (disabled ? 'cursor-not-allowed border-line bg-panel opacity-60' : checked ? 'border-brand-500 bg-brand-50' : 'border-line bg-white')
      }
      onClick={onToggle}
      disabled={disabled}
    >
      <span
        className={
          'flex h-6 w-6 shrink-0 items-center justify-center rounded-md border-2 ' +
          (checked ? 'border-brand-600 bg-brand-600 text-white' : 'border-line bg-white')
        }
      >
        {checked && <Check size={16} strokeWidth={3} />}
      </span>
      <span className="text-base font-bold">{label}</span>
    </button>
  )
}

export default function ConditionRun() {
  const nav = useNavigate()
  const server = useApp((s) => s.server)
  const brands = useApp((s) => s.brands)
  const setBrands = useApp((s) => s.setBrands)
  const w = useApp((s) => s.wizard)
  const setW = useApp((s) => s.setWizard)
  const [editOpen, setEditOpen] = useState(false)
  const [draft, setDraft] = useState<{ checks: Checks; sku: string; color: string; size: string } | null>(null)

  const session = server?.session
  const elapsed = useElapsed(session?.startedAt ?? null, session?.status === 'running')

  useEffect(() => {
    api<Brand[]>('/api/brands').then(setBrands).catch(() => {})
  }, [setBrands])

  // 새로고침 등으로 위저드 상태가 비었을 때 서버 세션 설정으로 복원
  useEffect(() => {
    const cfg = session?.config
    if (!w.brandId && session?.mode === 'condition' && cfg && cfg.brandId) {
      setW({
        brandId: cfg.brandId,
        checks: cfg.checks ?? w.checks,
        countMode: cfg.countMode,
        target: cfg.target ?? 40,
        sku: cfg.item?.sku ?? '',
        color: cfg.item?.color ?? '',
        size: cfg.item?.size ?? '',
      })
    }
  }, [session, w.brandId, setW, w.checks])

  const brand = brands.find((b) => b.id === w.brandId) ?? null

  if (!w.brandId && session?.mode !== 'condition') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-5">
        <p className="text-2xl font-extrabold">진행 중인 조건 검사가 없습니다</p>
        <button className="btn btn-primary btn-lg" onClick={() => nav('/condition/setup')}>
          조건 설정으로 이동
        </button>
      </div>
    )
  }

  const count = session?.mode === 'condition' ? session.count : 0
  const target = w.countMode === 'target' ? w.target : null
  const pct = target ? Math.min(100, Math.round((count / target) * 100)) : 0
  const remain = target ? Math.max(0, target - count) : null

  const openEdit = () => {
    setDraft({ checks: { ...w.checks }, sku: w.sku, color: w.color, size: w.size })
    setEditOpen(true)
  }

  const applyEdit = async () => {
    if (!draft) return
    setW({ checks: draft.checks, sku: draft.sku, color: draft.color, size: draft.size })
    await api('/api/session/config', {
      checks: draft.checks,
      item: { sku: draft.sku, color: draft.color, size: draft.size },
    })
    setEditOpen(false)
  }

  const toggleDraft = (key: keyof Checks) => {
    if (!draft || !brand || !brand.caps[key]) return
    setDraft({ ...draft, checks: { ...draft.checks, [key]: !draft.checks[key] } })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">조건 계수{brand ? ' · ' + brand.name : ''}</h1>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1.25fr_1fr] gap-5 p-6">
        <div className="flex min-h-0 flex-col gap-5">
          <VideoPanel />
          <JudgeLog />
        </div>

        <div className="flex min-h-0 flex-col gap-5 overflow-y-auto">
          <div className="card p-6 text-center">
            <div className="text-lg font-bold text-ink-500">검사 완료 수량</div>
            <div className="flex items-end justify-center gap-3">
              <span className="text-[88px] font-black leading-none tabular-nums text-brand-800">{count}</span>
              {target != null && <span className="pb-2 text-3xl font-extrabold text-ink-500">/ {target}장</span>}
              {target == null && <span className="pb-2 text-3xl font-extrabold text-brand-600">벌</span>}
            </div>
            {target != null && (
              <div className="mt-4">
                <div className="h-4 overflow-hidden rounded-full bg-panel">
                  <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: pct + '%' }} />
                </div>
                <div className="mt-2 text-lg font-extrabold text-ink-700">남은 수량 {remain}장</div>
              </div>
            )}
            <div className="mt-4 border-t border-line">
              <div className="flex items-center justify-between py-3">
                <span className="flex items-center gap-2 text-base font-bold text-ink-700">
                  <Timer size={20} className="text-brand-600" /> 작업 시간
                </span>
                <span className="text-lg font-extrabold tabular-nums">{elapsed}</span>
              </div>
              <div className="flex items-center justify-between border-t border-line py-3">
                <span className="flex items-center gap-2 text-base font-bold text-ink-700">
                  <Clock size={20} className="text-brand-600" /> 최근 통과
                </span>
                <span className="text-lg font-extrabold tabular-nums">{session?.lastPassAt ?? '—'}</span>
              </div>
            </div>
          </div>

          <div className="card p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-extrabold">검사 조건</h3>
              <button className="btn btn-outline btn-sm" onClick={openEdit}>
                <SlidersHorizontal size={18} /> 조건 변경
              </button>
            </div>
            <div className="mt-2">
              <CondRow label="브랜드" value={brand ? brand.name : '—'} />
              <CondRow label="품번" value={w.sku || '—'} />
              <CondRow label="색상" value={w.color || '—'} />
              <CondRow label="사이즈" value={w.size || '—'} />
              <CondRow label="인식 방식" value={checksLabel(w.checks)} />
            </div>
          </div>

          <StatusBanner />
        </div>
      </div>

      <ControlBar mode="condition" />

      {editOpen && draft && (
        <Modal title="검사 조건 설정" onClose={() => setEditOpen(false)}>
          <p className="text-[15px] font-semibold text-ink-500">검사 중에도 검사 항목을 추가하거나 제거할 수 있습니다</p>
          <div className="mt-4 space-y-2">
            <EditCheck label="RFID 태그 인식" checked={draft.checks.rfid} disabled={!brand?.caps.rfid} onToggle={() => toggleDraft('rfid')} />
            <EditCheck label="OCR 문자 인식" checked={draft.checks.ocr} disabled={!brand?.caps.ocr} onToggle={() => toggleDraft('ocr')} />
            <EditCheck label="의류 가격택 바코드" checked={draft.checks.barcode_tag} disabled={!brand?.caps.barcode_tag} onToggle={() => toggleDraft('barcode_tag')} />
            <EditCheck label="폴리백 외부 라벨 바코드" checked={draft.checks.barcode_poly} disabled={!brand?.caps.barcode_poly} onToggle={() => toggleDraft('barcode_poly')} />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-bold text-ink-700">품번</span>
              <input className="field !min-h-[48px]" value={draft.sku} onChange={(e) => setDraft({ ...draft, sku: e.target.value.toUpperCase() })} />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-bold text-ink-700">색상</span>
              <input className="field !min-h-[48px]" value={draft.color} onChange={(e) => setDraft({ ...draft, color: e.target.value.toUpperCase() })} />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-bold text-ink-700">사이즈</span>
              <input className="field !min-h-[48px]" value={draft.size} onChange={(e) => setDraft({ ...draft, size: e.target.value.toUpperCase() })} />
            </label>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <button className="btn btn-outline" onClick={() => setEditOpen(false)}>
              취소
            </button>
            <button className="btn btn-primary" onClick={applyEdit}>
              적용
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
