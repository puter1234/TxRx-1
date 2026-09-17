import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Lock, Delete, Trash2, Plus, KeyRound } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'
import type { Brand, BrandCaps } from '../lib/types'

const CAP_LABEL: { key: keyof BrandCaps; label: string }[] = [
  { key: 'rfid', label: 'RFID' },
  { key: 'ocr', label: 'OCR' },
  { key: 'barcode_tag', label: '가격택 바코드' },
  { key: 'barcode_poly', label: '폴리백 바코드' },
]

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      className={'relative h-9 w-16 shrink-0 rounded-full transition ' + (checked ? 'bg-brand-600' : 'bg-slate-300')}
      onClick={() => onChange(!checked)}
      role="switch"
      aria-checked={checked}
    >
      <span className={'absolute top-1 h-7 w-7 rounded-full bg-white shadow transition-all ' + (checked ? 'left-8' : 'left-1')} />
    </button>
  )
}

function LoginGate({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState('')
  const [error, setError] = useState(false)

  const press = (d: string) => {
    setError(false)
    if (d === 'clear') setPw('')
    else if (d === 'back') setPw((p) => p.slice(0, -1))
    else if (pw.length < 8) setPw((p) => p + d)
  }

  const submit = async () => {
    try {
      const res = await api<{ ok: boolean }>('/api/login', { password: pw })
      if (res.ok) onOk()
      else {
        setError(true)
        setPw('')
      }
    } catch {
      setError(true)
    }
  }

  const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back']

  return (
    <div className="flex h-full items-center justify-center">
      <div className="card w-full max-w-md p-8">
        <div className="flex flex-col items-center text-center">
          <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
            <Lock size={32} />
          </span>
          <h1 className="mt-4 text-2xl font-extrabold">환경 설정 잠금</h1>
          <p className="mt-1.5 text-base font-semibold text-ink-500">관리자 비밀번호를 입력하세요</p>
        </div>

        <div className="mt-6 flex h-16 items-center justify-center gap-3 rounded-xl border-2 border-line bg-panel">
          {pw.length === 0 && <span className="text-base font-semibold text-ink-500">비밀번호 입력</span>}
          {Array.from(pw).map((_, i) => (
            <span key={i} className="h-4 w-4 rounded-full bg-ink-900" />
          ))}
        </div>
        {error && <p className="mt-2.5 text-center text-base font-extrabold text-danger">비밀번호가 올바르지 않습니다</p>}

        <div className="mt-5 grid grid-cols-3 gap-2.5">
          {keys.map((k) => (
            <button
              key={k}
              className="btn btn-outline !min-h-[60px] text-2xl font-black"
              onClick={() => press(k)}
            >
              {k === 'clear' ? <span className="text-base font-bold">지움</span> : k === 'back' ? <Delete size={26} /> : k}
            </button>
          ))}
        </div>
        <button className="btn btn-primary btn-lg mt-4 w-full" onClick={submit} disabled={pw.length === 0}>
          확인
        </button>
        <p className="mt-3 text-center text-[15px] font-semibold text-ink-500">프로토타입 초기 비밀번호: 0000</p>
      </div>
    </div>
  )
}

function GeneralTab() {
  const server = useApp((s) => s.server)
  const [savePhotos, setSavePhotos] = useState(true)
  const [threshold, setThreshold] = useState(55)
  const [curPw, setCurPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (server?.settings) {
      setSavePhotos(server.settings.save_photos)
      setThreshold(server.settings.threshold)
    }
    // 서버 상태 최초 수신 시에만 동기화
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [server?.settings?.data_dir])

  const put = (patch: { save_photos?: boolean; threshold?: number }) => api('/api/settings', patch, 'PUT')

  const changePw = async () => {
    try {
      const res = await api<{ ok: boolean }>('/api/password', { current: curPw, next: newPw })
      setPwMsg(res.ok ? { ok: true, text: '비밀번호가 변경되었습니다' } : { ok: false, text: '현재 비밀번호가 올바르지 않습니다' })
      if (res.ok) {
        setCurPw('')
        setNewPw('')
      }
    } catch {
      setPwMsg({ ok: false, text: '변경 요청에 실패했습니다' })
    }
  }

  return (
    <div className="grid max-w-5xl grid-cols-2 gap-5">
      <div className="card space-y-5 p-6">
        <h2 className="text-xl font-extrabold">계수 저장</h2>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-lg font-bold">통과 사진 저장</div>
            <div className="text-[15px] font-semibold text-ink-500">계수 시 캡처 이미지를 날짜별 폴더에 저장합니다</div>
          </div>
          <Toggle
            checked={savePhotos}
            onChange={(v) => {
              setSavePhotos(v)
              put({ save_photos: v })
            }}
          />
        </div>
        <div>
          <div className="flex items-center justify-between">
            <div className="text-lg font-bold">계수 임계선 위치</div>
            <div className="text-xl font-extrabold tabular-nums text-brand-700">{threshold}%</div>
          </div>
          <div className="text-[15px] font-semibold text-ink-500">화면 좌측 기준 · 의류가 임계선을 지나면 계수됩니다</div>
          <input
            type="range"
            min={10}
            max={90}
            value={threshold}
            className="mt-3 h-3 w-full accent-brand-600"
            onChange={(e) => setThreshold(Number(e.target.value))}
            onMouseUp={() => put({ threshold })}
            onTouchEnd={() => put({ threshold })}
          />
        </div>
        <div>
          <div className="text-lg font-bold">데이터 저장 경로</div>
          <div className="mt-1.5 break-all rounded-xl bg-panel px-4 py-3 text-base font-semibold">
            {server?.settings?.data_dir ?? '—'}
          </div>
        </div>
      </div>

      <div className="card space-y-4 p-6">
        <h2 className="flex items-center gap-2 text-xl font-extrabold">
          <KeyRound size={24} className="text-brand-600" /> 비밀번호 변경
        </h2>
        <label className="block">
          <span className="mb-1.5 block text-base font-bold text-ink-700">현재 비밀번호</span>
          <input className="field" type="password" inputMode="numeric" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-base font-bold text-ink-700">새 비밀번호</span>
          <input className="field" type="password" inputMode="numeric" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        </label>
        {pwMsg && (
          <p className={'text-base font-extrabold ' + (pwMsg.ok ? 'text-ok' : 'text-danger')}>{pwMsg.text}</p>
        )}
        <button className="btn btn-primary w-full" onClick={changePw} disabled={!curPw || !newPw}>
          변경
        </button>
      </div>
    </div>
  )
}

function BrandTab() {
  const brands = useApp((s) => s.brands)
  const setBrands = useApp((s) => s.setBrands)
  const [name, setName] = useState('')
  const [caps, setCaps] = useState<BrandCaps>({ rfid: false, ocr: true, barcode_tag: true, barcode_poly: false })

  const refresh = () => api<Brand[]>('/api/brands').then(setBrands).catch(() => {})
  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const add = async () => {
    if (!name.trim()) return
    await api('/api/brands', { name: name.trim(), caps })
    setName('')
    refresh()
  }

  const update = async (b: Brand, key: keyof BrandCaps) => {
    const next = { ...b, caps: { ...b.caps, [key]: !b.caps[key] } }
    setBrands(brands.map((x) => (x.id === b.id ? next : x)))
    await api('/api/brands/' + b.id, { name: next.name, caps: next.caps }, 'PUT')
  }

  const remove = async (b: Brand) => {
    await api('/api/brands/' + b.id, undefined, 'DELETE')
    refresh()
  }

  return (
    <div className="max-w-5xl space-y-5">
      <div className="card p-6">
        <h2 className="text-xl font-extrabold">브랜드 추가</h2>
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="block w-64">
            <span className="mb-1.5 block text-base font-bold text-ink-700">브랜드명</span>
            <input className="field" placeholder="예: 헤지스" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="flex items-center gap-4 pb-3">
            {CAP_LABEL.map(({ key, label }) => (
              <label key={key} className="flex items-center gap-2 text-base font-bold">
                <input
                  type="checkbox"
                  className="h-6 w-6 accent-brand-600"
                  checked={caps[key]}
                  onChange={() => setCaps({ ...caps, [key]: !caps[key] })}
                />
                {label}
              </label>
            ))}
          </div>
          <button className="btn btn-primary" onClick={add} disabled={!name.trim()}>
            <Plus size={22} /> 추가
          </button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b-2 border-line bg-panel text-left">
              <th className="px-5 py-3.5 text-base font-extrabold">브랜드명</th>
              {CAP_LABEL.map(({ key, label }) => (
                <th key={key} className="px-4 py-3.5 text-center text-base font-extrabold">
                  {label}
                </th>
              ))}
              <th className="px-4 py-3.5" />
            </tr>
          </thead>
          <tbody>
            {brands.map((b) => (
              <tr key={b.id} className="border-b border-line last:border-b-0">
                <td className="px-5 py-3.5 text-lg font-extrabold">{b.name}</td>
                {CAP_LABEL.map(({ key }) => (
                  <td key={key} className="px-4 py-3.5 text-center">
                    <input
                      type="checkbox"
                      className="h-6 w-6 accent-brand-600"
                      checked={b.caps[key]}
                      onChange={() => update(b, key)}
                    />
                  </td>
                ))}
                <td className="px-4 py-3.5 text-right">
                  <button className="btn btn-outline btn-sm hover:!border-danger hover:!text-danger" onClick={() => remove(b)}>
                    <Trash2 size={18} /> 삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LogTab() {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    api<{ lines: string[] }>('/api/logs?date=' + date)
      .then((r) => setLines(r.lines))
      .catch(() => setLines([]))
  }, [date])

  return (
    <div className="max-w-5xl space-y-4">
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold">날짜 선택</span>
        <input type="date" className="field !w-56" value={date} onChange={(e) => setDate(e.target.value)} max={today} />
      </div>
      <div className="card max-h-[520px] overflow-y-auto p-5">
        {lines.length === 0 ? (
          <p className="text-lg font-semibold text-ink-500">해당 날짜의 로그가 없습니다</p>
        ) : (
          <div className="space-y-1 font-mono text-[15px] font-medium">
            {lines.map((l, i) => (
              <div key={i} className={l.includes('[ERROR]') ? 'font-bold text-danger' : l.includes('[WARN]') ? 'text-warn' : ''}>
                {l}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Settings() {
  const nav = useNavigate()
  const [authed, setAuthed] = useState(false)
  const [tab, setTab] = useState<'general' | 'brands' | 'logs'>('general')

  if (!authed) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
          <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
            <ArrowLeft size={20} /> 처음 화면
          </button>
          <h1 className="text-2xl font-extrabold">환경 설정</h1>
        </div>
        <div className="min-h-0 flex-1">
          <LoginGate onOk={() => setAuthed(true)} />
        </div>
      </div>
    )
  }

  const tabs: { id: typeof tab; label: string }[] = [
    { id: 'general', label: '일반' },
    { id: 'brands', label: '브랜드 관리' },
    { id: 'logs', label: '작업 로그' },
  ]

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">환경 설정</h1>
        <div className="ml-6 flex gap-2">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={
                'rounded-xl px-5 py-3 text-lg font-extrabold transition ' +
                (tab === t.id ? 'bg-brand-600 text-white' : 'bg-white text-ink-700 hover:bg-brand-50')
              }
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {tab === 'general' && <GeneralTab />}
        {tab === 'brands' && <BrandTab />}
        {tab === 'logs' && <LogTab />}
      </div>
    </div>
  )
}
