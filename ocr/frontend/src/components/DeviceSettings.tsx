import { useEffect, useRef, useState } from "react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { cameraEditable, ended } from "../lib/station";
import { BenchHeader, useBench, type BenchHook } from "./DeviceTests";

type Mode = { width: number; height: number; fps: number; pixel_format: string };
type Control = { name: string; type: string; value: number; min?: number; max?: number; step?: number; flags: string; menu: Record<string, string> };
const labels: Record<string, string> = {
  brightness: "밝기", contrast: "대비", saturation: "채도", gain: "게인", gain_auto: "자동 게인",
  hue: "색조", gamma: "감마", zoom_absolute: "줌",
  white_balance_temperature_auto: "자동 화이트밸런스", white_balance_automatic: "자동 화이트밸런스",
  white_balance_temperature: "화이트밸런스 온도", auto_exposure: "노출 방식", exposure_auto: "노출 방식",
  exposure_absolute: "노출값", exposure_time_absolute: "노출값",
  focus_absolute: "초점", focus_auto: "자동 초점", focus_automatic_continuous: "자동 초점",
  sharpness: "선명도", backlight_compensation: "역광 보정", power_line_frequency: "조명 주파수",
  exposure_auto_priority: "자동 노출 FPS 변경", exposure_dynamic_framerate: "자동 노출 FPS 변경",
};
const menuLabel = (value: string) => {
  if (/manual/i.test(value)) return "수동";
  if (/aperture priority|auto mode/i.test(value)) return "자동";
  if (/shutter priority/i.test(value)) return "셔터 우선";
  if (/disabled/i.test(value)) return "끄기";
  return value;
};

function controlActive(c: Control, controls: Control[], values: Record<string, number>) {
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

export default function DeviceSettings() {
  const bench = useBench();
  return <><BenchHeader bench={bench}/><DeviceSettingsPanels bench={bench}/></>;
}

export function DeviceSettingsPanels({ bench, tab = "all" }: { bench: BenchHook; tab?: string }) {
  const snapshot = useApp(s => s.snapshot);
  const locked = !ended(snapshot?.session);
  const cameraLocked = !cameraEditable(snapshot);
  const [devices, setDevices] = useState<{device: string; name: string}[]>([]);
  const [device, setDevice] = useState(""), [discovery, setDiscovery] = useState("");
  const [caps, setCaps] = useState<{ modes: Mode[]; controls: Control[]; current: any } | null>(null);
  const [modeIndex, setModeIndex] = useState(0), [values, setValues] = useState<Record<string, number>>({});
  const [setup, setSetup] = useState<any>(null), [ports, setPorts] = useState<{device: string; name: string}[]>([]);
  const [message, setMessage] = useState("");
  const [cameraMessage, setCameraMessage] = useState("");
  const [baseline, setBaseline] = useState("");
  const [revision, setRevision] = useState(0);
  const attempted = useRef("");
  const discovered = useRef(false);
  const dirty = !!caps && baseline !== JSON.stringify({ modeIndex, values });
  const [portsBusy, setPortsBusy] = useState(false), [portsError, setPortsError] = useState("");
  const findPorts = async () => {
    setPortsBusy(true); setPortsError("");
    try { const serial = await api("/bench/ports"); setPorts(serial.ports || []); }
    catch (e) { setPortsError((e as Error).message); }
    finally { setPortsBusy(false); }
  };
  useEffect(() => { if (!setup && bench.state) setSetup({ rfid_power: 2600, ...bench.state.setup }); }, [bench.state, setup]);
  const find = async () => {
    const result = await api("/bench/camera/devices");
    setDevices(result.devices || []); setDiscovery(result.error || "");
    const prior = bench.state?.camera?.profile?.device || bench.state?.camera?.saved_profile?.device;
    setDevice(old => old || prior || result.devices?.[0]?.device || "");
  };
  useEffect(() => {
    if (!bench.state || discovered.current) return;
    discovered.current = true;
    void find().catch(e => setDiscovery(e.message));
  }, [bench.state]);
  useEffect(() => { void findPorts(); }, []);
  const inspect = async () => {
    const data = await api("/bench/camera/inspect", { device });
    setCaps(data);
    const current = data.current;
    const index = Math.max(0, data.modes.findIndex((m: Mode) => current && m.width === current.width && m.height === current.height && Math.abs(m.fps - current.fps) < 0.05 && m.pixel_format === current.pixel_format));
    const actual = Object.fromEntries(data.controls.map((c: Control) => [c.name, c.value]));
    const fixed = { ...actual };
    for (const name of ["focus_auto", "focus_automatic_continuous", "white_balance_temperature_auto", "white_balance_automatic"]) {
      if (name in fixed) fixed[name] = 0;
    }
    setModeIndex(index); setValues(fixed);
    setBaseline(JSON.stringify({ modeIndex: index, values: actual }));
    setRevision(data.revision ?? bench.state?.camera?.revision ?? 0);
    const saved = data.saved_profile ?? bench.state?.camera?.saved_profile;
    const matchesSaved = saved && saved.device === device && current &&
      ["width", "height", "pixel_format"].every(key => saved[key] === current[key]) &&
      Math.abs(saved.fps - current.fps) < 0.05 &&
      Object.entries(saved.controls).every(([key, value]) => actual[key] === value);
    setCameraMessage(matchesSaved ? "저장값과 같음" : saved ? "저장값과 다름" : "저장값 없음");
  };
  const apply = (save: boolean) => bench.action(async () => {
    if (!caps?.modes[modeIndex]) return;
    const controls = Object.fromEntries(caps.controls
      .filter(c => !/read-only|disabled/.test(c.flags) && values[c.name] !== undefined && controlActive(c, caps.controls, values))
      .map(c => [c.name, values[c.name]]));
    const result = await api("/bench/camera/apply", {
      profile: { device, ...caps.modes[modeIndex], controls }, save,
      expected_revision: revision,
    });
    setCaps(result.capabilities);
    const actual = Object.fromEntries(result.capabilities.controls.map((c: Control) => [c.name, c.value]));
    setValues(actual);
    setBaseline(JSON.stringify({ modeIndex, values: actual }));
    setRevision(result.revision);
    setCameraMessage(save ? "저장됨" : "적용됨, 저장 전");
  });
  const disabled = locked || bench.busy || !!bench.state?.native_busy || !!bench.state?.sensor_ocr?.busy;
  const cameraDisabled = cameraLocked || bench.busy || !!bench.state?.native_busy || !!bench.state?.rfid_busy || !!bench.state?.sensor_ocr?.busy || !!bench.state?.runs.motor;
  useEffect(() => {
    if (!device || cameraDisabled || attempted.current === device) return;
    attempted.current = device;
    void bench.action(inspect);
  }, [device, cameraDisabled]);
  const field = (key: string, value: any) => setSetup((old: any) => ({ ...old, [key]: value }));
  return <div className="space-y-5">
    <section role="tabpanel" id="panel-camera" aria-labelledby="tab-camera" hidden={tab !== "all" && tab !== "camera"} className="card space-y-5 p-5">
      <h2 className="text-[32px] font-black">카메라 설정</h2>
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-72 flex-1 text-lg font-bold">카메라
          <select className="field mt-2" value={device} disabled={cameraDisabled} onChange={e => { setDevice(e.target.value); setCaps(null); setCameraMessage(""); }}>
            <option value="">카메라 선택</option>{devices.map(d => <option value={d.device} key={d.device}>{d.name} ({d.device})</option>)}
          </select></label>
        <button className="btn btn-outline" disabled={cameraDisabled} onClick={() => bench.action(find)}>장치 찾기</button>
        <button className="btn btn-primary" disabled={cameraDisabled || !device} onClick={() => bench.action(inspect)}>{dirty ? "초안 버리고 다시 읽기" : "실제 설정 다시 읽기"}</button>
      </div>
      {discovery && <p className="text-lg font-bold">{discovery}</p>}
      <div>
        {caps && <div className="space-y-4">
          <label className="block text-lg font-bold">해상도와 촬영 속도
            <select className="field mt-2" value={modeIndex} disabled={cameraDisabled} onChange={e => { setModeIndex(Number(e.target.value)); setCameraMessage(""); }}>
              {caps.modes.map((m, i) => <option value={i} key={i}>{m.width} × {m.height} / {m.fps} fps / {m.pixel_format}</option>)}
            </select></label>
          {[true, false].map(primary => <details key={String(primary)} open={primary}>
          <summary className="mb-3 cursor-pointer text-xl font-bold">{primary ? "노출, 초점, 화이트밸런스" : "추가 설정"}</summary>
          <div className="grid gap-4 sm:grid-cols-2">{caps.controls.filter(c => labels[c.name] && !["focus_auto", "focus_automatic_continuous", "white_balance_temperature_auto", "white_balance_automatic"].includes(c.name) && (/(exposure|focus|gain|white_balance)/.test(c.name) === primary)).map(c => {
            const readonly = /read-only|disabled/.test(c.flags) || ["focus_auto", "focus_automatic_continuous", "white_balance_temperature_auto", "white_balance_automatic"].includes(c.name);
            // An inactive manual control can be changed with its automatic mode in the same apply.
            const inactive = !controlActive(c, caps.controls, values);
            const label = labels[c.name], value = values[c.name] ?? c.value;
            return <div key={c.name} className="border-b border-line pb-4">
              <div className="mb-3"><label htmlFor={"camera-" + c.name} className="text-xl font-extrabold">{label}</label></div>
              {Object.keys(c.menu).length ? <select id={"camera-" + c.name} className="field" disabled={cameraDisabled || readonly || inactive} value={value} onChange={e => setValues(v => ({ ...v, [c.name]: Number(e.target.value) }))}>
                {Object.entries(c.menu).map(([n, text]) => <option key={n} value={n}>{menuLabel(text)}</option>)}
              </select> : c.type === "bool" ? <button id={"camera-" + c.name} role="switch" aria-label={label} aria-checked={value !== 0} className={"btn w-full " + (value ? "btn-primary" : "btn-outline")} disabled={cameraDisabled || readonly || inactive} onClick={() => setValues(v => ({ ...v, [c.name]: value ? 0 : 1 }))}>{value ? "켜짐" : "꺼짐"}</button>
                : <div className="flex items-center gap-2">
                  <button aria-label={label + " 줄이기"} className="btn btn-outline px-4 text-2xl" disabled={cameraDisabled || readonly || inactive || value <= (c.min ?? 0)} onClick={() => setValues(v => ({ ...v, [c.name]: Math.max(c.min ?? 0, value - (c.step || 1)) }))}>−</button>
                  <input id={"camera-" + c.name} type="number" className="field min-w-0 text-center" min={c.min} max={c.max} step={c.step || 1} disabled={cameraDisabled || readonly || inactive} value={value} onChange={e => setValues(v => ({ ...v, [c.name]: Number(e.target.value) }))}/>
                  <button aria-label={label + " 늘리기"} className="btn btn-outline px-4 text-2xl" disabled={cameraDisabled || readonly || inactive || value >= (c.max ?? value)} onClick={() => setValues(v => ({ ...v, [c.name]: Math.min(c.max ?? value, value + (c.step || 1)) }))}>+</button>
                </div>}
            </div>;
          })}</div></details>)}
          <div className="sticky bottom-0 z-10 flex gap-3 border-t border-line bg-white py-3"><button className="btn btn-outline flex-1" disabled={cameraDisabled || !caps.modes.length} onClick={() => apply(false)}>시험 적용</button>
            <button className="btn btn-primary flex-1" disabled={cameraDisabled || !caps.modes.length} onClick={() => apply(true)}>적용하고 저장</button></div>
          {(dirty || cameraMessage) && <p role="status" className="text-xl font-extrabold">{dirty ? "적용 전" : cameraMessage}</p>}
        </div>}
      </div>
    </section>
    {setup && <details role="tabpanel" aria-labelledby="tab-connections" hidden={tab !== "all" && tab !== "connections"} id="panel-connections" open className="card space-y-5 p-6"><summary className="cursor-pointer text-[28px] font-black">입출력 및 RFID 설정</summary>
      <h2 className="text-[32px] font-black">입출력 연결</h2>
      <p className="text-lg font-bold">모터 DO1 ({bench.state?.pins.motor}), LED DO2 ({bench.state?.pins.led}), 접촉기 DI3 ({bench.state?.pins.feedback})</p>
      {bench.state?.connected && <div className="space-y-3">
        <button className="btn btn-primary" disabled={disabled} onClick={() => bench.action(async () => { await api("/bench/io/disconnect", {}); setMessage("입력 연결 종료됨"); })}>시험 정지하고 설정 수정</button></div>}
      <fieldset disabled={disabled || !!bench.state?.connected} className="grid gap-5 md:grid-cols-2">
        <label className="text-lg font-bold">출력 ON 값<select className="field mt-2" value={setup.do_on_raw ?? ""} onChange={e => field("do_on_raw", e.target.value === "" ? null : Number(e.target.value))}><option value="">미확인</option><option value="0">0</option><option value="1">1</option></select></label>
        <label className="text-lg font-bold">운전 허가 GPIO<input className="field mt-2" type="number" min="0" max="1023" value={setup.permit_line ?? ""} onChange={e => field("permit_line", e.target.value === "" ? null : Number(e.target.value))}/></label>
        <label className="text-lg font-bold">운전 허가 입력값<select className="field mt-2" value={setup.permit_active_raw ?? ""} onChange={e => field("permit_active_raw", e.target.value === "" ? null : Number(e.target.value))}><option value="">미확인</option><option value="0">0</option><option value="1">1</option></select></label>
        {[0, 1].map(i => <label key={i} className="text-lg font-bold">센서 {i + 1} 감지값<select className="field mt-2" value={setup.sensor_active_raw[i] ?? ""} onChange={e => field("sensor_active_raw", setup.sensor_active_raw.map((v: number | null, j: number) => j === i ? e.target.value === "" ? null : Number(e.target.value) : v))}><option value="">미확인</option><option value="0">0</option><option value="1">1</option></select></label>)}
        <label className="flex items-center gap-3 text-lg font-bold"><input className="h-6 w-6" type="checkbox" checked={setup.output_wiring_confirmed} onChange={e => field("output_wiring_confirmed", e.target.checked)}/>출력 배선과 OFF 상태 확인</label>
        <label className="flex items-center gap-3 text-lg font-bold"><input className="h-6 w-6" type="checkbox" checked={setup.stop_circuit_confirmed} onChange={e => field("stop_circuit_confirmed", e.target.checked)}/>현장 정지 회로 확인</label>
      </fieldset>
      <button className="btn btn-primary" disabled={disabled || !!bench.state?.connected || !!bench.state?.rfid_busy} onClick={() => bench.action(async () => { await api("/bench/setup", setup, "PUT"); setMessage("저장됨"); })}>입출력 설정 저장</button>
      <h3 className="text-xl font-extrabold">RFID 연결</h3>
      <button className="btn btn-outline" disabled={portsBusy} onClick={findPorts}>{portsBusy ? "포트 찾는 중" : "RFID 포트 찾기"}</button>
      {portsError && <p role="alert" className="text-lg font-bold text-danger">{portsError}</p>}
      {!portsBusy && !portsError && ports.length === 0 && <p role="status" className="text-lg font-bold">포트 없음</p>}
      <fieldset disabled={disabled || !!bench.state?.rfid_busy} className="grid gap-5 md:grid-cols-2">
        <label className="text-lg font-bold">직렬 포트<select className="field mt-2" value={setup.rfid_port} onChange={e => field("rfid_port", e.target.value)}>
          <option value="">포트 선택</option>{setup.rfid_port && !ports.some(p => p.device === setup.rfid_port) && <option value={setup.rfid_port}>{setup.rfid_port}</option>}
          {ports.map(p => <option key={p.device} value={p.device}>{p.name} ({p.device})</option>)}
        </select></label>
        <label className="text-lg font-bold">읽기 시간 (ms)<input className="field mt-2" type="number" min="100" max="10000" value={setup.rfid_window_ms} onChange={e => field("rfid_window_ms", Number(e.target.value))}/></label>
        <label className="text-lg font-bold">RFID 출력<input className="field mt-2" type="number" min="0" max="2600" step="1" value={setup.rfid_power} onChange={e => field("rfid_power", e.target.value === "" ? "" : Number(e.target.value))}/></label>
        <label className="flex items-center gap-3 text-lg font-bold"><input className="h-6 w-6" type="checkbox" checked={setup.rfid_protocol_confirmed} onChange={e => field("rfid_protocol_confirmed", e.target.checked)}/>RFID 명령 규격 확인</label>
      </fieldset>
      <button className="btn btn-primary" disabled={disabled || !!bench.state?.rfid_busy} onClick={() => bench.action(async () => {
        if (!Number.isInteger(setup.rfid_power) || setup.rfid_power < 0 || setup.rfid_power > 2600) throw new Error("RFID 출력 0~2600");
        await api("/bench/rfid/setup", { rfid_port: setup.rfid_port, rfid_window_ms: setup.rfid_window_ms, rfid_power: setup.rfid_power, rfid_protocol_confirmed: setup.rfid_protocol_confirmed }, "PUT");
        setMessage("저장됨");
      })}>RFID 설정 저장</button>
      {message && <p role="status" className="text-xl font-extrabold">{message}</p>}
    </details>}
  </div>;
}
