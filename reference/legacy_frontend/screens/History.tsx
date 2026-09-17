import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FolderOpen, Database, RefreshCw } from 'lucide-react'
import { useApp } from '../lib/store'
import { api } from '../lib/api'
import type { Job } from '../lib/types'

export default function History() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const loadMode = params.get('load') === '1'
  const setW = useApp((s) => s.setWizard)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = () => {
    setLoading(true)
    api<Job[]>('/api/jobs')
      .then(setJobs)
      .catch(() => setJobs([]))
      .finally(() => setLoading(false))
  }

  useEffect(refresh, [])

  const loadJob = (job: Job) => {
    const cfg = job.config
    if (job.mode === 'condition' && cfg) {
      setW({
        step: 3,
        brandId: cfg.brandId ?? null,
        checks: cfg.checks ?? { rfid: false, ocr: false, barcode_tag: false, barcode_poly: false },
        countMode: cfg.countMode ?? 'target',
        target: cfg.target ?? 40,
        sku: cfg.item?.sku ?? '',
        color: cfg.item?.color ?? '',
        size: cfg.item?.size ?? '',
      })
      nav('/condition/setup')
    } else {
      nav('/simple')
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav('/')}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">{loadMode ? '이전 작업 불러오기' : '작업 기록'}</h1>
        <button className="btn btn-outline btn-sm ml-auto" onClick={refresh}>
          <RefreshCw size={18} /> 새로고침
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-6xl space-y-4">
          <div className="flex items-center gap-2.5 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-base font-bold text-brand-800">
            <Database size={20} />
            작업 기록은 현재 이 PC의 날짜별 폴더에만 저장됩니다 · 추후 데이터베이스 연동 예정
          </div>

          <div className="card overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b-2 border-line bg-panel text-left">
                  <th className="px-5 py-3.5 text-base font-extrabold">날짜</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">시각</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">방식</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">브랜드</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">품번</th>
                  <th className="px-4 py-3.5 text-right text-base font-extrabold">수량</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">저장 위치</th>
                  <th className="px-4 py-3.5" />
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={8} className="px-5 py-10 text-center text-lg font-semibold text-ink-500">불러오는 중…</td>
                  </tr>
                )}
                {!loading && jobs.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-5 py-10 text-center text-lg font-semibold text-ink-500">
                      저장된 작업 기록이 없습니다 · 계수를 완료하면 자동으로 저장됩니다
                    </td>
                  </tr>
                )}
                {jobs.map((job) => (
                  <tr key={job.id} className="border-b border-line last:border-b-0 hover:bg-panel/60">
                    <td className="px-5 py-3.5 text-base font-bold tabular-nums">{job.date}</td>
                    <td className="px-4 py-3.5 text-base font-semibold tabular-nums">{job.time}</td>
                    <td className="px-4 py-3.5">
                      <span
                        className={
                          'rounded-md px-2.5 py-1 text-[15px] font-bold ' +
                          (job.mode === 'condition' ? 'bg-brand-50 text-brand-700' : 'bg-panel text-ink-700')
                        }
                      >
                        {job.mode === 'condition' ? '조건 계수' : '단순 계수'}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-base font-bold">{job.config?.brandName ?? '—'}</td>
                    <td className="px-4 py-3.5 text-base font-semibold">{job.config?.item?.sku || '—'}</td>
                    <td className="px-4 py-3.5 text-right text-lg font-extrabold tabular-nums">{job.count}벌</td>
                    <td className="max-w-[220px] truncate px-4 py-3.5 text-[15px] font-semibold text-ink-500" title={job.dir}>
                      {job.dir}
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <button className="btn btn-outline btn-sm" onClick={() => loadJob(job)}>
                        <FolderOpen size={18} /> 불러오기
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
