import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Clock, Timer, SlidersHorizontal } from "lucide-react";
import { useApp } from "../lib/store";
import { configView, ended, reportError, sendCommand } from "../lib/station";
import VideoPanel from "../components/VideoPanel";
import JudgeLog from "../components/JudgeLog";
import StatusBanner from "../components/StatusBanner";
import ControlBar from "../components/ControlBar";
import Modal from "../components/Modal";
import Help from "../components/Help";
export default function ConditionRun() {
  const nav = useNavigate(),
    s = useApp((st) => st.snapshot?.session),
    state = useApp((st) => st.snapshot),
    setW = useApp((st) => st.setWizard);
  const [edit, setEdit] = useState(false),
    [busy, setBusy] = useState(false),
    [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  if (!s || s.recipe.kind === "simple")
    return (
      <div className="flex h-full flex-col items-center justify-center gap-5">
        <h1 className="text-2xl font-extrabold">조건 계수 대기</h1>
        <button
          className="btn btn-primary btn-lg"
          onClick={() => nav("/condition/setup")}
        >
          조건 설정
        </button>
        <button className="btn btn-outline" onClick={() => nav("/")}>
          처음 화면
        </button>
      </div>
    );
  const target = s.recipe.target_count,
    pct = target ? Math.min(100, (s.count / target) * 100) : 0;
  const seconds = Math.max(
    0,
    Math.floor((Date.now() - new Date(s.created_at).getTime()) / 1000),
  );
  const elapsed = [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  ]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
  const change = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (!ended(s))
        await sendCommand("finish", "검사 조건 변경으로 작업 종료");
      const cfg = configView(s);
      setW({
        step: 3,
        brandId: s.recipe.brand_id,
        checks: cfg.checks!,
        countMode: cfg.countMode,
        target: cfg.target || 40,
        targets: { ...s.recipe.targets },
      });
      nav("/condition/setup");
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
        <button className="btn btn-outline btn-sm" onClick={() => nav("/")}>
          <ArrowLeft size={20} />
          처음 화면
        </button>
        <h1 className="text-2xl font-extrabold">조건 계수 {s.brand.name}</h1>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[1.25fr_1fr] gap-5 overflow-y-auto p-6">
        <div className="flex min-h-0 flex-col gap-5">
          <VideoPanel />
          <JudgeLog />
        </div>
        <div className="flex min-h-0 flex-col gap-5">
          <div className="card p-6 text-center">
            <div className="text-lg font-bold">검사 완료 수량</div>
            <div className="flex items-end justify-center gap-3">
              <span className="text-[88px] font-black leading-none tabular-nums text-brand-800">
                {s.count}
              </span>
              <span className="pb-2 text-3xl font-extrabold">
                {target ? "/ " + target + "벌" : "벌"}
              </span>
            </div>
            {target != null && (
              <div className="mt-4">
                <div className="h-4 overflow-hidden rounded-full bg-panel">
                  <div
                    className="h-full rounded-full bg-brand-600 transition-all"
                    style={{ width: pct + "%" }}
                  />
                </div>
                <div className="mt-2 text-lg font-extrabold">
                  남은 수량 {Math.max(0, target - s.count)}벌
                </div>
              </div>
            )}
            <div className="mt-4 border-t border-line">
              <div className="flex items-center justify-between py-3">
                <span className="flex items-center gap-2 text-lg font-bold">
                  <Timer size={20} />
                  작업 시간
                </span>
                <span className="text-lg font-extrabold">{elapsed}</span>
              </div>
              <div className="flex items-center justify-between border-t border-line py-3">
                <span className="flex items-center gap-2 text-lg font-bold">
                  <Clock size={20} />
                  최근 검사
                </span>
                <span className="text-lg font-extrabold">
                  {state?.last_result
                    ? new Date(state.last_result.created_at).toLocaleTimeString(
                        "ko-KR",
                      )
                    : "없음"}
                </span>
              </div>
            </div>
          </div>
          <div className="card p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-extrabold">검사 조건</h3>
              <button
                className="btn btn-outline btn-sm"
                disabled={
                  state?.busy ||
                  [
                    "FEEDING",
                    "EJECTING",
                    "STOPPING",
                    "INSPECTING",
                    "RETRY_PENDING",
                  ].includes(s.phase)
                }
                onClick={() => setEdit(true)}
              >
                <SlidersHorizontal size={18} />
                조건 변경
              </button>
            </div>
            {[
              ["브랜드", s.brand.name],
              ...s.brand.options.map((o) => [o.label, s.recipe.targets[o.key]]),
              [
                "인식 방식",
                s.recipe.channels
                  .map(
                    (c) =>
                      ({ ocr: "OCR", rfid: "RFID", barcode: "바코드" })[c] || c,
                  )
                  .join(", "),
              ],
            ].map(([label, value]) => (
              <div
                key={label}
                className="flex items-center justify-between border-b border-line py-3 last:border-0"
              >
                <span className="text-lg font-bold">{label}</span>
                <span className="text-xl font-extrabold">
                  {value || "없음"}
                </span>
              </div>
            ))}
          </div>
          <StatusBanner />
        </div>
      </div>
      <ControlBar mode="condition" />
      {edit && (
        <Modal
          title="검사 조건 변경"
          onClose={() => {
            if (!busy) setEdit(false);
          }}
        >
          <div className="flex items-center">
            <p className="text-xl font-bold">
              현재 작업을 저장하고 조건을 변경합니다.
            </p>
            <Help text="진행 중인 작업의 판정 기준은 바꾸지 않습니다. 현재 작업 기록을 남긴 뒤 새 작업의 조건을 선택합니다." />
          </div>
          <div className="mt-6 flex gap-3">
            <button
              className="btn btn-outline"
              onClick={() => setEdit(false)}
              disabled={busy}
            >
              취소
            </button>
            <button
              className="btn btn-primary"
              onClick={change}
              disabled={busy}
            >
              조건 변경
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
