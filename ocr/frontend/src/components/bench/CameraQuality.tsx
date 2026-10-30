import { useEffect, useRef, useState } from "react";
import { Minus, Plus } from "lucide-react";
import { api } from "../../station/shared";
import { controlActive, labels, menuLabel, type Control, type Mode } from "../DeviceSettings";
import type { BenchHook } from "../DeviceTests";

const AUTO = ["focus_auto", "focus_automatic_continuous", "white_balance_temperature_auto", "white_balance_automatic"];
const PRIMARY = /(exposure|focus|gain|white_balance)/;
type Caps = { modes: Mode[]; controls: Control[]; current: any; saved_profile?: any };
type Draft = { mode: number; values: Record<string, number> };

export const modeLabel = (m: { width: number; height: number; fps: number }) => `${m.width} × ${m.height}, 초당 ${m.fps}장`;
const sameMode = (a: Mode, b: any) =>
  !!b && a.width === b.width && a.height === b.height && a.pixel_format === b.pixel_format && Math.abs(a.fps - b.fps) < 0.05;

// Every change goes to the camera and is saved right away. There is no separate
// apply or save step, and the screen always shows the saved values.
export default function CameraQuality({ bench, locked }: { bench: BenchHook; locked: boolean }) {
  const camera = bench.state?.camera;
  const [devices, setDevices] = useState<{ device: string; name: string }[]>([]);
  const [device, setDevice] = useState("");
  const [caps, setCaps] = useState<Caps | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [status, setStatus] = useState<"" | "saving" | "saved">("");
  const [error, setError] = useState("");
  const first = useRef<Draft | null>(null);
  const queued = useRef<Draft | null>(null);
  const inflight = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const capsRef = useRef<Caps | null>(null);
  capsRef.current = caps;

  useEffect(() => {
    api("/bench/camera/devices")
      .then((r) => {
        setDevices(r.devices || []);
        const known = camera?.saved_profile?.device || camera?.profile?.device;
        setDevice(known || r.devices?.[0]?.device || "");
        if (!r.devices?.length) setError(r.error || "카메라 없음");
      })
      .catch((e) => setError(e.message));
    return () => clearTimeout(timer.current);
  }, []);

  useEffect(() => {
    if (!device) return;
    let alive = true;
    setCaps(null);
    api<Caps>("/bench/camera/inspect", { device })
      .then((data) => {
        if (!alive) return;
        const saved = data.saved_profile?.device === device ? data.saved_profile : null;
        const source = saved || data.current;
        const mode = Math.max(0, data.modes.findIndex((m) => sameMode(m, source)));
        const values = { ...Object.fromEntries(data.controls.map((c) => [c.name, c.value])), ...(saved?.controls || {}) };
        for (const name of AUTO) if (name in values) values[name] = 0;
        setCaps(data);
        setDraft({ mode, values });
        first.current = { mode, values };
        setError("");
        // A camera that was never set up is turned on with the chosen device right away.
        if (!saved && !locked) schedule({ mode, values }, 0);
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [device]);

  const saveNow = async ({ mode, values }: Draft) => {
    const c = capsRef.current;
    if (!c?.modes[mode]) return;
    const controls = Object.fromEntries(
      c.controls
        .filter((x) => !/read-only|disabled/.test(x.flags) && values[x.name] !== undefined && controlActive(x, c.controls, values))
        .map((x) => [x.name, values[x.name]]),
    );
    setStatus("saving");
    try {
      await api("/bench/camera/apply", { profile: { device, ...c.modes[mode], controls }, save: true });
      setStatus("saved");
      setError("");
      await bench.refresh().catch(() => {});
    } catch (e) {
      const message = (e as Error).message;
      // Another device test held the camera for a moment; try the same change again.
      if (message.includes("진행 중인 점검")) {
        queued.current = queued.current || { mode, values };
        timer.current = setTimeout(flush, 800);
        return;
      }
      setStatus("");
      setError(message);
    }
  };
  const flush = async () => {
    if (inflight.current || !queued.current) return;
    const next = queued.current;
    queued.current = null;
    inflight.current = true;
    try {
      await saveNow(next);
    } finally {
      inflight.current = false;
      if (queued.current) void flush();
    }
  };
  const schedule = (next: Draft, delay = 400) => {
    queued.current = next;
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, delay);
  };
  // Leaving within the wait still sends the last change.
  const flushRef = useRef(flush);
  flushRef.current = flush;
  useEffect(() => () => {
    clearTimeout(timer.current);
    void flushRef.current();
  }, []);
  const change = (next: Draft, delay?: number) => {
    setDraft(next);
    setStatus("");
    schedule(next, delay);
  };

  if (error && !caps)
    return (
      <div className="space-y-4">
        <p role="alert" className="text-[24px] font-extrabold text-danger">{error}</p>
        {devices.length > 1 && <DevicePicker devices={devices} device={device} onChange={setDevice} disabled={locked} />}
      </div>
    );
  if (!caps || !draft) return <p role="status" className="text-[24px] font-extrabold">카메라 읽는 중</p>;
  const { mode, values } = draft;
  const editable = caps.controls.filter((c) => labels[c.name] && !AUTO.includes(c.name) && !/read-only|disabled/.test(c.flags));
  const control = (c: Control) => {
    const value = values[c.name] ?? c.value;
    const inactive = !controlActive(c, caps.controls, values);
    const disabled = locked || inactive;
    const set = (v: number) => change({ mode, values: { ...values, [c.name]: v } });
    return (
      <div key={c.name} className="space-y-2">
        <div className="flex items-baseline justify-between">
          <label htmlFor={"quality-" + c.name} className="text-[22px] font-extrabold">{labels[c.name]}</label>
          {!Object.keys(c.menu).length && c.type !== "bool" && <span className="text-[22px] font-extrabold tabular-nums">{value}</span>}
        </div>
        {Object.keys(c.menu).length ? (
          <div role="group" aria-label={labels[c.name]} className="flex flex-wrap gap-2">
            {Object.entries(c.menu).map(([n, text]) => (
              <button key={n} className={"btn " + (String(value) === n ? "btn-primary" : "btn-outline")} aria-pressed={String(value) === n}
                disabled={disabled} onClick={() => set(Number(n))}>{menuLabel(text)}</button>
            ))}
          </div>
        ) : c.type === "bool" ? (
          <button id={"quality-" + c.name} role="switch" aria-checked={value !== 0} className={"btn w-full " + (value ? "btn-primary" : "btn-outline")}
            disabled={disabled} onClick={() => set(value ? 0 : 1)}>{value ? "켜짐" : "꺼짐"}</button>
        ) : (
          <div className="flex items-center gap-3">
            <button aria-label={labels[c.name] + " 줄이기"} className="btn btn-outline !min-h-[56px] !px-4" disabled={disabled || value <= (c.min ?? 0)}
              onClick={() => set(Math.max(c.min ?? 0, value - (c.step || 1)))}><Minus size={28} /></button>
            <input id={"quality-" + c.name} type="range" className="quality-range min-w-0 flex-1" min={c.min} max={c.max} step={c.step || 1}
              value={value} disabled={disabled} onChange={(e) => set(Number(e.target.value))} />
            <button aria-label={labels[c.name] + " 늘리기"} className="btn btn-outline !min-h-[56px] !px-4" disabled={disabled || value >= (c.max ?? value)}
              onClick={() => set(Math.min(c.max ?? value, value + (c.step || 1)))}><Plus size={28} /></button>
          </div>
        )}
      </div>
    );
  };
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <p role="status" className={"text-[22px] font-extrabold " + (error ? "text-danger" : "text-ink-700")}>
          {error || (status === "saving" ? "저장 중" : status === "saved" ? "저장됨" : locked ? "작업 진행 중"
            : bench.state?.sensor_ocr?.busy ? "공정 시험 중" : "")}
        </p>
        {first.current && JSON.stringify(first.current) !== JSON.stringify(draft) && (
          <button className="btn btn-outline ml-auto" disabled={locked} onClick={() => first.current && change(first.current, 0)}>처음 값으로</button>
        )}
      </div>
      {devices.length > 1 && <DevicePicker devices={devices} device={device} onChange={setDevice} disabled={locked} />}
      <label className="block space-y-2 text-[22px] font-extrabold">
        해상도
        <select className="field" value={mode} disabled={locked || !!bench.state?.sensor_ocr?.busy}
          onChange={(e) => change({ mode: Number(e.target.value), values }, 0)}>
          {caps.modes.map((m, i) => (
            <option key={i} value={i}>
              {modeLabel(m)}
              {/* The same size and speed can come in two picture formats. */}
              {caps.modes.some((o, j) => j !== i && modeLabel(o) === modeLabel(m)) ? `, ${m.pixel_format}` : ""}
            </option>
          ))}
        </select>
      </label>
      <div className="space-y-5">{editable.filter((c) => PRIMARY.test(c.name)).map(control)}</div>
      {editable.some((c) => !PRIMARY.test(c.name)) && (
        <details>
          <summary className="cursor-pointer text-[22px] font-extrabold">추가 조정</summary>
          <div className="mt-4 space-y-5">{editable.filter((c) => !PRIMARY.test(c.name)).map(control)}</div>
        </details>
      )}
      <div className="border-t-2 border-line pt-4">
        <button className="btn btn-outline" disabled={locked || bench.busy}
          onClick={() => bench.action(() => api("/bench/camera/" + (camera?.wanted ? "disconnect" : "connect"), {}))}>
          {camera?.wanted ? "카메라 끄기" : "카메라 켜기"}
        </button>
      </div>
    </div>
  );
}

function DevicePicker({ devices, device, onChange, disabled }: {
  devices: { device: string; name: string }[]; device: string; onChange: (d: string) => void; disabled: boolean;
}) {
  return (
    <label className="block space-y-2 text-[22px] font-extrabold">
      카메라
      <select className="field" value={device} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {devices.map((d) => <option key={d.device} value={d.device}>{d.name}</option>)}
      </select>
    </label>
  );
}
