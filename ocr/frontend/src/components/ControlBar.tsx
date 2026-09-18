import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Play, Pause, Plus, Minus, RotateCcw, Square } from "lucide-react";
import { useApp } from "../lib/store";
import { ended, sendCommand, startSession, reportError } from "../lib/station";
import Modal from "./Modal";
export default function ControlBar({ mode }: { mode: "simple" | "condition" }) {
  const nav = useNavigate(),
    state = useApp((s) => s.snapshot),
    online = useApp((s) => s.connected),
    pending = useApp((s) => s.pending);
  const session = state?.session,
    active = !ended(session),
    phase = session?.phase || "";
  const [dialog, setDialog] = useState<
      "adjust" | "zero" | "recover" | "finish" | null
    >(null),
    [delta, setDelta] = useState(1),
    [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false);
  const running = [
    "FEEDING",
    "EJECTING",
    "INSPECTING",
    "STOPPING",
    "RETRY_PENDING",
  ].includes(phase);
  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      reportError(e);
    }
  };
  const start = () =>
    run(async () => {
      if (!active && mode === "simple")
        await startSession({ mode: "simple", countMode: "continuous" });
      else await sendCommand("start");
    });
  const open = (kind: typeof dialog, change = 1) => {
    setDialog(kind);
    setDelta(change);
    setReason("");
  };
  const confirm = (action?: "reset" | "discard") =>
    run(async () => {
      if (busy) return;
      setBusy(true);
      try {
        if (dialog === "adjust" || dialog === "zero")
          await sendCommand(
            "adjust",
            reason,
            dialog === "zero" ? -(session?.count || 0) : delta,
          );
        else if (dialog === "recover")
          await sendCommand(action || "reset", reason);
        else if (dialog === "finish") {
          await sendCommand("finish", reason);
          nav("/");
        }
        setDialog(null);
      } finally {
        setBusy(false);
      }
    });
  return (
    <>
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-line bg-white px-6 py-4">
        <button
          className="btn btn-primary"
          onClick={start}
          disabled={
            !online ||
            !!state?.busy ||
            pending.includes("start") ||
            pending.includes("create") ||
            (active ? !state?.can_start : mode !== "simple")
          }
        >
          <Play size={22} />
          {!active && mode === "simple"
            ? "계수 시작"
            : phase === "PAUSED"
              ? "재개"
              : "검사 시작"}
        </button>
        <button
          className="btn btn-outline"
          onClick={() => run(() => sendCommand("stop"))}
          disabled={!online || !active || pending.includes("stop")}
        >
          <Pause size={22} />
          일시정지
        </button>
        <button
          className="btn btn-outline"
          onClick={() => open("adjust", -1)}
          disabled={
            !online ||
            !active ||
            running ||
            state?.busy ||
            pending.includes("adjust")
          }
        >
          <Minus size={22} />
          수동 1개 빼기
        </button>
        <button
          className="btn btn-outline"
          onClick={() => open("adjust", 1)}
          disabled={
            !online ||
            !active ||
            running ||
            state?.busy ||
            pending.includes("adjust")
          }
        >
          <Plus size={22} />
          수동 1개 더하기
        </button>
        {mode === "simple" && (
          <button
            className="btn btn-outline"
            onClick={() => open("zero")}
            disabled={!online || !active || running || state?.busy}
          >
            <RotateCcw size={22} />
            수량 초기화
          </button>
        )}
        {phase === "PASSED" && (
          <button
            className="btn btn-primary"
            onClick={() => run(() => sendCommand("release"))}
            disabled={!online || state?.busy || pending.includes("release")}
          >
            {state?.mode === "REPLAY" ? "다음 제품" : "제품 배출"}
          </button>
        )}
        {["HOLD", "FAULT", "PAUSED"].includes(phase) && (
          <button
            className="btn btn-warn"
            onClick={() => open("recover")}
            disabled={!online || state?.busy}
          >
            조치 확인
          </button>
        )}
        <button
          className="btn btn-outline"
          onClick={() => open("finish")}
          disabled={!online || !active || state?.busy}
        >
          <Square size={20} />
          {mode === "simple" ? "계수 종료" : "검사 종료"}
        </button>
        <button
          className="btn btn-danger ml-auto"
          onClick={() => run(() => sendCommand("stop"))}
          disabled={!online || !active || pending.includes("stop")}
        >
          <Square size={22} />
          정지
        </button>
      </div>
      {dialog && (
        <Modal
          title={
            dialog === "adjust"
              ? "수량 보정"
              : dialog === "zero"
                ? "수량 초기화"
                : dialog === "recover"
                  ? "조치 확인"
                  : "작업 종료"
          }
          onClose={() => {
            if (!busy) setDialog(null);
          }}
        >
          {(dialog === "adjust" || dialog === "zero") && (
            <p className="mb-5 text-2xl font-bold">
              현재 {session?.count || 0}개에서{" "}
              {dialog === "zero" ? 0 : (session?.count || 0) + delta}개로 변경
            </p>
          )}
          <label className="block text-lg font-bold">
            {dialog === "recover" ? "확인한 내용" : "변경 사유"}
            <input
              className="field mt-2"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
            />
          </label>
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              className="btn btn-outline"
              onClick={() => setDialog(null)}
              disabled={busy}
            >
              취소
            </button>
            <button
              className="btn btn-primary"
              disabled={
                !online ||
                busy ||
                state?.busy ||
                (reason.trim().length < 3 &&
                  (dialog !== "finish" ||
                    !!session?.active_product ||
                    ["FAULT", "HOLD"].includes(phase)))
              }
              onClick={() => confirm("reset")}
            >
              {dialog === "recover" ? "재검사 준비" : "확인"}
            </button>
            {dialog === "recover" && phase === "HOLD" && (
              <button
                className="btn btn-outline"
                disabled={
                  !online || busy || state?.busy || reason.trim().length < 3
                }
                onClick={() => confirm("discard")}
              >
                제품 제거 완료
              </button>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
