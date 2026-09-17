import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ChevronRight, Search, Check, RotateCcw, Minus, Plus, Info, Play } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'
import type { Brand, Checks } from '../lib/types'

const STEPS = ['브랜드 및 검사 항목', '수량 설정', '조건 설정']

function Stepper({ step }: { step: number }) {
  return (
    <div className="flex items-center justify-center">
      {STEPS.map((label, i) => {
        const n = i + 1
        const isNow = n === step
        const done = n < step
        return (
          <div key={label} className="flex items-center">
            {i > 0 && <div className={'mx-3 h-1 w-16 rounded ' + (n <= step ? 'bg-brand-600' : 'bg-line')} />}
            <div className="flex items-center gap-2.5">
              <span
                className={
                  'flex h-10 w-10 items-center justify-center rounded-full text-lg font-extrabold ' +
                  (isNow ? 'bg-brand-600 text-white' : done ? 'bg-ok text-white' : 'border-2 border-line bg-white text-ink-500')
                }
              >
                {done ? <Check size={22} /> : n}
              </span>
              <span className={'text-base font-bold ' + (isNow ? 'text-brand-700' : 'text-ink-500')}>{label}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CheckRow({
  label, checked, disabled, indent, onToggle,
}: {
  label: string; checked: boolean; disabled?: boolean; indent?: boolean; onToggle: () => void
}) {
  return (
    <button
      className={
        'flex w-full items-center gap-3 rounded-xl border-2 px-4 py-3.5 text-left transition ' +
        (indent ? 'ml-6 w-[calc(100%-1.5rem)] ' : '') +
        (disabled
          ? 'cursor-not-allowed border-line bg-panel opacity-60'
          : checked
            ? 'border-brand-500 bg-brand-50'
            : 'border-line bg-white hover:border-brand-200')
      }
      onClick={onToggle}
      disabled={disabled}
    >
      <span
        className={
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border-2 ' +
          (checked ? 'border-brand-600 bg-brand-600 text-white' : 'border-line bg-white')
        }
      >
        {checked && <Check size={18} strokeWidth={3} />}
      </span>
      <span className="text-lg font-bold">{label}</span>
      {disabled && <span className="ml-auto rounded-md bg-line px-2.5 py-1 text-sm font-bold text-ink-500">지원하지 않음</span>}
    </button>
  )
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-xl bg-panel px-4 py-3">
      <span className="text-base font-bold text-ink-500">{label}</span>
      <span className="text-lg font-extrabold">{value}</span>
    </div>
  )
}

export default function ConditionWizard() {
  const nav = useNavigate()
  const brands = useApp((s) => s.brands)
  const setBrands = useApp((s) => s.setBrands)
  const w = useApp((s) => s.wizard)
  const setW = useApp((s) => s.setWizard)
  const [query, setQuery] = useState('')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    api<Brand[]>('/api/brands').then(setBrands).catch(() => {})
  }, [setBrands])

  const brand = brands.find((b) => b.id === w.brandId) ?? null
  const filtered = useMemo(
    () => brands.filter((b) => b.name.toLowerCase().includes(query.trim().toLowerCase())),
    [brands, query],
  )

  const selectBrand = (b: Brand) => {
    setW({ brandId: b.id, checks: { ...b.caps } })
  }

  const toggle = (key: keyof Checks) => {
    if (!brand || !brand.caps[key]) return
    setW({ checks: { ...w.checks, [key]: !w.checks[key] } })
  }

  const barcodeCapable = !!brand && (brand.caps.barcode_tag || brand.caps.barcode_poly)
  const barcodeChecked = w.checks.barcode_tag || w.checks.barcode_poly
  const toggleBarcode = () => {
    if (!brand || !barcodeCapable) return
    if (barcodeChecked) setW({ checks: { ...w.checks, barcode_tag: false, barcode_poly: false } })
    else setW({ checks: { ...w.checks, barcode_tag: brand.caps.barcode_tag, barcode_poly: brand.caps.barcode_poly } })
  }

  const anyCheck = w.checks.rfid || w.checks.ocr || w.checks.barcode_tag || w.checks.barcode_poly
  const canNext1 = !!brand && anyCheck

  const checkSummary = [
    w.checks.rfid && 'RFID',
    w.checks.ocr && 'OCR 문자 인식',
    w.checks.barcode_tag && '가격택 바코드',
    w.checks.barcode_poly && '폴리백 바코드',
  ]
    .filter(Boolean)
    .join(' + ')

  const start = async () => {
    if (!brand) return
    setStarting(true)
    try {
      await api('/api/session/start', {
        mode: 'condition',
        brandId: brand.id,
        brandName: brand.name,
        checks: w.checks,
        countMode: w.countMode,
        target: w.countMode === 'target' ? w.target : null,
        item: { sku: w.sku, color: w.color, size: w.size },
      })
      nav('/condition/run')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">조건 계수 설정</h1>
      </div>

      <div className="shrink-0 px-6 pt-5">
        <Stepper step={w.step} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {w.step === 1 && (
          <div className="mx-auto grid max-w-6xl grid-cols-[1.4fr_1fr] gap-5">
            <div className="card p-6">
              <h2 className="text-xl font-extrabold">브랜드 선택</h2>
              <div className="relative mt-4">
                <Search size={22} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-500" />
                <input
                  className="field pl-12"
                  placeholder="브랜드 검색"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3">
                {filtered.map((b) => {
                  const sel = b.id === w.brandId
                  return (
                    <button
                      key={b.id}
                      className={
                        'relative flex h-24 items-center justify-center rounded-xl border-2 text-xl font-extrabold transition ' +
                        (sel ? 'border-brand-600 bg-brand-50 text-brand-800' : 'border-line bg-white hover:border-brand-200')
                      }
                      onClick={() => selectBrand(b)}
                    >
                      {b.name}
                      {sel && (
                        <span className="absolute right-2.5 top-2.5 flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-white">
                          <Check size={18} strokeWidth={3} />
                        </span>
                      )}
                    </button>
                  )
                })}
                {filtered.length === 0 && (
                  <p className="col-span-3 py-8 text-center text-lg font-semibold text-ink-500">검색 결과가 없습니다</p>
                )}
              </div>
            </div>

            <div className="card flex flex-col p-6">
              <h2 className="text-xl font-extrabold">{brand ? brand.name + ' 검사 항목' : '검사 항목'}</h2>
              {!brand ? (
                <p className="mt-4 text-lg font-semibold text-ink-500">먼저 브랜드를 선택하세요</p>
              ) : (
                <div className="mt-4 space-y-2.5">
                  <CheckRow label="RFID 태그 인식" checked={w.checks.rfid} disabled={!brand.caps.rfid} onToggle={() => toggle('rfid')} />
                  <CheckRow label="OCR 문자 인식" checked={w.checks.ocr} disabled={!brand.caps.ocr} onToggle={() => toggle('ocr')} />
                  <CheckRow label="바코드 영상 인식" checked={barcodeChecked} disabled={!barcodeCapable} onToggle={toggleBarcode} />
                  {barcodeChecked && (
                    <>
                      <CheckRow label="의류 가격택" indent checked={w.checks.barcode_tag} disabled={!brand.caps.barcode_tag} onToggle={() => toggle('barcode_tag')} />
                      <CheckRow label="폴리백 외부 라벨" indent checked={w.checks.barcode_poly} disabled={!brand.caps.barcode_poly} onToggle={() => toggle('barcode_poly')} />
                    </>
                  )}
                  <div className="flex items-start gap-2.5 rounded-xl bg-brand-50 p-4 text-[15px] font-semibold text-brand-800">
                    <Info size={20} className="mt-0.5 shrink-0" />
                    가격택과 폴리백 바코드가 모두 인식되어도 동일 제품은 1벌로 계수됩니다
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {w.step === 2 && (
          <div className="mx-auto grid max-w-5xl grid-cols-[1.4fr_1fr] gap-5">
            <div className="card p-6">
              <h2 className="text-xl font-extrabold">작업 모드 선택</h2>
              <div className="mt-4 space-y-3">
                <div
                  className={
                    'w-full cursor-pointer rounded-xl border-2 p-5 text-left transition ' +
                    (w.countMode === 'target' ? 'border-brand-600 bg-brand-50' : 'border-line bg-white hover:border-brand-200')
                  }
                  onClick={() => setW({ countMode: 'target' })}
                >
                  <div className="text-xl font-extrabold">목표 수량 모드</div>
                  <div className="mt-1 text-base font-semibold text-ink-500">설정한 수량에 도달하면 컨베이어가 자동으로 정지합니다</div>
                  {w.countMode === 'target' && (
                    <div className="mt-4 flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                      <button className="btn btn-outline h-14 w-14 !min-h-0 !p-0" onClick={() => setW({ target: Math.max(1, w.target - 1) })}>
                        <Minus size={24} />
                      </button>
                      <div className="flex h-14 w-28 items-center justify-center rounded-xl border-2 border-line bg-white text-3xl font-black tabular-nums">
                        {w.target}
                      </div>
                      <button className="btn btn-outline h-14 w-14 !min-h-0 !p-0" onClick={() => setW({ target: w.target + 1 })}>
                        <Plus size={24} />
                      </button>
                      <span className="text-xl font-bold">장</span>
                      <div className="ml-2 flex gap-2">
                        {[20, 40, 60, 100].map((n) => (
                          <button
                            key={n}
                            className={
                              'rounded-lg border-2 px-3.5 py-2 text-base font-bold ' +
                              (w.target === n ? 'border-brand-600 bg-brand-600 text-white' : 'border-line bg-white')
                            }
                            onClick={() => setW({ target: n })}
                          >
                            {n}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <div
                  className={
                    'w-full cursor-pointer rounded-xl border-2 p-5 text-left transition ' +
                    (w.countMode === 'continuous' ? 'border-brand-600 bg-brand-50' : 'border-line bg-white hover:border-brand-200')
                  }
                  onClick={() => setW({ countMode: 'continuous' })}
                >
                  <div className="text-xl font-extrabold">계속 계수 모드</div>
                  <div className="mt-1 text-base font-semibold text-ink-500">수량 설정 없이 누적하여 계수를 진행합니다</div>
                </div>
              </div>
            </div>

            <div className="card p-6">
              <h2 className="text-xl font-extrabold">설정 요약</h2>
              <div className="mt-4 space-y-3">
                <SummaryRow label="브랜드" value={brand ? brand.name : '—'} />
                <SummaryRow label="검사 항목" value={checkSummary || '—'} />
                <SummaryRow label="작업 모드" value={w.countMode === 'target' ? '목표 수량 ' + w.target + '장' : '계속 계수'} />
              </div>
            </div>
          </div>
        )}

        {w.step === 3 && (
          <div className="mx-auto grid max-w-5xl grid-cols-[1.4fr_1fr] gap-5">
            <div className="card p-6">
              <h2 className="text-xl font-extrabold">검사 조건 설정</h2>
              <p className="mt-1 text-base font-semibold text-ink-500">설정한 값과 판독 결과가 다르면 컨베이어가 정지합니다</p>
              <div className="mt-5 space-y-4">
                <label className="block">
                  <span className="mb-1.5 block text-base font-bold text-ink-700">품번</span>
                  <input className="field" placeholder="예: TS-2401" value={w.sku} onChange={(e) => setW({ sku: e.target.value.toUpperCase() })} />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-base font-bold text-ink-700">색상</span>
                  <input className="field" placeholder="예: NAVY" value={w.color} onChange={(e) => setW({ color: e.target.value.toUpperCase() })} />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-base font-bold text-ink-700">사이즈</span>
                  <input className="field" placeholder="예: 100" value={w.size} onChange={(e) => setW({ size: e.target.value.toUpperCase() })} />
                </label>
              </div>
            </div>

            <div className="card p-6">
              <h2 className="text-xl font-extrabold">최종 확인</h2>
              <div className="mt-4 space-y-3">
                <SummaryRow label="브랜드" value={brand ? brand.name : '—'} />
                <SummaryRow label="검사 항목" value={checkSummary || '—'} />
                <SummaryRow label="작업 모드" value={w.countMode === 'target' ? '목표 수량 ' + w.target + '장' : '계속 계수'} />
                <SummaryRow label="품번" value={w.sku || '—'} />
                <SummaryRow label="색상" value={w.color || '—'} />
                <SummaryRow label="사이즈" value={w.size || '—'} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-3 border-t border-line bg-white px-6 py-4">
        <button
          className="btn btn-outline"
          onClick={() => (w.step === 1 ? nav('/') : setW({ step: (w.step - 1) as 1 | 2 | 3 }))}
        >
          <ArrowLeft size={22} /> 이전
        </button>
        {w.step === 1 && (
          <button
            className="btn btn-outline"
            onClick={() => setW({ brandId: null, checks: { rfid: false, ocr: false, barcode_tag: false, barcode_poly: false } })}
          >
            <RotateCcw size={22} /> 선택 초기화
          </button>
        )}
        <div className="ml-auto" />
        {w.step < 3 ? (
          <button
            className="btn btn-primary"
            disabled={w.step === 1 && !canNext1}
            onClick={() => setW({ step: (w.step + 1) as 1 | 2 | 3 })}
          >
            다음: {STEPS[w.step]} <ChevronRight size={22} />
          </button>
        ) : (
          <button className="btn btn-primary btn-lg" disabled={starting} onClick={start}>
            <Play size={24} /> 검사 시작
          </button>
        )}
      </div>
    </div>
  )
}
