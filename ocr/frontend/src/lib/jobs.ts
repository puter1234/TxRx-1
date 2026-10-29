import { useNavigate } from "react-router-dom";
import type { Session, Snapshot } from "../station/shared";
import { configView } from "./station";
import { useApp } from "./store";

export type Kind = "simple" | "vision" | "condition";

export const KIND_LABEL: Record<Kind, string> = {
  simple: "옷",
  vision: "와펜",
  condition: "조건",
};

export const jobTitle = (s: Pick<Session, "recipe" | "brand">) =>
  s.recipe.kind === "simple"
    ? "옷 계수"
    : s.recipe.kind === "vision"
      ? "와펜 계수"
      : `${s.brand.name} 조건 계수`;

const DEFAULT_NAMES = ["", "단순 계수", "와펜 계수", "기본 설정"];
export const presetLabel = (name?: string) => (name && !DEFAULT_NAMES.includes(name) ? name : "");

export const RUNNING = ["FEEDING", "EJECTING", "INSPECTING", "STOPPING", "RETRY_PENDING", "CAMERA_WAIT"];

export type Tone = "idle" | "go" | "warn" | "danger" | "done";

export function phaseView(phase: string): { label: string; tone: Tone } {
  if (RUNNING.includes(phase)) return { label: phase === "CAMERA_WAIT" ? "카메라 다시 연결 중" : "계수 중", tone: phase === "CAMERA_WAIT" ? "warn" : "go" };
  switch (phase) {
    case "READY":
      return { label: "대기", tone: "idle" };
    case "PASSED":
      return { label: "합격", tone: "go" };
    case "PAUSED":
      return { label: "멈춤", tone: "warn" };
    case "HOLD":
      return { label: "확인 필요", tone: "danger" };
    case "FAULT":
      return { label: "장비 오류", tone: "danger" };
    case "DONE":
      return { label: "목표 완료", tone: "done" };
    default:
      return { label: "끝남", tone: "idle" };
  }
}

export const TONE_BAR: Record<Tone, string> = {
  idle: "bg-brand-700 text-white",
  go: "bg-ok text-white",
  warn: "bg-warn text-ink-900",
  danger: "bg-danger text-white",
  done: "bg-ok text-white",
};

export const needsCamera = (kind: Kind | undefined, channels: string[] = []) =>
  kind === "vision" || channels.some((c) => c === "ocr" || c === "barcode");

export const cameraOn = (equipment: any) => equipment?.camera?.connected === true;

// The server only permits camera changes before the first product of a READY job.
export const cameraChangeAllowed = (s: Snapshot | null | undefined) =>
  !s?.busy && (!s?.session || ["FINISHED", "DONE", "ABORTED"].includes(s.session.phase) ||
    (s.session.phase === "READY" && !s.session.active_product));

// Opens the start screen of a finished job with the same choices filled in.
export function useRedo() {
  const nav = useNavigate();
  const setW = useApp((s) => s.setWizard);
  return (s: Session, testRun = false) => {
    const cfg = configView(s);
    if (cfg.mode === "condition") {
      setW({
        step: 3,
        presetId: cfg.presetId || "",
        testRun,
        brandId: cfg.brandId ?? null,
        checks: cfg.checks ?? { rfid: false, ocr: false, barcode_tag: false, barcode_poly: false },
        countMode: cfg.countMode,
        target: cfg.target || 40,
        targets: { ...s.recipe.targets },
      });
      nav("/condition");
    } else
      nav(testRun ? "/simple?test=1" : "/simple", {
        state: { kind: cfg.mode, presetId: cfg.presetId, target: cfg.target ?? null, targets: s.recipe.targets || {} },
      });
  };
}
