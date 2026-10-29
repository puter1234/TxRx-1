import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Camera, Images, ScanText, Square } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended } from "../lib/station";
import { useCameraPreview } from "../components/useCameraPreview";
import { useBench, type BenchHook } from "../components/DeviceTests";
import BatchCapture from "../components/BatchCapture";
import ProcessTest, { type ProcessSettings } from "../components/bench/ProcessTest";
import WappenTest, { type Trial } from "../components/bench/WappenTest";
import RfidTest from "../components/bench/RfidTest";
import CameraQuality, { modeLabel } from "../components/bench/CameraQuality";
import ResultView, { type Shown } from "../components/bench/ResultView";
import { Sheet } from "../ui/kit";

const MODES = [
  { id: "process", label: "공정 시험" },
  { id: "wappen", label: "와펜 계수" },
  { id: "rfid", label: "RFID" },
  { id: "quality", label: "화질" },
] as const;

// All device tests on one screen: the camera is always live, inputs open by
// themselves while the screen is shown, and each test starts with one button.
export default function TestBench() {
  const bench = useBench();
  const [params, setParams] = useSearchParams();
  const mode = MODES.some((m) => m.id === params.get("mode")) ? params.get("mode")! : "process";
  const session = useApp((s) => s.snapshot?.session);
  const online = useApp((s) => s.connected);
  const locked = !online || !ended(session);
  const [shown, setShown] = useState<Shown | null>(null);
  const [trial, setTrial] = useState<Trial | null>(null);
  const [batch, setBatch] = useState(false);
  const [inputError, setInputError] = useState("");
  const settings = useRef<ProcessSettings | null>(null);
  const lastConnect = useRef(0);

  useEffect(
    () => () => {
      // Leaving releases the test inputs; an open input request blocks the next job.
      void fetch("/api/bench/close", { method: "POST", credentials: "same-origin", keepalive: true,
        headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
    },
    [],
  );
  useEffect(() => {
    const s = bench.state;
    if (!s || s.connected || locked || bench.busy || Date.now() - lastConnect.current < 3000) return;
    lastConnect.current = Date.now();
    api("/bench/io/connect", {})
      .then(() => setInputError(""))
      .catch((e) => setInputError((e as Error).message))
      .finally(() => void bench.refresh().catch(() => {}));
  }, [bench.state?.connected, bench.state?.generation, locked, bench.busy]);

  const camera = bench.state?.camera;
  const cameraReady = camera?.connected === true;
  const processRunning = !!bench.state?.sensor_ocr?.busy;
  const photo = () =>
    bench.action(async () => {
      const r = await api("/bench/camera/capture", {});
      setShown({ title: "사진", url: r.url, download: r.url, size: { width: r.width, height: r.height } });
    });
  const read = () =>
    bench.action(async () => {
      // The same locator as the process test, also when its tab was never opened.
      const saved = settings.current || (await api<{ settings?: ProcessSettings }>("/bench/pipeline").catch(() => null))?.settings;
      const r = await api("/bench/ocr/read", { locator: saved?.locator || "yolo26" });
      const lines = (r.reads || []).flatMap((x: any) => x.lines);
      setShown({ title: "문자 읽기", url: r.preview_url || "", download: r.original_url, diagnostics: r.barcode_diagnostics,
        lines: lines.map((l: any) => ({ text: l.text, image: l.preview, confidence: l.confidence })), note: r.error || undefined,
        report: { ...r, reads: (r.reads || []).map((x: any) => ({ ...x, lines: x.lines.map(({ preview, ...l }: any) => l) })) } });
    });
  const cameraBlock = !cameraReady ? (camera?.reconnecting ? "카메라 연결 중" : "카메라 꺼짐") : processRunning ? "공정 시험 중" : "";
  return (
    <div className="space-y-4">
      <StatusStrip bench={bench} locked={locked} inputError={inputError} onQuality={() => setParams({ section: "test", mode: "quality" }, { replace: true })} />
      {(bench.error || bench.state?.error) && (
        <div role="alert" className="flex flex-wrap items-center gap-4 rounded-2xl border-2 border-danger bg-danger-bg px-5 py-3">
          <p className="flex-1 text-[22px] font-extrabold text-danger">{bench.error || bench.state?.error}</p>
          {bench.state?.error && (
            <button className="btn btn-primary" disabled={bench.busy || locked} onClick={() => bench.action(() => api("/bench/error/clear", {}))}>오류 해제</button>
          )}
        </div>
      )}
      <div className="grid gap-5" style={{ gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr)" }}>
        <div className="min-w-0 space-y-4">
          <LiveView connected={cameraReady} reconnecting={!!camera?.reconnecting} trial={trial} />
          <div className="grid grid-cols-[1fr_1fr_auto] gap-3">
            <button className="btn btn-primary btn-lg" disabled={!!cameraBlock || bench.busy || locked} onClick={photo}>
              <Camera size={34} />
              {cameraBlock || "사진 찍기"}
            </button>
            <button className="btn btn-primary btn-lg" disabled={!!cameraBlock || bench.busy || locked} onClick={read}>
              <ScanText size={34} />
              {cameraBlock || "문자 읽기"}
            </button>
            <button className="btn btn-outline btn-lg" disabled={!!cameraBlock || locked} onClick={() => setBatch(true)}>
              <Images size={34} />
              여러 장
            </button>
          </div>
        </div>
        <div className="min-w-0 space-y-5">
          <div role="tablist" aria-label="시험" className="grid grid-cols-4 gap-2">
            {MODES.map((m) => (
              <button key={m.id} role="tab" aria-selected={mode === m.id}
                className={"btn btn-lg !px-2 " + (mode === m.id ? "btn-primary" : "btn-outline")}
                onClick={() => setParams({ section: "test", mode: m.id }, { replace: true })}>{m.label}</button>
            ))}
          </div>
          <div className="card p-5">
            {mode === "process" && <ProcessTest bench={bench} locked={locked} onShow={setShown} onSettings={(s) => (settings.current = s)} />}
            {mode === "wappen" && <WappenTest bench={bench} locked={locked} presetId={params.get("preset")} onTrial={setTrial} />}
            {mode === "rfid" && <RfidTest bench={bench} locked={locked} />}
            {mode === "quality" && <CameraQuality bench={bench} locked={locked} />}
          </div>
        </div>
      </div>
      {batch && (
        <Sheet title="여러 장 찍기" onClose={() => setBatch(false)}>
          <BatchCapture bench={bench} locked={locked} />
        </Sheet>
      )}
      {shown && (
        <Sheet title={shown.title} wide onClose={() => setShown(null)}>
          <ResultView shown={shown} />
        </Sheet>
      )}
    </div>
  );
}

function StatusStrip({ bench, locked, inputError, onQuality }: {
  bench: BenchHook; locked: boolean; inputError: string; onQuality: () => void;
}) {
  const s = bench.state;
  const camera = s?.camera;
  const sensor = (channel: number) => {
    const item = s?.sensors.find((x) => x.channel === channel);
    if (!s?.connected || item?.raw == null) return { text: "확인 중", tone: "idle" };
    const active = item.active ?? item.raw === (s.setup?.sensor_active_raw?.[channel - 1] ?? 0);
    return active ? { text: "감지", tone: "warn" } : { text: "없음", tone: "ok" };
  };
  const motorRun = s?.runs?.motor;
  const contactor = motorRun?.feedback_error ? { text: motorRun.feedback_error.replace(/^접촉기 /, ""), tone: "danger" }
    : s?.feedback?.active == null ? { text: "확인 중", tone: "idle" } : s.feedback.active ? { text: "켜짐", tone: "warn" } : { text: "꺼짐", tone: "ok" };
  const cameraChip = camera?.connected
    ? { text: camera.profile ? modeLabel(camera.profile) : "켜짐", tone: "ok" }
    : camera?.reconnecting
      ? { text: "연결 중", tone: "warn" }
      : { text: camera?.saved_profile ? "꺼짐" : "설정 필요", tone: "danger" };
  const outputs = (["motor", "led", "speed"] as const).filter((t) => t !== "speed" || s?.pins?.speed != null);
  return (
    <section aria-label="장비 상태" className="card space-y-3 px-5 py-4">
      <div className="flex min-h-16 flex-wrap items-center gap-x-6 gap-y-2">
        <Chip label="카메라" {...cameraChip} />
        {!camera?.connected && !camera?.reconnecting && (
          camera?.saved_profile
            ? <button className="btn btn-primary" aria-label="카메라 켜기" disabled={locked || bench.busy} onClick={() => bench.action(() => api("/bench/camera/connect", {}))}>켜기</button>
            : <button className="btn btn-primary" aria-label="카메라 화질" onClick={onQuality}>화질</button>
        )}
        <Chip label="센서 1" {...sensor(1)} />
        <Chip label="센서 2" {...sensor(2)} />
        <Chip label="접촉기" {...contactor} />
        {inputError && !s?.connected && <span className="text-[20px] font-extrabold text-danger">{inputError}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {outputs.map((target) => {
          const on = s?.io?.[`${target}_requested` as const] === true;
          const wait = Math.ceil((s?.cooldown_ms?.[target] || 0) / 1000);
          const name = target === "motor" ? "모터" : target === "led" ? "LED" : "속도";
          return (
            <div key={target} role="group" aria-label={name} className="flex items-center gap-2">
              <span className="text-[22px] font-extrabold">{name}</span>
              <button className={"btn " + (!on ? "btn-primary" : "btn-outline")} aria-pressed={!on} disabled={locked || bench.busy}
                onClick={() => bench.action(() => api(`/bench/${target}/off`, {}))}>{target === "speed" ? "저속" : "끄기"}</button>
              <button className={"btn " + (on ? "btn-primary" : "btn-outline")} aria-pressed={on}
                disabled={locked || bench.busy || !!s?.runs?.[target] || wait > 0} onClick={() => bench.pulse(target)}>
                {target === "speed" ? "고속" : "켜기"}{wait > 0 ? ` ${wait}초` : ""}
              </button>
            </div>
          );
        })}
        <button className="btn btn-danger ml-auto" onClick={bench.stop}>
          <Square size={26} fill="currentColor" />
          비상정지
        </button>
      </div>
    </section>
  );
}

const TONES: Record<string, string> = {
  ok: "bg-ok", warn: "bg-warn", danger: "bg-danger", idle: "bg-ink-500",
};

function Chip({ label, text, tone }: { label: string; text: string; tone: string }) {
  return (
    <span className="flex items-center gap-2 text-[22px] font-extrabold">
      <span className={"h-4 w-4 rounded-full " + TONES[tone]} aria-hidden="true" />
      {label} {text}
    </span>
  );
}

function LiveView({ connected, reconnecting, trial }: { connected: boolean; reconnecting: boolean; trial: Trial | null }) {
  const { url, failed } = useCameraPreview(connected);
  const flow = trial?.preset?.flow;
  return (
    <section aria-label="실시간 영상" className="relative flex aspect-[4/3] max-h-[560px] w-full items-center justify-center overflow-hidden rounded-3xl bg-ink-900">
      {connected && url ? (
        <img src={url} alt="카메라 영상" className="h-full w-full object-contain" />
      ) : (
        <p className="text-[32px] font-black text-white">{connected ? "영상 받는 중" : reconnecting ? "카메라 연결 중" : "카메라 꺼짐"}</p>
      )}
      {connected && url && failed && (
        <p role="status" className="absolute left-4 top-4 rounded-xl bg-warn px-4 py-2 text-[22px] font-extrabold text-ink-900">영상 지연</p>
      )}
      {trial && flow && trial.width > 0 && connected && url && (
        <svg aria-label="검출 위치와 계수선" className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 ${trial.width} ${trial.height}`} preserveAspectRatio="xMidYMid meet">
          {flow.roi && (
            <rect x={flow.roi[0] * trial.width} y={flow.roi[1] * trial.height} width={flow.roi[2] * trial.width}
              height={flow.roi[3] * trial.height} fill="none" stroke="#22c55e" strokeWidth={6} strokeDasharray="24 16" />
          )}
          {trial.boxes.map(([x1, y1, x2, y2], i) => (
            <rect key={i} x={x1 * trial.width} y={y1 * trial.height} width={(x2 - x1) * trial.width}
              height={(y2 - y1) * trial.height} fill="none" stroke="#22c55e" strokeWidth={8} />
          ))}
          <line
            x1={flow.axis === "x" ? flow.line * trial.width : 0} x2={flow.axis === "x" ? flow.line * trial.width : trial.width}
            y1={flow.axis === "y" ? flow.line * trial.height : 0} y2={flow.axis === "y" ? flow.line * trial.height : trial.height}
            stroke="#facc15" strokeWidth={8} />
        </svg>
      )}
    </section>
  );
}
