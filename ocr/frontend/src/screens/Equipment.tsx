import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Play,
  Square,
  Loader2,
  CreditCard,
  ScanText,
  Signal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useApp } from "../lib/store";
import { api } from "../lib/api";
import { Equipment as EquipmentDetails } from "../station/StationApp";
import Help from "../components/Help";
import { ended, sendCommand, reportError } from "../lib/station";

type TestKind = "sensor" | "rfid" | "ocr";

interface TestResult {
  ok: boolean;
  detail: string;
}

function TestCard({
  icon: Icon,
  title,
  desc,
  kind,
  busy,
  result,
  onRun,
  runLabel,
  disabled,
}: {
  icon: LucideIcon;
  title: string;
  desc: string;
  kind: TestKind;
  busy: TestKind | null;
  result: TestResult | null;
  onRun: (k: TestKind) => void;
  runLabel: string;
  disabled: boolean;
}) {
  const isBusy = busy === kind;
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
          <Icon size={24} />
        </span>
        <div>
          <h3 className="text-lg font-extrabold">{title}</h3>
        </div>
        <Help text={desc} />
      </div>
      <div className="mt-4 min-h-[56px]">
        {isBusy ? (
          <div className="flex items-center gap-2.5 rounded-xl bg-warn-bg px-4 py-3 text-base font-bold text-warn">
            <Loader2 size={22} className="animate-spin" /> 인식 확인 중…
          </div>
        ) : result ? (
          <div
            className={
              "rounded-xl px-4 py-3 text-base font-bold " +
              (result.ok ? "bg-ok-bg text-ok" : "bg-danger-bg text-danger")
            }
          >
            {result.detail}
          </div>
        ) : (
          <div className="rounded-xl bg-panel px-4 py-3 text-lg font-semibold text-ink-900">
            {disabled ? "작업 종료 후 점검" : "점검 전"}
          </div>
        )}
      </div>
      <button
        className="btn btn-outline mt-3 w-full"
        onClick={() => onRun(kind)}
        disabled={busy !== null || disabled}
      >
        {runLabel}
      </button>
    </div>
  );
}

export default function Equipment() {
  const nav = useNavigate();
  const server = useApp((s) => s.server);
  const state = useApp((s) => s.snapshot);
  const online = useApp((s) => s.connected);
  const [busy, setBusy] = useState<TestKind | null>(null);
  const [results, setResults] = useState<Record<TestKind, TestResult | null>>({
    sensor: null,
    rfid: null,
    ocr: null,
  });

  const conveyorRunning = server?.pipeline?.conveyor === "active";
  const sessionActive = !!state?.busy;

  const runTest = async (kind: TestKind) => {
    if (busy || !online || !ended(state?.session)) return;
    setBusy(kind);
    try {
      const res = await api<TestResult>("/api/device/test/" + kind, {});
      setResults((r) => ({ ...r, [kind]: res }));
    } catch {
      setResults((r) => ({
        ...r,
        [kind]: { ok: false, detail: "테스트 요청에 실패했습니다" },
      }));
    } finally {
      setBusy(null);
    }
  };

  const toggleConveyor = () =>
    sendCommand(conveyorRunning ? "stop" : "start").catch(reportError);

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav("/")}>
          <ArrowLeft size={20} /> 처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">장비 점검</h1>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
        <div className="grid grid-cols-4 gap-5">
          <div className="card flex flex-col p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                {conveyorRunning ? <Square size={24} /> : <Play size={24} />}
              </span>
              <div className="flex flex-1 items-center">
                <h3 className="text-lg font-extrabold">컨베이어 제어</h3>
                <Help text="선택한 작업의 운전 조건으로 이송합니다. 작업 설정과 현장 운전 허가가 준비되어야 가동할 수 있습니다." />
              </div>
            </div>
            <div className="mt-4 min-h-[56px]">
              <div
                className={
                  "rounded-xl px-4 py-3 text-base font-bold " +
                  (conveyorRunning
                    ? "bg-warn-bg text-warn"
                    : "bg-panel text-ink-700")
                }
              >
                {!online ||
                state?.io.connected !== true ||
                state?.mode !== "HARDWARE"
                  ? "장비 미연결"
                  : state?.io.km2_on === true
                    ? "접촉기 켜짐"
                    : state?.io.km2_on === false
                      ? "접촉기 꺼짐"
                      : "상태 미확인"}
              </div>
            </div>
            <button
              className={
                "btn mt-3 w-full " +
                (conveyorRunning ? "btn-danger" : "btn-primary")
              }
              onClick={toggleConveyor}
              disabled={
                !online ||
                (!conveyorRunning &&
                  (sessionActive ||
                    state?.mode !== "HARDWARE" ||
                    !state?.can_start))
              }
            >
              {conveyorRunning ? "벨트 정지" : "벨트 가동"}
            </button>
            {sessionActive && (
              <p className="mt-2 text-lg font-bold text-warn">
                계수 진행 중에는 별도 제어할 수 없습니다
              </p>
            )}
          </div>

          <TestCard
            icon={Signal}
            title="광센서 감지"
            desc="감지 신호 응답을 확인합니다"
            kind="sensor"
            busy={busy}
            result={results.sensor}
            onRun={runTest}
            runLabel="신호 확인"
            disabled={!online || !ended(state?.session)}
          />
          <TestCard
            icon={CreditCard}
            title="RFID 확인"
            desc="테스트 카드 태그를 인식합니다"
            kind="rfid"
            busy={busy}
            result={results.rfid}
            onRun={runTest}
            runLabel="태그 읽기"
            disabled={!online || !ended(state?.session)}
          />
          <TestCard
            icon={ScanText}
            title="OCR 인식 확인"
            desc="문자 인식 모델이 이 컴퓨터에서 열리는지 확인합니다."
            kind="ocr"
            busy={busy}
            result={results.ocr}
            onRun={runTest}
            runLabel="모델 확인"
            disabled={!online || !ended(state?.session)}
          />
        </div>
        <details className="card p-5">
          <summary className="cursor-pointer text-xl font-bold">
            상세 장비 정보
          </summary>
          <div className="mt-5">
            <EquipmentDetails
              action={async (fn) => {
                try {
                  await fn();
                } catch (e) {
                  reportError(e);
                }
              }}
              role="operator"
            />
          </div>
        </details>
      </div>
    </div>
  );
}
