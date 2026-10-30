import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { RotateCcw, ListChecks } from "lucide-react";
import { api, errorText, type Result, type Session } from "../station/shared";
import { useApp } from "../lib/store";
import { ended, reportError } from "../lib/station";
import { jobTitle, useRedo } from "../lib/jobs";
import { optionColorStyle } from "../lib/optionColors";
import { Screen, Sheet } from "../ui/kit";

const PAGE = 100;
const day = (iso: string) => new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
const time = (iso: string) =>
  new Date(iso).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export default function History() {
  const nav = useNavigate();
  const again = useRedo();
  const active = !ended(useApp((s) => s.snapshot?.session));
  const [rows, setRows] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [selected, setSelected] = useState<Session | null>(null);
  const [failed, setFailed] = useState(false);

  const load = async (offset: number) => {
    setLoading(true);
    setFailed(false);
    try {
      const page = await api<{ sessions: Session[] }>("/history?offset=" + offset);
      setRows((old) => (offset ? [...old, ...page.sessions] : page.sessions));
      setMore(page.sessions.length === PAGE);
    } catch (e) {
      reportError(e);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load(0);
  }, []);

  let lastDay = "";
  return (
    <Screen title="작업 기록" onBack={() => nav("/")}>
      <div className="space-y-4">
        {rows.map((s) => {
          const heading = day(s.created_at) !== lastDay ? (lastDay = day(s.created_at)) : null;
          return (
            <div key={s.id}>
              {heading && <h2 className="mb-3 mt-6 text-[32px] font-black">{heading}</h2>}
              <article className="card flex items-center gap-8 p-6">
                <span className="w-40 shrink-0 text-[36px] font-black tabular-nums">{time(s.created_at)}</span>
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="flex items-center gap-4 text-[36px] font-black">
                    <span className="truncate">{jobTitle(s)}</span>
                    {s.phase === "ABORTED" && <span className="shrink-0 rounded-xl bg-warn px-3 py-1 text-[24px] font-extrabold">중단</span>}
                    {s.recipe.test_run && <span className="shrink-0 rounded-xl border-2 border-ink-500 px-3 py-1 text-[24px] font-extrabold">시험</span>}
                  </p>
                  {s.recipe.kind !== "simple" && s.recipe.kind !== "vision" && (
                    <div className="flex flex-wrap gap-3">
                      {s.brand.options.map((o) => (
                        <span key={o.key} className="rounded-xl border-2 border-ink-700 px-4 py-1 text-[26px] font-extrabold"
                          style={optionColorStyle(o, s.recipe.targets[o.key])}>
                          {s.recipe.targets[o.key]}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <span className="shrink-0 text-[48px] font-black tabular-nums">
                  {s.count}
                  <span className="text-[32px] text-ink-700">개</span>
                </span>
                <button className="btn btn-outline btn-lg" onClick={() => setSelected(s)}>
                  <ListChecks size={34} />
                  검사 내역
                </button>
                <button className="btn btn-primary btn-lg" disabled={active} onClick={() => again(s)}>
                  <RotateCcw size={34} />
                  다시 하기
                </button>
              </article>
            </div>
          );
        })}
        {!loading && !rows.length && !failed && <p className="py-16 text-center text-[40px] font-black text-ink-700">기록 없음</p>}
        {!loading && failed && (
          <button className="btn btn-outline btn-lg w-full" onClick={() => load(rows.length)}>다시 불러오기</button>
        )}
        {loading && <p role="status" className="py-8 text-center text-[32px] font-extrabold">불러오는 중</p>}
        {more && !loading && (
          <button className="btn btn-outline btn-lg w-full" onClick={() => load(rows.length)}>
            더 보기
          </button>
        )}
      </div>
      {selected && <Inspections session={selected} onClose={() => setSelected(null)} />}
    </Screen>
  );
}

function Inspections({ session, onClose }: { session: Session; onClose: () => void }) {
  const [rows, setRows] = useState<Result[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    api<{ inspections: Result[] }>(`/history?session_id=${encodeURIComponent(session.id)}&offset=${offset}`)
      .then((r) => {
        if (!alive) return;
        setRows((old) => (offset ? [...old, ...r.inspections] : r.inspections));
        setMore(r.inspections.length === PAGE);
      })
      .catch(reportError)
      .finally(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
  }, [session.id, offset]);
  const label = (key: string) => session.brand.options.find((o) => o.key === key)?.label || key;
  return (
    <Sheet title={`${jobTitle(session)} 검사`} onClose={onClose} wide>
      <div className="space-y-4">
        {rows.map((r) => {
          const pass = r.status === "PASS";
          const read = Object.values(r.observations || {}).reduce((all, fields) => ({ ...all, ...fields }), {} as Record<string, string>);
          const order = session.brand.options.map((o) => o.key);
          const keys = Object.keys(read).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
          return (
            <article key={r.id} className={"flex gap-6 rounded-2xl border-4 p-5 " + (pass ? "border-ok" : "border-danger")}>
              {r.evidence?.url && <img src={r.evidence.url} alt="검사 사진" className="h-40 w-56 shrink-0 rounded-xl bg-ink-900 object-contain" />}
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex items-center gap-4">
                  <span className={"rounded-xl px-4 py-1 text-[30px] font-black text-white " + (pass ? "bg-ok" : r.status === "FAIL" ? "bg-danger" : "bg-ink-500")}>
                    {pass ? "합격" : r.status === "FAIL" ? "불합격" : "중단"}
                  </span>
                  <span className="text-[30px] font-extrabold tabular-nums">{time(r.created_at)}</span>
                </div>
                {!!Object.keys(read).length && (
                  <p className="text-[28px] font-extrabold">
                    {keys.map((k) => `${label(k)} ${read[k]}`).join("   ")}
                  </p>
                )}
                {r.failures.map((f, i) => (
                  <p key={i} className="text-[28px] font-extrabold text-danger">
                    {errorText(f.code)}
                    {f.field ? `  ${label(f.field)} 목표 ${f.expected ?? ""} 읽음 ${f.actual ?? "없음"}` : ""}
                  </p>
                ))}
              </div>
            </article>
          );
        })}
        {!busy && !rows.length && <p className="py-8 text-center text-[32px] font-black text-ink-700">검사 기록 없음</p>}
        {busy && <p role="status" className="text-[28px] font-extrabold">불러오는 중</p>}
        {more && !busy && (
          <button className="btn btn-outline btn-lg w-full" onClick={() => setOffset(rows.length)}>
            더 보기
          </button>
        )}
      </div>
    </Sheet>
  );
}
