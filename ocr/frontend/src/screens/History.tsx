import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, FolderOpen, RefreshCw } from "lucide-react";
import { useApp } from "../lib/store";
import { api } from "../lib/api";
import type { Job } from "../lib/types";
import { api as request, ResultCard, type Result } from "../station/shared";
import { reportError } from "../lib/station";
import Modal from "../components/Modal";

function InspectionHistory({
  job,
  onClose,
}: {
  job: Job;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Result[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    request<{ inspections: Result[] }>(
      `/history?session_id=${encodeURIComponent(job.id)}&offset=${offset}`,
    )
      .then((r) => {
        if (alive) {
          setRows((old) =>
            offset ? [...old, ...r.inspections] : r.inspections,
          );
          setMore(r.inspections.length === 100);
        }
      })
      .catch(reportError)
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [job.id, offset]);
  return (
    <Modal title="검사 기록" width="max-w-4xl" onClose={onClose}>
      <div className="space-y-4">
        {rows.map((row) => (
          <div key={row.id}>
            <p className="mb-2 text-lg font-bold">
              {new Date(row.created_at).toLocaleString("ko-KR")}
            </p>
            <ResultCard result={row} />
          </div>
        ))}
        {!busy && !rows.length && (
          <p className="py-6 text-lg font-bold">검사 기록 없음</p>
        )}
        {busy && (
          <p role="status" className="text-lg font-bold">
            불러오는 중
          </p>
        )}
        {more && (
          <button
            className="btn btn-outline w-full"
            disabled={busy}
            onClick={() => setOffset(rows.length)}
          >
            검사 기록 더 보기
          </button>
        )}
      </div>
    </Modal>
  );
}

export default function History() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const loadMode = params.get("load") === "1";
  const setW = useApp((s) => s.setWizard);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [selected, setSelected] = useState<Job | null>(null);

  const refresh = () => {
    setLoading(true);
    api<Job[]>("/api/jobs")
      .then((rows) => {
        setJobs(rows);
        setMore(rows.length === 100);
      })
      .catch(reportError)
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const loadMore = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const rows = await api<Job[]>(`/api/jobs?offset=${jobs.length}`);
      setJobs((old) => [...old, ...rows]);
      setMore(rows.length === 100);
    } catch (e) {
      reportError(e);
    } finally {
      setLoading(false);
    }
  };

  const loadJob = (job: Job) => {
    const cfg = job.config;
    if (job.mode === "condition" && cfg) {
      setW({
        step: 3,
        brandId: cfg.brandId ?? null,
        checks: cfg.checks ?? {
          rfid: false,
          ocr: false,
          barcode_tag: false,
          barcode_poly: false,
        },
        countMode: cfg.countMode ?? "target",
        target: cfg.target ?? 40,
        sku: cfg.item?.sku ?? "",
        color: cfg.item?.color ?? "",
        size: cfg.item?.size ?? "",
        targets: cfg.targets || {
          style: cfg.item?.sku || "",
          color: cfg.item?.color || "",
          size: cfg.item?.size || "",
        },
      });
      nav("/condition/setup");
    } else {
      nav("/simple");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav("/")}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">
          {loadMode ? "이전 작업 불러오기" : "작업 기록"}
        </h1>
        <button
          className="btn btn-outline btn-sm ml-auto"
          disabled={loading}
          onClick={refresh}
        >
          <RefreshCw size={18} /> 새로고침
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-6xl space-y-4">
          <div className="card overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b-2 border-line bg-panel text-left">
                  <th className="px-5 py-3.5 text-base font-extrabold">날짜</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">시각</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">방식</th>
                  <th className="px-4 py-3.5 text-base font-extrabold">
                    브랜드
                  </th>
                  <th className="px-4 py-3.5 text-base font-extrabold">품번</th>
                  <th className="px-4 py-3.5 text-right text-base font-extrabold">
                    수량
                  </th>
                  <th className="px-4 py-3.5 text-base font-extrabold">
                    저장 위치
                  </th>
                  <th className="px-4 py-3.5" />
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-5 py-10 text-center text-lg font-semibold text-ink-700"
                    >
                      불러오는 중…
                    </td>
                  </tr>
                )}
                {!loading && jobs.length === 0 && (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-5 py-10 text-center text-lg font-semibold text-ink-700"
                    >
                      저장된 작업이 없습니다
                    </td>
                  </tr>
                )}
                {jobs.map((job) => (
                  <tr
                    key={job.id}
                    className="border-b border-line last:border-b-0 hover:bg-panel/60"
                  >
                    <td className="px-5 py-3.5 text-base font-bold tabular-nums">
                      {job.date}
                    </td>
                    <td className="px-4 py-3.5 text-base font-semibold tabular-nums">
                      {job.time}
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={
                          "rounded-md px-2.5 py-1 text-lg font-bold " +
                          (job.mode === "condition"
                            ? "bg-brand-50 text-brand-700"
                            : "bg-panel text-ink-700")
                        }
                      >
                        {job.mode === "condition" ? "조건 계수" : "단순 계수"}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-base font-bold">
                      {job.config?.brandName ?? "없음"}
                    </td>
                    <td className="px-4 py-3.5 text-base font-semibold">
                      {job.config?.item?.sku || "없음"}
                    </td>
                    <td className="px-4 py-3.5 text-right text-lg font-extrabold tabular-nums">
                      {job.count}벌
                    </td>
                    <td
                      className="max-w-[220px] truncate px-4 py-3.5 text-lg font-semibold text-ink-700"
                      title={job.dir}
                    >
                      {job.dir}
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <button
                        className="btn btn-outline btn-sm mb-2"
                        onClick={() => setSelected(job)}
                      >
                        검사 기록
                      </button>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => loadJob(job)}
                      >
                        <FolderOpen size={18} /> 불러오기
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {more && (
            <button
              className="btn btn-outline w-full"
              disabled={loading}
              onClick={loadMore}
            >
              작업 더 보기
            </button>
          )}
        </div>
      </div>
      {selected && (
        <InspectionHistory
          key={selected.id}
          job={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
