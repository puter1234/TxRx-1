import { useEffect, useState } from "react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended } from "../lib/station";
import type { BenchHook } from "./DeviceTests";

export type Mode = { width: number; height: number; fps: number; pixel_format: string };
export type Control = { name: string; type: string; value: number; min?: number; max?: number; step?: number; flags: string; menu: Record<string, string> };
export const labels: Record<string, string> = {
  brightness: "밝기", contrast: "대비", saturation: "채도", gain: "게인", gain_auto: "자동 게인",
  hue: "색조", gamma: "감마", zoom_absolute: "줌",
  white_balance_temperature_auto: "자동 화이트밸런스", white_balance_automatic: "자동 화이트밸런스",
  white_balance_temperature: "화이트밸런스 온도", auto_exposure: "노출 방식", exposure_auto: "노출 방식",
  exposure_absolute: "노출값", exposure_time_absolute: "노출값",
  focus_absolute: "초점", focus_auto: "자동 초점", focus_automatic_continuous: "자동 초점",
  sharpness: "선명도", backlight_compensation: "역광 보정", power_line_frequency: "조명 주파수",
  exposure_auto_priority: "자동 노출 FPS 변경", exposure_dynamic_framerate: "자동 노출 FPS 변경",
};
export const menuLabel = (value: string) => {
  if (/manual/i.test(value)) return "수동";
  if (/aperture priority|auto mode/i.test(value)) return "자동";
  if (/shutter priority/i.test(value)) return "셔터 우선";
  if (/disabled/i.test(value)) return "끄기";
  return value;
};

export function controlActive(c: Control, controls: Control[], values: Record<string, number>) {
  const auto = (names: string[]) => controls.find(v => names.includes(v.name));
  if (c.name === "gain") {
    const mode = auto(["gain_auto"]);
    if (mode) return (values[mode.name] ?? mode.value) === 0;
  }
  if (["exposure_absolute", "exposure_time_absolute"].includes(c.name)) {
    const mode = auto(["exposure_auto", "auto_exposure"]);
    if (mode) return /manual|shutter priority/i.test(mode.menu[String(values[mode.name] ?? mode.value)] || "");
  }
  if (c.name === "focus_absolute") {
    const mode = auto(["focus_auto", "focus_automatic_continuous"]);
    if (mode) return (values[mode.name] ?? mode.value) === 0;
  }
  if (c.name === "white_balance_temperature") {
    const mode = auto(["white_balance_temperature_auto", "white_balance_automatic"]);
    if (mode) return (values[mode.name] ?? mode.value) === 0;
  }
  return !/inactive/.test(c.flags);
}

// I/O wiring. The documented board needs no choices and is only listed; other
// boards set polarity and the run permit here, each change saved by itself.
export function WiringPanel({ bench }: { bench: BenchHook }) {
  const snapshot = useApp((s) => s.snapshot);
  const locked = !ended(snapshot?.session);
  const [saving, setSaving] = useState<"" | "saving" | "saved">("");
  const [error, setError] = useState("");
  const s = bench.state;
  if (!s) return null;
  const setup = s.setup;
  const on = setup.do_on_raw ?? (s.wiring_fixed ? 1 : null);
  const line = (channel: number) => s.sensors.find((x) => x.channel === channel)?.line;
  const rows: [string, number | null | undefined, string][] = [
    ["모터", s.pins.motor, on == null ? "" : `켜짐 신호 ${on}`],
    ["LED", s.pins.led, on == null ? "" : `켜짐 신호 ${on}`],
    ...(s.pins.speed != null ? [["속도", s.pins.speed, on == null ? "" : `고속 신호 ${on}`] as [string, number, string]] : []),
    ["센서 1", line(1), `감지 신호 ${setup.sensor_active_raw?.[0] ?? 0}`],
    ["센서 2", line(2), `감지 신호 ${setup.sensor_active_raw?.[1] ?? 0}`],
    ["접촉기", s.pins.feedback, ""],
  ];
  const save = async (patch: Record<string, unknown>) => {
    setSaving("saving");
    setError("");
    try {
      await api("/bench/setup", { ...setup, ...patch }, "PUT");
      setSaving("saved");
    } catch (e) {
      setSaving("");
      setError((e as Error).message);
    } finally {
      await bench.refresh().catch(() => {});
    }
  };
  const disabled = locked || saving === "saving" || !!s.sensor_ocr?.busy;
  const pick = (label: string, value: number | null | undefined, onPick: (v: number) => Record<string, unknown>) => (
    <div role="group" aria-label={label} className="flex items-center gap-3">
      <span className="min-w-56 text-[22px] font-extrabold">{label}</span>
      {[0, 1].map((v) => (
        <button key={v} className={"btn " + (value === v ? "btn-primary" : "btn-outline")} aria-pressed={value === v}
          disabled={disabled} onClick={() => value !== v && void save(onPick(v))}>{v}</button>
      ))}
    </div>
  );
  const confirm = (key: "output_wiring_confirmed" | "stop_circuit_confirmed", label: string) => (
    <button className={"btn " + (setup[key] ? "btn-primary" : "btn-outline")} aria-pressed={!!setup[key]} disabled={disabled}
      onClick={() => void save({ [key]: !setup[key] })}>{label}</button>
  );
  const editor = (
    <div className="space-y-4 border-t-2 border-line pt-5">
      {pick("출력 켜짐 신호", setup.do_on_raw, (v) => ({ do_on_raw: v }))}
      {[0, 1].map((i) => pick(`센서 ${i + 1} 감지 신호`, setup.sensor_active_raw?.[i] ?? 0,
        (v) => ({ sensor_active_raw: setup.sensor_active_raw.map((x: number | null, j: number) => (j === i ? v : x)) })))}
      <div className="flex items-center gap-3">
        <label htmlFor="permit-line" className="min-w-56 text-[22px] font-extrabold">운전 허가 GPIO</label>
        <PermitLine value={setup.permit_line} disabled={disabled} onSave={(v) => void save({ permit_line: v })} />
      </div>
      {setup.permit_line != null && pick("운전 허가 신호", setup.permit_active_raw, (v) => ({ permit_active_raw: v }))}
      <div className="flex flex-wrap gap-3">
        {confirm("output_wiring_confirmed", "출력 배선 확인")}
        {confirm("stop_circuit_confirmed", "정지 회로 확인")}
      </div>
    </div>
  );
  return (
    <section className="card space-y-5 p-6">
      <div className="flex items-center gap-4">
        <h2 className="text-[32px] font-black">입출력</h2>
        <p role="status" className={"ml-auto text-[22px] font-extrabold " + (error ? "text-danger" : "text-ink-700")}>
          {error || (saving === "saving" ? "저장 중" : saving === "saved" ? "저장됨" : "")}
        </p>
      </div>
      <table className="w-full text-left text-[22px] font-extrabold">
        <tbody className="divide-y divide-line">
          {rows.map(([name, gpio, detail]) => (
            <tr key={name}>
              <th className="w-40 py-3">{name}</th>
              <td className="w-56 py-3">GPIO {gpio ?? "없음"}</td>
              <td className="py-3 text-ink-700">{detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* The documented board needs no changes; they stay one tap away, e.g. for a run-permit input. */}
      {s.wiring_fixed ? (
        <details>
          <summary className="cursor-pointer text-[22px] font-extrabold">배선 바꾸기</summary>
          {editor}
        </details>
      ) : editor}
    </section>
  );
}

function PermitLine({ value, disabled, onSave }: { value: number | null; disabled: boolean; onSave: (v: number | null) => void }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => setText(value == null ? "" : String(value)), [value]);
  const commit = () => {
    const next = text.trim() === "" ? null : Number(text);
    if (next === value) return;
    if (next === null || (Number.isInteger(next) && next >= 0 && next <= 1023)) onSave(next);
    else setText(value == null ? "" : String(value));
  };
  return (
    <input id="permit-line" className="field !w-40" type="number" min={0} max={1023} value={text} disabled={disabled}
      placeholder="없음" onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
  );
}
