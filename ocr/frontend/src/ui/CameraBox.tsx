import { useState } from "react";
import { Camera } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { refreshEquipment, reportError } from "../lib/station";
import { cameraChangeAllowed, cameraOn } from "../lib/jobs";
import { useCameraPreview } from "../components/useCameraPreview";

export function useCameraSwitch() {
  const equipment = useApp((s) => s.equipment);
  const snapshot = useApp((s) => s.snapshot);
  const online = useApp((s) => s.connected);
  const [busy, setBusy] = useState(false);
  const on = cameraOn(equipment);
  // A camera that was on comes back by itself for a few tries, then the button returns.
  const reconnecting = !on && equipment?.camera?.reconnecting === true;
  const error: string = (!on && equipment?.camera?.error) || "";
  const turnOn = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api("/bench/camera/connect", {});
      await refreshEquipment();
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  return { on, reconnecting, error, busy, turnOn, allowed: online && cameraChangeAllowed(snapshot) };
}

export function CameraOnButton({ className = "btn-lg" }: { className?: string }) {
  const camera = useCameraSwitch();
  if (camera.reconnecting) return null;
  return (
    <button className={"btn btn-primary " + className} disabled={camera.busy || !camera.allowed} onClick={camera.turnOn}>
      <Camera size={44} />
      {camera.busy ? "켜는 중" : "카메라 켜기"}
    </button>
  );
}

export default function CameraBox({
  tracking,
  flow,
  className = "h-[420px]",
}: {
  tracking?: { boxes: number[][]; width: number; height: number };
  flow?: Record<string, any> | null;
  className?: string;
}) {
  const camera = useCameraSwitch();
  const { url, failed } = useCameraPreview(camera.on);
  return (
    <section aria-label="카메라" className={"relative flex items-center justify-center overflow-hidden rounded-3xl bg-ink-900 " + className}>
      {camera.on && url ? (
        <img src={url} alt="카메라 영상" className="h-full w-full object-contain" />
      ) : camera.on ? (
        <p className="text-[32px] font-extrabold text-white">영상 받는 중</p>
      ) : (
        <div className="flex max-w-full flex-col items-center gap-6 px-6 text-center">
          <p className="text-[36px] font-black text-white">{camera.reconnecting ? "카메라 연결 중" : "카메라 꺼짐"}</p>
          {camera.error && <p role="alert" className="line-clamp-3 break-words text-[24px] font-extrabold text-warn">{camera.error}</p>}
          <CameraOnButton className="btn-xl" />
        </div>
      )}
      {tracking && flow && camera.on && url && !failed && (
        <svg
          aria-label="검출 위치와 계수선"
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 ${tracking.width} ${tracking.height}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {tracking.boxes.map(([x1, y1, x2, y2], i) => (
            <rect key={i} x={x1 * tracking.width} y={y1 * tracking.height} width={(x2 - x1) * tracking.width}
              height={(y2 - y1) * tracking.height} fill="none" stroke="#22c55e" strokeWidth={4} />
          ))}
          <line
            x1={flow.axis === "x" ? flow.line * tracking.width : 0}
            x2={flow.axis === "x" ? flow.line * tracking.width : tracking.width}
            y1={flow.axis === "y" ? flow.line * tracking.height : 0}
            y2={flow.axis === "y" ? flow.line * tracking.height : tracking.height}
            stroke="#facc15"
            strokeWidth={4}
          />
        </svg>
      )}
    </section>
  );
}
