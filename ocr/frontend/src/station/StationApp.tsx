import { useCallback, useEffect, useState } from "react";
import {
  Settings,
  Monitor,
  ClipboardList,
  Play,
  AlertTriangle,
  LogOut,
  Download,
  RefreshCw,
} from "lucide-react";
import Work from "./Work";
import Help from "../components/Help";
import Config from "./Config";
import { api, Field, Badge, ResultCard, PHASE, display } from "./shared";
import type { Action, Snapshot, Brand, Session, Result } from "./shared";

export function Login({
  configured,
  onLogin,
  action,
}: {
  configured: boolean;
  onLogin: () => void;
  action: Action;
}) {
  const [pin, setPin] = useState(""),
    [again, setAgain] = useState(""),
    [submitting, setSubmitting] = useState(false);
  return (
    <main className="mx-auto flex min-h-screen max-w-lg items-center p-6">
      <form
        className="card w-full space-y-6 p-8"
        onSubmit={(e) => {
          e.preventDefault();
          if (submitting) return;
          setSubmitting(true);
          action(async () => {
            try {
              await api(configured ? "/auth/login" : "/auth/setup", {
                password: pin,
              });
              onLogin();
            } catch (error) {
              if (
                error instanceof Error &&
                error.message === "사용자 ID 또는 비밀번호를 확인하세요."
              ) {
                throw new Error("비밀번호를 확인하세요.");
              }
              throw error;
            } finally {
              setSubmitting(false);
            }
          });
        }}
      >
        <div>
          <p className="text-sm font-extrabold tracking-widest text-brand-700">
            TXRX
          </p>
          <h1 className="mt-3 text-3xl font-black">
            {configured ? "비밀번호 입력" : "비밀번호 설정"}
          </h1>
        </div>
        <Field label={configured ? "비밀번호" : "새 비밀번호 (6자 이상)"}>
          <input
            autoComplete={configured ? "current-password" : "new-password"}
            className="field"
            type="password"
            autoFocus
            disabled={submitting}
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            maxLength={64}
          />
        </Field>
        {!configured && (
          <Field label="비밀번호 확인">
            <input
              className="field"
              type="password"
              disabled={submitting}
              value={again}
              onChange={(e) => setAgain(e.target.value)}
            />
          </Field>
        )}
        <button
          className="btn btn-primary w-full"
          disabled={
            submitting ||
            !pin ||
            (!configured && (pin.length < 6 || pin !== again))
          }
        >
          {submitting ? "확인 중…" : configured ? "들어가기" : "설정 후 시작"}
        </button>
      </form>
    </main>
  );
}

const BLOCKERS: Record<string, string> = {
  departure_sensor: "배출 감지 센서 역할 지정",
  sensor_clear_ms: "센서 해제 안정 시간 실측",
  rfid_protocol_verified: "RFID 명령, 응답 실기 검증",
  settle_ms: "정지 후 촬영 안정화 시간 실측",
  inspection_timeout_ms: "최대 검사 시간 확정",
  feedback_timeout_ms: "접촉기 응답 시간 검증",
  release_timeout_ms: "배출 제한 시간 실측",
  product_sensor: "제품 검출 센서 역할 지정",
  sensor_active_raw: "제품 감지 신호 논리 확인",
  detector_module: "제품 검출 라이브러리 연결",
  detector_sha256: "제품 검출 라이브러리 버전 고정",
  signed_by: "현장 확인 담당자",
  evidence_reference: "현장 시험 기록",
  physical_permit_observed: "물리 운전 허가 관측",
  power_cycle_off_verified: "전원 복구 시 출력 꺼짐 시험",
  process_kill_off_verified: "프로그램 강제 종료 정지 시험",
  os_hang_off_verified: "운영체제 정지 시 차단 시험",
  stop_chain_verified: "정지 회로 동작 확인",
  single_product_verified: "제품 한 개 검출 확인",
  camera_calibrated: "카메라 촬영 조건 검증",
};
export function Equipment({ action, role }: { action: Action; role: string }) {
  const [info, setInfo] = useState<any>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const update = async () => {
      try {
        const next = await api("/equipment");
        if (alive) {
          setInfo(next);
          setError("");
        }
      } catch (e) {
        if (alive) setError(String(e));
      } finally {
        if (alive) timer = setTimeout(update, 3000);
      }
    };
    update();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);
  if (!info)
    return <p className="p-8">{error || "장비 정보를 불러오는 중…"}</p>;
  const sys = info.system;
  const items: [string, unknown][] = [
    ["운영체제", sys.os],
    ["보드 정보", sys.identity?.board_model],
    ["L4T/BSP", sys.identity?.l4t_release],
    ["패키지 버전", sys.versions],
    ["프로세스 파일/핸들 수", sys.process_handles],
    ["GPU 부하 원시값", sys.gpu_load],
    ["카메라 실제 수신 FPS", info.camera.mean_received_fps],
    ["카메라 프레임 드롭", info.camera.dropped_frames],
    ["프로세서 구조", sys.architecture],
    ["CPU 사용률", `${sys.cpu_percent}%`],
    ["메모리 사용률", `${sys.memory_percent}%`],
    ["남은 저장 공간", `${(sys.disk_free / 1024 ** 3).toFixed(1)} GB`],
    ["기동 후 시간", `${Math.floor(sys.uptime_seconds / 60)}분`],
    ["I/O 출처", info.io.source],
    ["실물 I/O 연결", info.io.connected],
    ["모터 요청", info.io.motor_requested],
    ["KM2 접촉기 피드백", info.io.km2_on],
    ["물리 운전 허가", info.io.physical_permit],
    ["센서 원시값", info.io.di_raw],
    ["실제 벨트 운동", sys.belt_motion],
    ["외부 공급 전압", sys.external_supply_voltage],
    ["모터 전류", sys.motor_current],
    ["카메라 연결", info.camera.connected],
    ["카메라 프레임 나이(ms)", info.camera.last_frame_age_ms],
    ["카메라 수신 프레임", info.camera.frames],
    ["추론 장치", info.vision.device],
    ["GPU 이름", info.vision.gpu_name],
    ["RFID 초기화", info.io.rfid_ready],
    ["최근 자동 DB 백업", info.last_daily_backup?.day],
    ["로컬 모델 파일", info.vision.local_assets_present],
    ["모델 메모리 적재", info.vision.loaded],
    ["RFID EN 자동 초기화", info.io.supports_en_reset],
  ];
  return (
    <div className="space-y-5">
      {error && (
        <p role="alert" className="rounded-xl bg-danger-bg p-4 text-danger">
          갱신 실패, 아래 정보는 과거 값입니다. {error}
        </p>
      )}
      <div className="card p-6">
        <div className="flex items-center">
          <h2 className="text-2xl font-extrabold">장비 정보</h2>
          <Help text="미확인은 장비에서 읽은 값이 없다는 뜻입니다." />
        </div>
        <p className="mt-2 text-lg font-bold">
          수집 시각{" "}
          {new Date(sys.observed_at * 1000).toLocaleTimeString("ko-KR")}
        </p>
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map(([k, v]) => (
            <div className="rounded-xl bg-panel p-4" key={k}>
              <div className="text-lg font-bold text-ink-900">{k}</div>
              <div className="mt-2 break-all text-lg font-bold">
                {display(v)}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="card p-6">
        <h3 className="text-xl font-extrabold">온도, 전원, 팬 센서</h3>
        {Object.entries(sys.temperatures).map(([k, v]) => (
          <p className="mt-3" key={k}>
            <strong>{k}</strong> {display(v)}
          </p>
        ))}
        {sys.hardware_sensors.map((v: any, i: number) => (
          <p className="mt-3" key={i}>
            <strong>{v.sensor}</strong> {v.raw} {v.unit}
          </p>
        ))}
        {!Object.keys(sys.temperatures).length &&
          !sys.hardware_sensors.length && (
            <p className="mt-3 text-lg font-bold">센서 정보 미확인</p>
          )}
      </div>
      <div className="card p-6">
        <h3 className="text-xl font-extrabold">최근 검사 지표</h3>
        <p className="mt-3">
          최근 {info.metrics?.sample_count}건, 지연 p50/p95/p99(ms):{" "}
          {display(info.metrics?.latency_ms)}
        </p>
        <p>{display(info.metrics?.decisions)}</p>
        <p>채널 요청, 판독: {display(info.metrics?.channels)}</p>
        <p>
          DB {info.metrics?.db_bytes} bytes, WAL {info.metrics?.wal_bytes}{" "}
          bytes, 중단 복구 {info.metrics?.recovery_restarts}회
        </p>
      </div>
      <div className="card p-6">
        <div className="flex items-center">
          <h3 className="text-xl font-extrabold">실물 운전 전 확인할 항목</h3>
          <Help text="장비 실측과 아래 시험을 완료한 후 실물 운전을 사용할 수 있습니다." />
        </div>
        <ul className="mt-4 list-inside list-disc space-y-2">
          {info.blockers.map((b: string) => (
            <li key={b}>{BLOCKERS[b] || b}</li>
          ))}
        </ul>
        <details className="mt-5">
          <summary className="cursor-pointer font-bold">
            상세 진단 정보 전체 보기
          </summary>
          <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all text-base">
            {JSON.stringify(info, null, 2)}
          </pre>
        </details>
        {info.io.fault && <p className="mt-3 text-danger">{info.io.fault}</p>}
      </div>
      {role === "admin" && (
        <button
          className="btn btn-outline"
          onClick={() =>
            action(async () => {
              const b = await api("/backup", {});
              const a = document.createElement("a");
              a.href = "/api/backups/" + b.name;
              a.download = b.name;
              a.click();
            }, "백업과 무결성 검사를 완료했습니다.")
          }
        >
          <Download size={20} />
          검사 기록 DB 백업
        </button>
      )}
    </div>
  );
}

function History({ action }: { action: Action }) {
  const [history, setHistory] = useState<{
      sessions: Session[];
      inspections: Result[];
    }>({ sessions: [], inspections: [] }),
    [selected, setSelected] = useState<Result | null>(null),
    [error, setError] = useState(""),
    [events, setEvents] = useState<any[]>([]),
    [offset, setOffset] = useState(0),
    [more, setMore] = useState(false);
  const refresh = useCallback(
    () =>
      Promise.all([api("/history"), api("/events")])
        .then(([r, e]) => {
          setHistory(r);
          setEvents(e.events);
          setOffset(100);
          setMore(r.inspections.length === 100 || r.sessions.length === 100);
          setError("");
        })
        .catch((e) => {
          setError(e.message);
          throw e;
        }),
    [],
  );
  const loadMore = () =>
    action(async () => {
      const r = await api("/history?offset=" + offset);
      setHistory((h) => ({
        sessions: [
          ...new Map(
            [...h.sessions, ...r.sessions].map((v: Session) => [v.id, v]),
          ).values(),
        ],
        inspections: [
          ...new Map(
            [...h.inspections, ...r.inspections].map((v: Result) => [v.id, v]),
          ).values(),
        ],
      }));
      setOffset((n) => n + 100);
      setMore(r.inspections.length === 100 || r.sessions.length === 100);
    });
  useEffect(() => {
    refresh().catch(() => {});
  }, [refresh]);
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-extrabold">작업, 검사 이력</h2>
        <button className="btn btn-outline" onClick={() => action(refresh)}>
          <RefreshCw size={20} />
          새로고침
        </button>
      </div>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      <div className="card overflow-auto">
        <table className="w-full text-left">
          <thead className="bg-panel">
            <tr>
              {["검사 시각", "출처", "제품", "시도", "판정", "확인"].map(
                (t) => (
                  <th className="p-4" key={t}>
                    {t}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {history.inspections.map((r) => (
              <tr className="border-t border-line" key={r.id}>
                <td className="whitespace-nowrap p-4">
                  {new Date(r.created_at).toLocaleString("ko-KR")}
                </td>
                <td className="p-4">{r.mode}</td>
                <td className="max-w-60 break-all p-4">{r.product_id}</td>
                <td className="p-4">{r.attempt}</td>
                <td className="p-4">
                  <Badge red={r.status !== "PASS"}>{r.status}</Badge>
                </td>
                <td className="p-4">
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={() => setSelected(r)}
                  >
                    상세
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!history.inspections.length && (
          <p className="p-8 text-center text-ink-700">
            저장된 검사 결과가 없습니다.
          </p>
        )}
      </div>
      {more && (
        <button className="btn btn-outline" onClick={loadMore}>
          이전 이력 더 불러오기
        </button>
      )}
      {selected && <ResultCard result={selected} />}
      <div className="card p-6">
        <h3 className="text-xl font-extrabold">작업별 수량</h3>
        {history.sessions.map((s) => (
          <div
            className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4"
            key={s.id}
          >
            <span>
              {new Date(s.created_at).toLocaleString("ko-KR")}, {s.brand.name} ,{" "}
              {s.mode}
            </span>
            <strong>
              {s.count}개 / 합격 {s.passed} / 수동 보정 {s.adjustments} /{" "}
              {PHASE[s.phase] || s.phase}
            </strong>
          </div>
        ))}
      </div>
      <div className="card p-6">
        <h3 className="text-xl font-extrabold">
          최근 변경, 정지 기록 (최대 200건)
        </h3>
        {events
          .slice()
          .reverse()
          .map((e) => (
            <details className="mt-3 border-t border-line pt-3" key={e.seq}>
              <summary className="cursor-pointer">
                {new Date(e.created_at).toLocaleString("ko-KR")}, {e.kind} ,{" "}
                {e.body.actor || "시스템"}
              </summary>
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(e.body, null, 2)}
              </pre>
            </details>
          ))}
      </div>
    </div>
  );
}

export default function StationApp() {
  const [auth, setAuth] = useState<{
      configured: boolean;
      authenticated: boolean;
      user?: { username: string; role: string };
    } | null>(null),
    [state, setState] = useState<Snapshot | null>(null),
    [brands, setBrands] = useState<Brand[]>([]);
  const [tab, setTab] = useState("work"),
    [notice, setNotice] = useState<{
      kind: "error" | "ok";
      text: string;
    } | null>(null),
    [online, setOnline] = useState(false);
  const action: Action = async (work, success) => {
    setNotice(null);
    try {
      await work();
      if (success) setNotice({ kind: "ok", text: success });
    } catch (e) {
      setNotice({
        kind: "error",
        text: e instanceof Error ? e.message : String(e),
      });
    }
  };
  const loadAuth = useCallback(() => {
    api("/auth")
      .then(setAuth)
      .catch((e) => setNotice({ kind: "error", text: e.message }));
  }, []);
  const refresh = useCallback(async () => {
    const [s, b] = await Promise.all([
      api<Snapshot>("/status"),
      api<Brand[]>("/brands"),
    ]);
    setState(s);
    setBrands(b);
    setOnline(true);
  }, []);
  useEffect(() => {
    loadAuth();
    const expired = () => {
      setAuth({ configured: true, authenticated: false });
      setState(null);
      setOnline(false);
    };
    window.addEventListener("txrx-login-required", expired);
    return () => window.removeEventListener("txrx-login-required", expired);
  }, [loadAuth]);
  useEffect(() => {
    if (!auth?.authenticated) return;
    let alive = true;
    let ws: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout>;
    let lastMessage = Date.now();
    const watchdog = setInterval(() => {
      if (Date.now() - lastMessage > 2500) {
        setOnline(false);
        if (ws?.readyState === WebSocket.OPEN) ws.close();
      }
    }, 500);
    const connect = () => {
      ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`,
      );
      ws.onmessage = (e) => {
        if (!alive) return;
        try {
          const message = JSON.parse(e.data);
          lastMessage = Date.now();
          setState(message.state);
          setOnline(true);
          ws?.send(
            JSON.stringify({ type: "heartbeat", event_seq: message.event_seq }),
          );
        } catch {
          setOnline(false);
          ws?.close();
        }
      };
      ws.onerror = () => {
        if (alive) setOnline(false);
      };
      ws.onclose = () => {
        if (!alive) return;
        setOnline(false);
        api("/auth")
          .then((value) => {
            if (alive && !value.authenticated) setAuth(value);
          })
          .catch(() => {});
        timer = setTimeout(connect, 1000);
      };
    };
    connect();
    api<Brand[]>("/brands")
      .then(setBrands)
      .catch((e) => setNotice({ kind: "error", text: e.message }));
    return () => {
      alive = false;
      clearTimeout(timer);
      clearInterval(watchdog);
      ws?.close();
    };
  }, [auth?.authenticated]);
  const banner = notice && (
    <div
      role="alert"
      className={
        "fixed bottom-5 left-1/2 z-50 flex w-[min(92vw,900px)] -translate-x-1/2 items-center gap-4 rounded-xl border p-4 shadow-lg " +
        (notice.kind === "error"
          ? "border-danger bg-danger-bg text-danger"
          : "border-ok bg-ok-bg text-ok")
      }
    >
      <strong className="flex-1">{notice.text}</strong>
      <button
        className="px-3 font-bold"
        aria-label="알림 닫기"
        onClick={() => setNotice(null)}
      >
        닫기
      </button>
    </div>
  );
  if (!auth)
    return (
      <>
        <p className="p-10 text-xl font-bold">로컬 검사 시스템에 연결 중…</p>
        {banner}
      </>
    );
  if (!auth.authenticated)
    return (
      <>
        <Login
          configured={auth.configured}
          onLogin={loadAuth}
          action={action}
        />
        {banner}
      </>
    );
  const tabs = [
    { id: "work", label: "검사 운전", icon: Play },
    { id: "settings", label: "목표, 메이커 설정", icon: Settings },
    { id: "equipment", label: "장비 정보", icon: Monitor },
    { id: "history", label: "검사 이력", icon: ClipboardList },
  ];
  const role = auth.user?.role || "operator";
  const locked =
    !!state?.session &&
    !["FINISHED", "DONE", "ABORTED"].includes(state.session.phase);
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-white px-5 py-4">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3">
          <div className="mr-auto">
            <strong className="text-2xl font-black tracking-tight text-brand-800">
              TXRX
            </strong>
            <span className="ml-3 font-bold text-ink-700">
              자동 계수 시스템
            </span>
          </div>
          <Badge red={!online}>
            {online ? "로컬 연결됨" : "연결 끊김, 갱신 중단"}
          </Badge>
          <Badge>
            {state?.mode === "HARDWARE" ? "실물 모드" : "사진 검증 모드"}
          </Badge>
          <button
            className="btn btn-outline btn-sm"
            onClick={() =>
              action(async () => {
                await api("/auth/logout", {});
                loadAuth();
              })
            }
          >
            <LogOut size={18} />
            로그아웃
          </button>
        </div>
      </header>
      <nav
        className="mx-auto flex max-w-[1600px] flex-wrap gap-2 px-5 pt-5"
        aria-label="메인 메뉴"
      >
        {tabs
          .filter((t) => t.id !== "settings" || role !== "operator")
          .map((t) => (
            <button
              className={
                "btn " + (tab === t.id ? "btn-primary" : "btn-outline")
              }
              onClick={() => setTab(t.id)}
              key={t.id}
            >
              <t.icon size={20} />
              {t.label}
            </button>
          ))}
      </nav>
      {!online && (
        <div className="mx-5 mt-4 flex items-center gap-3 rounded-xl bg-danger-bg p-4 font-bold text-danger">
          <AlertTriangle />
          현재 장비 상태를 확인할 수 없습니다. 최종 갱신:{" "}
          {state?.observed_at
            ? new Date(state.observed_at).toLocaleTimeString("ko-KR")
            : "미확인"}
          . 현장 상태를 확인하세요.
        </div>
      )}
      <main className="mx-auto max-w-[1600px] p-5 pb-28">
        {!state ? (
          <p>상태를 불러오는 중…</p>
        ) : tab === "work" ? (
          <Work
            role={role}
            state={state}
            brands={brands}
            action={action}
            refresh={refresh}
            online={online}
          />
        ) : tab === "settings" ? (
          <Config
            role={role}
            brands={brands}
            action={action}
            refresh={refresh}
            locked={locked}
          />
        ) : tab === "equipment" ? (
          <Equipment action={action} role={role} />
        ) : (
          <History action={action} />
        )}
      </main>
      {banner}
    </div>
  );
}
