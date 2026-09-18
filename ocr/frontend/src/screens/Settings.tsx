import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Lock, Delete, KeyRound, Download } from "lucide-react";
import { api } from "../station/shared";
import Config from "../station/Config";
import { useApp } from "../lib/store";
import { ended, refreshBrands, reportError } from "../lib/station";
import Help from "../components/Help";
import DeviceSettings from "../components/DeviceSettings";

export function LoginGate({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState(""),
    [again, setAgain] = useState(""),
    [configured, setConfigured] = useState<boolean | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/auth")
      .then((r) => setConfigured(r.configured))
      .catch((e) => setError(e.message));
  }, []);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || configured === null) return;
    setBusy(true);
    setError("");
    try {
      await api(configured ? "/auth/login" : "/auth/setup", { password: pw });
      onOk();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <form className="card w-full max-w-md p-8" onSubmit={submit}>
        <div className="flex items-center gap-4">
          <Lock size={32} />
          <h2 className="text-2xl font-extrabold">
            {configured === false ? "비밀번호 설정" : "환경 설정 잠금"}
          </h2>
          <Help text="환경 설정을 열 때만 비밀번호를 입력합니다. 계수 화면은 비밀번호 없이 사용할 수 있습니다." />
        </div>
        <label className="mt-6 block text-lg font-bold">
          {configured === false ? "새 비밀번호 (6자 이상)" : "비밀번호"}
          <input
            className="field mt-2"
            type="password"
            autoComplete={configured ? "current-password" : "new-password"}
            autoFocus
            value={pw}
            maxLength={64}
            disabled={busy}
            onChange={(e) => {
              setPw(e.target.value);
              setError("");
            }}
          />
        </label>
        {configured === false && (
          <label className="mt-4 block text-lg font-bold">
            비밀번호 확인
            <input
              type="password"
              className="field mt-2"
              value={again}
              disabled={busy}
              onChange={(e) => setAgain(e.target.value)}
            />
          </label>
        )}
        {error && (
          <p role="alert" className="mt-3 text-lg font-bold text-danger">
            {error}
          </p>
        )}
        <div className="mt-5 grid grid-cols-3 gap-3">
          {[
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "clear",
            "0",
            "back",
          ].map((k) => (
            <button
              key={k}
              type="button"
              aria-label={
                k === "back"
                  ? "한 글자 지우기"
                  : k === "clear"
                    ? "모두 지우기"
                    : k
              }
              disabled={busy}
              className="btn btn-outline !min-h-[60px] text-2xl font-black"
              onClick={() => {
                setError("");
                setPw((p) =>
                  k === "clear"
                    ? ""
                    : k === "back"
                      ? p.slice(0, -1)
                      : (p + k).slice(0, 64),
                );
              }}
            >
              {k === "clear" ? "지움" : k === "back" ? <Delete size={26} /> : k}
            </button>
          ))}
        </div>
        <button
          className="btn btn-primary btn-lg mt-4 w-full"
          disabled={
            busy ||
            configured === null ||
            !pw ||
            (configured === false && (pw.length < 6 || pw !== again))
          }
        >
          {busy ? "확인 중" : "확인"}
        </button>
      </form>
    </div>
  );
}
function GeneralTab() {
  const [savePhotos, setSavePhotos] = useState<boolean | null>(null),
    [saving, setSaving] = useState(false);
  useEffect(() => {
    api("/settings")
      .then((s) => setSavePhotos(s.save_photos))
      .catch(reportError);
  }, []);
  const [current, setCurrent] = useState(""),
    [next, setNext] = useState(""),
    [confirm, setConfirm] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const equipment = useApp((s) => s.equipment),
    snapshot = useApp((s) => s.snapshot);
  const change = async () => {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await api("/auth/password", { current, next });
      setCurrent("");
      setNext("");
      setConfirm("");
      setMessage("비밀번호를 변경했습니다.");
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid max-w-5xl grid-cols-2 gap-5">
      <div className="card space-y-5 p-6">
        <div className="flex items-center">
          <h2 className="text-xl font-extrabold">검사 기록</h2>
          <Help text="검사 결과와 사진은 이 컴퓨터에 저장합니다. 백업 버튼은 검사 기록 데이터베이스를 저장합니다. 전체 사진 백업은 운영 문서의 절차를 사용합니다." />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold">통과 사진 저장</span>
          <Help text="끄면 이후 작업의 합격 사진은 검사 후 남기지 않습니다. 불합격 사진과 판독 결과는 저장합니다. 진행 중인 작업을 종료한 뒤 변경할 수 있습니다." />
          <button
            type="button"
            role="switch"
            aria-label="통과 사진 저장"
            aria-checked={savePhotos === true}
            disabled={
              savePhotos === null || saving || !ended(snapshot?.session)
            }
            className={
              "btn min-w-24 " + (savePhotos ? "btn-primary" : "btn-outline")
            }
            onClick={async () => {
              if (saving) return;
              setSaving(true);
              try {
                const next = await api(
                  "/settings",
                  { save_photos: !savePhotos },
                  "PUT",
                );
                setSavePhotos(next.save_photos);
              } catch (e) {
                reportError(e);
              } finally {
                setSaving(false);
              }
            }}
          >
            {savePhotos === null ? "확인 중" : savePhotos ? "켜짐" : "꺼짐"}
          </button>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold">계수 방식</span>
          <span className="text-lg font-bold">정지 후 검사</span>
          <Help text="이동 중 임계선을 지날 때 세던 기존 설정은 적용하지 않습니다. 제품을 멈추고 검사한 뒤 한 제품을 한 번 셉니다. 검출 라이브러리와 장비 실측은 확인이 필요합니다." />
        </div>
        <div>
          <strong className="text-lg">저장 위치</strong>
          <p className="mt-3 break-all rounded-xl bg-panel p-4 text-lg font-semibold">
            {equipment?.data_dir || "확인 중"}
          </p>
        </div>
        <button
          className="btn btn-outline w-full"
          onClick={async () => {
            try {
              const b = await api("/backup", {});
              const a = document.createElement("a");
              a.href = "/api/backups/" + b.name;
              a.download = b.name;
              a.click();
            } catch (e) {
              reportError(e);
            }
          }}
        >
          <Download size={22} />
          검사 기록 백업
        </button>
      </div>
      <div className="card space-y-4 p-6">
        <h2 className="flex items-center gap-3 text-xl font-extrabold">
          <KeyRound size={24} />
          비밀번호 변경
        </h2>
        <label className="block text-lg font-bold">
          현재 비밀번호
          <input
            className="field mt-2"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className="block text-lg font-bold">
          새 비밀번호
          <input
            className="field mt-2"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </label>
        <label className="block text-lg font-bold">
          비밀번호 확인
          <input
            className="field mt-2"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </label>
        <button
          className="btn btn-primary w-full"
          disabled={
            busy ||
            !ended(snapshot?.session) ||
            !current ||
            next.length < 6 ||
            next !== confirm
          }
          onClick={change}
        >
          변경
        </button>
        {message && (
          <p role="status" className="text-lg font-bold">
            {message}
          </p>
        )}
      </div>
    </div>
  );
}
function LogTab() {
  const [date, setDate] = useState(new Date().toLocaleDateString("sv-SE")),
    [events, setEvents] = useState<any[]>([]);
  const [before, setBefore] = useState<number | null>(null),
    [busy, setBusy] = useState(false),
    [more, setMore] = useState(false);
  useEffect(() => {
    if (!date) return;
    let alive = true;
    const start = new Date(date + "T00:00:00"),
      end = new Date(start);
    end.setDate(end.getDate() + 1);
    const params = new URLSearchParams({
      since: start.toISOString(),
      until: end.toISOString(),
    });
    if (before !== null) params.set("before_seq", String(before));
    setBusy(true);
    api("/event-history?" + params)
      .then((r) => {
        if (alive) {
          setEvents((old) =>
            before === null ? r.events : [...old, ...r.events],
          );
          setMore(r.events.length === 200);
        }
      })
      .catch(reportError)
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [date, before]);
  const labels: Record<string, string> = {
    COMMAND: "작업 조작",
    INSPECTION_FINAL: "검사 완료",
    SESSION_CREATED: "작업 시작",
    MANUAL_ADJUSTMENT: "수량 보정",
    BRAND_SAVED: "브랜드 저장",
    PROCESS_RESTART: "서버 재시작",
    LOGIN: "설정 잠금 해제",
    ADMIN_INITIALIZED: "비밀번호 설정",
  };
  return (
    <div className="max-w-5xl space-y-4">
      <label className="flex items-center gap-4 text-lg font-bold">
        날짜 선택
        <input
          type="date"
          className="field !w-56"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            setBefore(null);
            setEvents([]);
          }}
        />
      </label>
      <div className="card space-y-4 p-5">
        {events.map((e) => (
          <details key={e.seq} className="border-b border-line pb-4">
            <summary className="cursor-pointer text-lg font-bold">
              {new Date(e.created_at).toLocaleTimeString("ko-KR")}{" "}
              {labels[e.kind] || e.kind}
            </summary>
            <pre className="mt-3 overflow-auto whitespace-pre-wrap text-base">
              {JSON.stringify(e.body, null, 2)}
            </pre>
          </details>
        ))}
        {!busy && !events.length && (
          <p className="text-lg font-bold">기록 없음</p>
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
            onClick={() => setBefore(events[events.length - 1].seq)}
          >
            이전 기록 더 보기
          </button>
        )}
      </div>
    </div>
  );
}
export default function Settings() {
  const [params] = useSearchParams();
  const nav = useNavigate(),
    [authed, setAuthed] = useState(false),
    [tab, setTab] = useState(params.get("tab") === "devices" ? "devices" : "general");
  const brands = useApp((s) => s.brands),
    snapshot = useApp((s) => s.snapshot);
  useEffect(() => {
    const expired = () => setAuthed(false);
    window.addEventListener("txrx-login-required", expired);
    return () => window.removeEventListener("txrx-login-required", expired);
  }, []);
  const home = async () => {
    if (authed) {
      try {
        await api("/auth/logout", {});
      } catch (e) {
        reportError(e);
        return;
      }
    }
    nav("/");
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={home}>
          <ArrowLeft size={20} />
          처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">환경 설정</h1>
        {authed && (
          <div className="ml-6 flex gap-2">
            {[
              { id: "general", label: "일반" },
              { id: "brands", label: "브랜드 관리" },
              { id: "devices", label: "장비 연결" },
              { id: "logs", label: "작업 로그" },
            ].map((t) => (
              <button
                key={t.id}
                className={
                  "rounded-xl px-5 py-3 text-lg font-extrabold " +
                  (tab === t.id
                    ? "bg-brand-600 text-white"
                    : "bg-white text-ink-900")
                }
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {!authed ? (
          <LoginGate onOk={() => setAuthed(true)} />
        ) : tab === "general" ? (
          <GeneralTab />
        ) : tab === "devices" ? (
          <DeviceSettings />
        ) : tab === "brands" ? (
          <Config
            brands={brands.map((b) => b.source)}
            action={async (fn) => {
              try {
                await fn();
              } catch (e) {
                reportError(e);
              }
            }}
            refresh={async () => {
              await refreshBrands();
            }}
            locked={!ended(snapshot?.session)}
          />
        ) : (
          <LogTab />
        )}
      </div>
    </div>
  );
}
