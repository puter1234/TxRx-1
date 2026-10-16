import { useEffect, useState } from "react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { reportError } from "../lib/station";
const today = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(
    new Date(),
  );
export default function Statistics() {
  const brands = useApp((s) => s.brands);
  const [brand, setBrand] = useState(""),
    [preset, setPreset] = useState(""),
    [presets, setPresets] = useState<any[]>([]);
  useEffect(() => {
    api<any[]>("/presets").then(setPresets).catch(reportError);
  }, []);
  const [since, setSince] = useState(today()),
    [until, setUntil] = useState(today()),
    [test, setTest] = useState(false);
  const [kind, setKind] = useState("daily"),
    [data, setData] = useState<any>(null),
    [busy, setBusy] = useState(false);
  const params = new URLSearchParams({
    since,
    until,
    include_tests: String(test),
    ...(brand ? { brand_id: brand } : {}),
    ...(preset ? { preset_id: preset } : {}),
  }).toString();
  useEffect(() => {
    if (!since || !until || since > until) return;
    let alive = true;
    setBusy(true);
    api("/statistics?" + params)
      .then((r) => {
        if (alive) setData(r);
      })
      .catch(reportError)
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [params]);
  const rows = data?.[kind] || [];
  const hours = (s: number | null) => s == null ? "미기록" : (s / 3600).toFixed(2);
  return (
    <section className="card space-y-4 p-5">
      <h2 className="text-2xl font-bold">작업 통계</h2>
      {!!data?.timing_unknown_jobs && <p>종료 시각이 없는 이전 작업 {data.timing_unknown_jobs}건은 시간 합계에서 제외했습니다.</p>}
      <div className="flex flex-wrap items-end gap-3">
        <label className="font-bold">
          시작일
          <input
            className="field"
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
          />
        </label>
        <label className="font-bold">
          종료일
          <input
            className="field"
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
        </label>
        <label className="flex gap-2 p-3">
          <input
            type="checkbox"
            checked={test}
            onChange={(e) => setTest(e.target.checked)}
          />
          시험 포함
        </label>
        <span className="p-3">한국 시간 기준</span>
      </div>
      <div className="flex gap-3">
        <label className="font-bold">
          브랜드
          <select
            aria-label="통계 브랜드"
            className="field"
            value={brand}
            onChange={(e) => setBrand(e.target.value)}
          >
            <option value="">전체</option>
            {brands.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="font-bold">
          작업
          <select
            aria-label="통계 작업"
            className="field"
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
          >
            <option value="">전체</option>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex gap-3">
        {[
          ["daily", "일자별"],
          ["jobs", "작업별"],
        ].map(([key, text]) => (
          <button
            key={key}
            className={"btn " + (kind === key ? "btn-primary" : "btn-outline")}
            onClick={() => setKind(key)}
          >
            {text}
          </button>
        ))}
        <a
          className="btn btn-outline ml-auto"
          href={`/api/statistics.csv?${params}&kind=${kind}`}
        >
          CSV 내보내기
        </a>
        <a
          className="btn btn-outline"
          href={`/api/statistics.csv?${params}&kind=inspections`}
        >
          검사 상세 CSV
        </a>
      </div>
      {busy ? (
        <p role="status">통계를 불러오는 중입니다.</p>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-left">
            <thead>
              <tr>
                {[
                  kind === "daily" ? "일자" : "작업",
                  "수량",
                  "합격",
                  "불합격",
                  "보정",
                  "DI1",
                  "DI2",
                  "비전",
                  "재연결",
                  "운전 (시간)",
                  "정지 (시간)",
                ].map((v) => (
                  <th
                    className="whitespace-nowrap border-b border-line p-3"
                    key={v}
                  >
                    {v}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={r.id || r.date}>
                  {[
                    r.date || r.work,
                    r.count,
                    r.passed,
                    r.failed,
                    r.adjustments,
                    r.di1,
                    r.di2,
                    r.vision,
                    r.camera_retries,
                    hours(r.run_seconds),
                    hours(r.stopped_seconds),
                  ].map((v, i) => (
                    <td className="border-b border-line p-3" key={i}>
                      {v}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="p-5">조회 기간에 기록이 없습니다.</p>}
        </div>
      )}
    </section>
  );
}
