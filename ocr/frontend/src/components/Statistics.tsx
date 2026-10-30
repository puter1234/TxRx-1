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
    [busy, setBusy] = useState(false),
    [loadedParams, setLoadedParams] = useState(""),
    [loadError, setLoadError] = useState(""),
    [reload, setReload] = useState(0);
  const params = new URLSearchParams({
    since,
    until,
    include_tests: String(test),
    ...(brand ? { brand_id: brand } : {}),
    ...(preset ? { preset_id: preset } : {}),
  }).toString();
  const validRange = !!since && !!until && since <= until;
  useEffect(() => {
    setLoadedParams("");
    setData(null);
    setLoadError("");
    setBusy(false);
    if (!validRange) return;
    let alive = true;
    setBusy(true);
    api("/statistics?" + params)
      .then((r) => {
        if (alive) {
          setData(r);
          setLoadedParams(params);
        }
      })
      .catch((error) => {
        if (alive) setLoadError(error instanceof Error ? error.message : "불러오기 실패");
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [params, reload]);
  const brandName = (id: string) => brands.find((b) => b.id === id)?.name;
  const works = presets
    .filter((p) => (brand ? p.brand_id === brand : p.kind !== "condition" || brandName(p.brand_id)))
    .map((p) => ({
      id: p.id,
      name: (p.kind === "condition" ? `${brandName(p.brand_id)} ${p.name}` : p.name) + (p.enabled ? "" : " (사용 안 함)"),
    }));
  const currentData = loadedParams === params ? data : null;
  const rows = currentData?.[kind] || [];
  const canExport = validRange && !busy && !loadError && currentData !== null;
  const hours = (s: number | null) => s == null ? "미기록" : (s / 3600).toFixed(2);
  return (
    <section className="card space-y-5 p-6 text-xl">
      <h2 className="text-[32px] font-black">작업 통계</h2>
      {!!currentData?.timing_unknown_jobs && <p className="text-xl font-bold">시간 미기록 {currentData.timing_unknown_jobs}건 제외</p>}
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xl font-extrabold">
          시작일
          <input
            className="field"
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
          />
        </label>
        <label className="text-xl font-extrabold">
          종료일
          <input
            className="field"
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-3 p-3 text-xl font-extrabold">
          <input
            type="checkbox"
            className="h-8 w-8 accent-brand-600"
            checked={test}
            onChange={(e) => setTest(e.target.checked)}
          />
          시험 포함
        </label>
      </div>
      <div className="flex gap-3">
        <label className="text-xl font-extrabold">
          브랜드
          <select
            aria-label="통계 브랜드"
            className="field"
            value={brand}
            onChange={(e) => {
              setBrand(e.target.value);
              setPreset("");
            }}
          >
            <option value="">전체</option>
            {brands.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xl font-extrabold">
          작업
          <select
            aria-label="통계 작업"
            className="field"
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
          >
            <option value="">전체</option>
            {works.map((p) => (
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
        <button className="btn btn-outline" disabled={busy || !validRange} onClick={() => setReload(v => v + 1)}>
          다시 조회
        </button>
        <a
          className={"btn btn-outline ml-auto" + (canExport ? "" : " opacity-50")}
          aria-disabled={!canExport}
          href={canExport ? `/api/statistics.csv?${params}&kind=${kind}` : undefined}
        >
          CSV 내보내기
        </a>
        <a
          className={"btn btn-outline" + (canExport ? "" : " opacity-50")}
          aria-disabled={!canExport}
          href={canExport ? `/api/statistics.csv?${params}&kind=inspections` : undefined}
        >
          검사 상세 CSV
        </a>
      </div>
      {!validRange ? <p role="alert">기간 확인</p> : loadError ? <p role="alert">{loadError}</p> : busy ? (
        <p role="status">불러오는 중</p>
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
                  "DI1 감지",
                  "DI2 통과",
                  "비전 통과",
                  "카메라 재연결",
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
          {!rows.length && <p className="p-5">기록 없음</p>}
        </div>
      )}
    </section>
  );
}
