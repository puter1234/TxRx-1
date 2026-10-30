import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Lock, Tags, SlidersHorizontal, FlaskConical, Cpu, FileClock, Settings as Gear, Download } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../station/shared";
import BrandSettings from "../components/BrandSettings";
import WorkPresets from "../components/WorkPresets";
import Statistics from "../components/Statistics";
import { useBench } from "../components/DeviceTests";
import { WiringPanel } from "../components/DeviceSettings";
import TestBench from "./TestBench";
import { Equipment as EquipmentDetails } from "../station/StationApp";
import { useApp } from "../lib/store";
import { ended, refreshBrands, reportError } from "../lib/station";
import { Keypad, Notice } from "../ui/kit";

export function LoginGate({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState(""),
    [again, setAgain] = useState(""),
    [field, setField] = useState<"pw" | "again">("pw"),
    [configured, setConfigured] = useState<boolean | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    // A server still starting up is checked again until it answers.
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const check = () =>
      api("/auth")
        .then((r) => { if (alive) { setConfigured(r.configured); setError(""); } })
        .catch((e) => { if (alive) { setError(e.message); timer = setTimeout(check, 2000); } });
    check();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (busy || configured === null) return;
    setBusy(true);
    setError("");
    try {
      await api(configured ? "/auth/login" : "/auth/setup", { password: pw });
      onOk();
    } catch (e) {
      setError((e as Error).message);
      setPw("");
      setAgain("");
      setField("pw");
    } finally {
      setBusy(false);
    }
  };
  const ready = !!pw && configured !== null && (configured || (pw.length >= 6 && pw === again));
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <form className="card w-full max-w-xl space-y-6 p-10" onSubmit={submit}>
        <h2 className="flex items-center gap-4 text-[44px] font-black">
          <Lock size={48} strokeWidth={2.5} />
          {configured === false ? "비밀번호 만들기" : "설정 잠금"}
        </h2>
        <label className="block text-[28px] font-extrabold">
          {configured === false ? "새 비밀번호 6자리 이상" : "비밀번호"}
          <input
            className="field mt-3 !min-h-[84px] text-center !text-[48px] tracking-[0.4em]"
            type="password"
            autoComplete={configured ? "current-password" : "new-password"}
            autoFocus
            value={pw}
            maxLength={64}
            disabled={busy}
            onFocus={() => setField("pw")}
            onChange={(e) => {
              setPw(e.target.value);
              setError("");
            }}
          />
        </label>
        {configured === false && (
          <label className="block text-[28px] font-extrabold">
            비밀번호 확인
            <input
              type="password"
              className="field mt-3 !min-h-[84px] text-center !text-[48px] tracking-[0.4em]"
              value={again}
              disabled={busy}
              onFocus={() => setField("again")}
              onChange={(e) => setAgain(e.target.value)}
            />
          </label>
        )}
        {error && <Notice>{error}</Notice>}
        <Keypad
          disabled={busy}
          onKey={(k) => {
            setError("");
            (field === "pw" ? setPw : setAgain)((v) => (k === "clear" ? "" : k === "back" ? v.slice(0, -1) : (v + k).slice(0, 64)));
          }}
        />
        <button className="btn btn-primary btn-xl w-full" disabled={busy || !ready}>
          {busy ? "확인 중" : "확인"}
        </button>
      </form>
    </div>
  );
}

const SECTIONS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: "test", label: "시험", icon: FlaskConical },
  { id: "brands", label: "브랜드", icon: Tags },
  { id: "presets", label: "계수 설정", icon: SlidersHorizontal },
  { id: "records", label: "기록", icon: FileClock },
  { id: "devices", label: "장비 정보", icon: Cpu },
  { id: "general", label: "일반", icon: Gear },
];
// Addresses of the old device, camera and tab screens open the matching place.
const LEGACY: Record<string, string> = {
  general: "general", brands: "brands", presets: "presets", logs: "records", camera: "test",
  sensors: "test", ocr: "test", rfid: "test", connections: "devices", details: "devices",
};

export default function Settings() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const requested = params.get("section") || LEGACY[params.get("tab") || ""] || "test";
  const section = SECTIONS.some((x) => x.id === requested) ? requested : "test";
  const [authed, setAuthed] = useState<boolean | null>(null);
  const brands = useApp((s) => s.brands);
  const snapshot = useApp((s) => s.snapshot);
  useEffect(() => {
    const expired = () => setAuthed(false);
    let alive = true;
    api("/auth")
      .then((result) => { if (alive) setAuthed(result.authenticated && result.user?.role === "admin"); })
      .catch(() => alive && setAuthed(false));
    window.addEventListener("txrx-login-required", expired);
    return () => {
      alive = false;
      window.removeEventListener("txrx-login-required", expired);
    };
  }, []);
  const go = (id: string) => setParams({ section: id }, { replace: true });
  const lock = async () => {
    try {
      await api("/auth/logout", {});
      setAuthed(false);
    } catch (e) {
      reportError(e);
    }
  };
  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-6 px-8 pb-4 pt-6">
        <button className="btn btn-outline btn-lg" onClick={() => nav("/")}>
          처음
        </button>
        <h1 className="text-[44px] font-black">설정</h1>
        {authed && (
          <button className="btn btn-outline btn-lg ml-auto" onClick={lock}>
            <Lock size={32} />
            잠그기
          </button>
        )}
      </header>
      {authed === null ? null : !authed ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <LoginGate onOk={() => setAuthed(true)} />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 gap-6 px-8 pb-6">
          <nav aria-label="설정 항목" className="flex w-[300px] shrink-0 flex-col gap-3">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                aria-current={section === id ? "page" : undefined}
                className={"btn btn-lg w-full !justify-start " + (section === id ? "btn-primary" : "btn-outline")}
                onClick={() => go(id)}
              >
                <Icon size={34} />
                {label}
              </button>
            ))}
          </nav>
          <section className="min-h-0 min-w-0 flex-1 overflow-y-auto pr-1">
            {section === "brands" && (
              <BrandSettings brands={brands.map((b) => b.source)} refresh={async () => { await refreshBrands(); }} locked={!ended(snapshot?.session)} />
            )}
            {section === "test" && <TestBench />}
            {section === "presets" && <WorkPresets initialKind={params.get("kind") === "vision" ? "vision" : "simple"} />}
            {section === "devices" && <Devices />}
            {section === "records" && <Records />}
            {section === "general" && <General />}
          </section>
        </div>
      )}
    </div>
  );
}

function Devices() {
  const bench = useBench();
  return (
    <div className="space-y-6">
      <WiringPanel bench={bench} />
      <EquipmentDetails action={async (fn) => { try { await fn(); } catch (e) { reportError(e); } }} role="operator" />
    </div>
  );
}

function Records() {
  const [backup, setBackup] = useState("");
  return (
    <div className="space-y-6">
      <Statistics />
      <section className="card flex items-center gap-6 p-6">
        <h2 className="text-[32px] font-black">백업</h2>
        {backup && <p role="status" className="text-[26px] font-extrabold text-ok">{backup}</p>}
        <button
          className="btn btn-outline btn-lg ml-auto"
          onClick={async () => {
            setBackup("");
            try {
              const b = await api("/backup", {});
              const a = document.createElement("a");
              a.href = "/api/backups/" + b.name;
              a.download = b.name;
              a.click();
              setBackup("백업 완료");
            } catch (e) {
              reportError(e);
            }
          }}
        >
          <Download size={32} />
          검사 기록 백업
        </button>
      </section>
      <EventLog />
    </div>
  );
}

const EVENT_LABEL: Record<string, string> = {
  ADMIN_INITIALIZED: "비밀번호 설정",
  BACKUP_CREATED: "백업",
  BACKUP_FAILED: "백업 실패",
  BENCH_CAMERA_BATCH: "시험 여러 장 촬영",
  BENCH_CAMERA_CAPTURE: "시험 사진",
  BENCH_ERROR_CLEARED: "시험 오류 정리",
  BENCH_OUTPUT_OFF: "시험 출력 끔",
  BENCH_OUTPUT_START: "시험 출력 켬",
  BENCH_OUTPUT_STOP: "시험 출력 정지",
  BENCH_RELEASED: "시험 입력 반환",
  BENCH_RFID_ERROR: "RFID 시험 오류",
  BENCH_RFID_RESULT: "RFID 시험",
  BENCH_RFID_SETUP_SAVED: "RFID 설정 저장",
  BENCH_SETUP_SAVED: "입출력 설정 저장",
  BENCH_VISION_TRIAL_START: "와펜 계수 시험",
  BRAND_DELETED: "브랜드 삭제",
  BRAND_SAVED: "브랜드 저장",
  CAMERA_CAPTURE_MISSED: "촬영 누락",
  CAMERA_CLOSED: "카메라 끔",
  CAMERA_CONTROLS_RESTORED: "카메라 초점 되돌림",
  CAMERA_DISCONNECTED: "카메라 끊김",
  CAMERA_RECONNECTED: "카메라 다시 연결",
  CAMERA_RECOVERED: "카메라 재연결",
  CAMERA_RETRY: "카메라 재연결 시도",
  CAMERA_RETRY_FAILED: "카메라 재연결 실패",
  CAMERA_SETTINGS_SAVED: "카메라 설정 저장",
  CAMERA_STREAM_RESTART: "카메라 영상 다시 시작",
  CAPTURE_FINISHED: "촬영 끝",
  CAPTURE_READY: "촬영 준비",
  CAPTURE_STARTED: "촬영 시작",
  COMMAND: "작업 조작",
  DAILY_BACKUP_CREATED: "자동 백업",
  DATABASE_WRITE_FAILED: "기록 저장 실패",
  DI1_DETECTED: "센서 1 감지",
  DI2_DETECTED: "센서 2 감지",
  FAULT: "장비 오류",
  HIGH_SPEED_SELECTED: "고속 선택",
  INSPECTION_ABORTED: "검사 중단",
  INSPECTION_BEGIN: "검사 시작",
  INSPECTION_FINAL: "검사 완료",
  LOGIN: "설정 잠금 해제",
  MANUAL_ADJUSTMENT: "수량 보정",
  MODEL_SELECTED: "계수 모델 선택",
  PASS_PHOTO_NOT_RETAINED: "통과 사진 저장 안 함",
  PHOTO_POLICY_CHANGED: "통과 사진 저장 변경",
  PHOTO_POLICY_FAILED: "통과 사진 저장 변경 실패",
  PRESET_SAVED: "계수 설정 저장",
  PROCESS_RESTART: "서버 재시작",
  PRODUCT_DEPARTED: "제품 통과",
  RFID_FINISHED: "RFID 읽기 끝",
  RFID_STARTED: "RFID 읽기 시작",
  SESSION_CREATED: "작업 시작",
  SPEED_WIRING_SAVED: "속도 배선 저장",
  STOP_REQUESTED: "멈춤",
  USER_CHANGED: "비밀번호 변경",
  VISION_CROSSING: "와펜 계수선 통과",
};

function EventLog() {
  const [date, setDate] = useState(new Date().toLocaleDateString("sv-SE")),
    [events, setEvents] = useState<any[]>([]),
    [before, setBefore] = useState<number | null>(null),
    [busy, setBusy] = useState(false),
    [more, setMore] = useState(false);
  useEffect(() => {
    if (!date) return;
    let alive = true;
    const start = new Date(date + "T00:00:00"),
      end = new Date(start);
    end.setDate(end.getDate() + 1);
    const params = new URLSearchParams({ since: start.toISOString(), until: end.toISOString() });
    if (before !== null) params.set("before_seq", String(before));
    setBusy(true);
    api("/event-history?" + params)
      .then((r) => {
        if (!alive) return;
        setEvents((old) => (before === null ? r.events : [...old, ...r.events]));
        setMore(r.events.length === 200);
      })
      .catch(reportError)
      .finally(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
  }, [date, before]);
  return (
    <section className="card space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-6">
        <h2 className="text-[32px] font-black">작업 로그</h2>
        <input
          type="date"
          aria-label="로그 날짜"
          className="field !w-72"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            setBefore(null);
            setEvents([]);
          }}
        />
      </div>
      <div className="divide-y-2 divide-line">
        {events.map((e) => (
          <details key={e.seq} className="py-3">
            <summary className="cursor-pointer text-[26px] font-extrabold">
              <span className="tabular-nums">{new Date(e.created_at).toLocaleTimeString("ko-KR")}</span> {EVENT_LABEL[e.kind] || "기타"}
            </summary>
            <pre className="mt-3 overflow-auto whitespace-pre-wrap rounded-xl bg-panel p-4 text-[18px]">{JSON.stringify(e.body, null, 2)}</pre>
          </details>
        ))}
      </div>
      {!busy && !events.length && <p className="text-[26px] font-extrabold text-ink-700">기록 없음</p>}
      {busy && <p role="status" className="text-[26px] font-extrabold">불러오는 중</p>}
      {more && (
        <button className="btn btn-outline btn-lg w-full" disabled={busy} onClick={() => setBefore(events[events.length - 1].seq)}>
          더 보기
        </button>
      )}
    </section>
  );
}

function General() {
  const [savePhotos, setSavePhotos] = useState<boolean | null>(null),
    [saving, setSaving] = useState(false),
    [current, setCurrent] = useState(""),
    [next, setNext] = useState(""),
    [confirm, setConfirm] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const equipment = useApp((s) => s.equipment),
    snapshot = useApp((s) => s.snapshot);
  const idle = ended(snapshot?.session);
  useEffect(() => {
    api("/settings")
      .then((s) => setSavePhotos(s.save_photos))
      .catch(reportError);
  }, []);
  const change = async () => {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await api("/auth/password", { current, next });
      setCurrent("");
      setNext("");
      setConfirm("");
      setMessage("변경됨");
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid max-w-6xl grid-cols-2 gap-6">
      {!idle && (
        <p role="alert" className="col-span-2 rounded-2xl bg-warn-bg p-5 text-[26px] font-extrabold">작업 진행 중</p>
      )}
      <section className="card space-y-6 p-6">
        <h2 className="text-[32px] font-black">통과 사진 저장</h2>
        <div role="group" aria-label="통과 사진 저장" className="grid grid-cols-2 gap-4">
          {[true, false].map((on) => (
            <button
              key={String(on)}
              className={"btn btn-xl " + (savePhotos === on ? "btn-primary" : "btn-outline")}
              aria-pressed={savePhotos === on}
              disabled={savePhotos === null || saving || !idle}
              onClick={async () => {
                if (saving || savePhotos === on) return;
                setSaving(true);
                try {
                  const result = await api("/settings", { save_photos: on }, "PUT");
                  setSavePhotos(result.save_photos);
                } catch (e) {
                  reportError(e);
                } finally {
                  setSaving(false);
                }
              }}
            >
              {on ? "저장" : "저장 안 함"}
            </button>
          ))}
        </div>
        <div>
          <h3 className="text-[26px] font-extrabold">저장 위치</h3>
          <p className="mt-2 break-all rounded-xl bg-panel p-4 text-[22px] font-bold">{equipment?.data_dir || "확인 중"}</p>
        </div>
      </section>
      <section className="card space-y-5 p-6">
        <h2 className="text-[32px] font-black">비밀번호 바꾸기</h2>
        {[
          ["현재 비밀번호", current, setCurrent, "current-password"],
          ["새 비밀번호", next, setNext, "new-password"],
          ["새 비밀번호 확인", confirm, setConfirm, "new-password"],
        ].map(([label, value, set, auto]) => (
          <label key={label as string} className="block text-[26px] font-extrabold">
            {label as string}
            <input
              className="field mt-2"
              type="password"
              autoComplete={auto as string}
              value={value as string}
              disabled={!idle}
              onChange={(e) => (set as (v: string) => void)(e.target.value)}
            />
          </label>
        ))}
        <button className="btn btn-primary btn-lg w-full" disabled={busy || !idle || !current || next.length < 6 || next !== confirm} onClick={change}>
          바꾸기
        </button>
        {message && <Notice tone="ok">{message}</Notice>}
      </section>
    </div>
  );
}

