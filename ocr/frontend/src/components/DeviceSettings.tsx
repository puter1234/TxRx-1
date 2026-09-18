import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended } from "../lib/station";
import Help from "./Help";
import BatchCapture from "./BatchCapture";
import { BenchHeader, CameraView, OutputTests, useBench } from "./DeviceTests";

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
  const bench = useBench(), nav = useNavigate();
  const locked = !ended(useApp(s => s.snapshot?.session));
  const [devices, setDevices] = useState<{device: string; name: string}[]>([]);
  const [device, setDevice] = useState(""), [discovery, setDiscovery] = useState("");
  const [caps, setCaps] = useState<{ modes: Mode[]; controls: Control[]; current: any } | null>(null);
  const [modeIndex, setModeIndex] = useState(0), [values, setValues] = useState<Record<string, number>>({});
  const [setup, setSetup] = useState<any>(null), [ports, setPorts] = useState<{device: string; name: string}[]>([]);
  const [message, setMessage] = useState("");
  useEffect(() => { if (!setup && bench.state) setSetup(bench.state.setup); }, [bench.state, setup]);
  const find = async () => {
    const result = await api("/bench/camera/devices");
    setDevices(result.devices || []); setDiscovery(result.error || "");
    const prior = bench.state?.camera?.profile?.device || bench.state?.camera?.saved_profile?.device;
    setDevice(old => old || prior || result.devices?.[0]?.device || "");
    const serial = await api("/bench/ports"); setPorts(serial.ports || []);
  };
  useEffect(() => { void find().catch(e => setDiscovery(e.message)); }, []);
  const inspect = async () => {
    const data = await api("/bench/camera/inspect", { device });
    setCaps(data);
    const current = data.current;
    setModeIndex(Math.max(0, data.modes.findIndex((m: Mode) => current && m.width === current.width && m.height === current.height && Math.abs(m.fps - current.fps) < 0.05 && m.pixel_format === current.pixel_format)));
    setValues(Object.fromEntries(data.controls.map((c: Control) => [c.name, c.value])));
    setMessage("");
  };
  const apply = (save: boolean) => bench.action(async () => {
    if (!caps?.modes[modeIndex]) return;
    const controls = Object.fromEntries(caps.controls
      .filter(c => !/read-only|disabled/.test(c.flags) && values[c.name] !== undefined && controlActive(c, caps.controls, values))
      .map(c => [c.name, values[c.name]]));
    const result = await api("/bench/camera/apply", {
      profile: { device, ...caps.modes[modeIndex], controls }, save,
      expected_revision: bench.state?.camera?.revision || 0,
    });
    setCaps(result.capabilities);
    setValues(Object.fromEntries(result.capabilities.controls.map((c: Control) => [c.name, c.value])));
    setMessage(save ? "적용값을 확인하고 저장했습니다" : "시험 설정을 적용했습니다");
  });
  const disabled = locked || bench.busy || !!bench.state?.native_busy;
  const field = (key: string, value: any) => setSetup((old: any) => ({ ...old, [key]: value }));
  return <div className="space-y-5">
    <div className="flex gap-4"><button className="btn btn-outline" onClick={() => nav("/equipment")}>장비 점검으로</button></div>
    <BenchHeader bench={bench}/>
    <section className="card space-y-5 p-6">
      <div className="flex items-center"><h2 className="text-2xl font-extrabold">카메라 설정</h2>
        <Help text="지원 목록을 읽고 해상도와 촬영값을 지정합니다. 시험 적용으로 영상을 확인한 뒤 저장하세요. 설정 변경 중에는 생산 작업을 시작할 수 없습니다."/></div>
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-72 flex-1 text-lg font-bold">카메라
          <select className="field mt-2" value={device} disabled={disabled} onChange={e => { setDevice(e.target.value); setCaps(null); setMessage(""); }}>
            <option value="">카메라 선택</option>{devices.map(d => <option value={d.device} key={d.device}>{d.name} ({d.device})</option>)}
          </select></label>
        <button className="btn btn-outline" disabled={disabled} onClick={() => bench.action(find)}>장치 찾기</button>
        <button className="btn btn-primary" disabled={disabled || !device} onClick={() => bench.action(inspect)}>설정 읽기</button>
      </div>
      {discovery && <p className="text-lg font-bold">{discovery}</p>}
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-4"><CameraView connected={bench.state?.camera?.connected === true}/>
          {bench.state?.camera?.width && <p className="text-lg font-bold">실제 영상 {bench.state.camera.width} × {bench.state.camera.height} / {Number(bench.state.camera.mean_received_fps || 0).toFixed(1)} fps</p>}
          <BatchCapture bench={bench} locked={locked}/>
          <details><summary className="cursor-pointer text-lg font-bold">조명 시험</summary><OutputTests bench={bench} ledOnly/></details>
        </div>
        {caps && <div className="space-y-4">
          <label className="block text-lg font-bold">해상도와 촬영 속도
            <select className="field mt-2" value={modeIndex} disabled={disabled} onChange={e => { setModeIndex(Number(e.target.value)); setMessage(""); }}>
              {caps.modes.map((m, i) => <option value={i} key={i}>{m.width} × {m.height} / {m.fps} fps / {m.pixel_format}</option>)}
            </select></label>
          {[true, false].map(primary => <details key={String(primary)} open={primary}>
          <summary className="mb-3 cursor-pointer text-xl font-bold">{primary ? "노출, 게인, 초점" : "추가 설정"}</summary>
          <div className="grid gap-4 sm:grid-cols-2">{caps.controls.filter(c => labels[c.name] && (/(exposure|focus|gain)/.test(c.name) === primary)).map(c => {
            const readonly = /read-only|disabled/.test(c.flags);
            // An inactive manual control can be changed with its automatic mode in the same apply.
            const inactive = !controlActive(c, caps.controls, values);
            const label = labels[c.name], value = values[c.name] ?? c.value;
            return <div key={c.name} className="rounded-xl border border-line p-4">
              <div className="mb-3 flex items-center"><label htmlFor={"camera-" + c.name} className="text-lg font-bold">{label}</label>
                <Help text={c.name.includes("focus") ? "초점 숫자는 렌즈 위치입니다. 거리 단위가 아닙니다. 영상의 글자를 보면서 맞추세요." : c.name.includes("exposure") ? "카메라가 보고한 제어값입니다. 자동 노출을 수동으로 바꾼 뒤 조절하세요." : "카메라가 보고한 범위 안에서 조절합니다."}/></div>
              {Object.keys(c.menu).length ? <select id={"camera-" + c.name} className="field" disabled={disabled || readonly || inactive} value={value} onChange={e => setValues(v => ({ ...v, [c.name]: Number(e.target.value) }))}>
                {Object.entries(c.menu).map(([n, text]) => <option key={n} value={n}>{menuLabel(text)}</option>)}
              </select> : c.type === "bool" ? <button id={"camera-" + c.name} role="switch" aria-label={label} aria-checked={value !== 0} className={"btn w-full " + (value ? "btn-primary" : "btn-outline")} disabled={disabled || readonly || inactive} onClick={() => setValues(v => ({ ...v, [c.name]: value ? 0 : 1 }))}>{value ? "켜짐" : "꺼짐"}</button>
                : <div className="flex items-center gap-2">
                  <button aria-label={label + " 줄이기"} className="btn btn-outline px-4 text-2xl" disabled={disabled || readonly || inactive || value <= (c.min ?? 0)} onClick={() => setValues(v => ({ ...v, [c.name]: Math.max(c.min ?? 0, value - (c.step || 1)) }))}>−</button>
                  <input id={"camera-" + c.name} type="number" className="field min-w-0 text-center" min={c.min} max={c.max} step={c.step || 1} disabled={disabled || readonly || inactive} value={value} onChange={e => setValues(v => ({ ...v, [c.name]: Number(e.target.value) }))}/>
                  <button aria-label={label + " 늘리기"} className="btn btn-outline px-4 text-2xl" disabled={disabled || readonly || inactive || value >= (c.max ?? value)} onClick={() => setValues(v => ({ ...v, [c.name]: Math.min(c.max ?? value, value + (c.step || 1)) }))}>+</button>
                </div>}
            </div>;
          })}</div></details>)}
          {!caps.controls.some(c => c.name === "gain") && <p className="text-lg font-bold">게인: 카메라 드라이버에서 제어를 제공하지 않습니다.</p>}
          <div className="flex gap-3"><button className="btn btn-outline flex-1" disabled={disabled || !caps.modes.length} onClick={() => apply(false)}>시험 적용</button>
            <button className="btn btn-primary flex-1" disabled={disabled || !caps.modes.length} onClick={() => apply(true)}>적용하고 저장</button></div>
          {message && <p role="status" className="text-lg font-bold">{message}</p>}
        </div>}
      </div>
    </section>
    {setup && <details className="card space-y-5 p-6"><summary className="cursor-pointer text-xl font-bold">입출력 및 RFID 설정</summary>
      <div className="flex items-center"><h2 className="text-2xl font-extrabold">입출력 연결</h2><Help text="배선 확인 후 값을 입력하세요. 입력 연결을 종료해야 수정할 수 있습니다. 저장해도 생산 운전 승인은 바뀌지 않습니다."/></div>
      <p className="text-lg font-bold">모터 DO1 ({bench.state?.pins.motor}), LED DO2 ({bench.state?.pins.led}), 접촉기 DI3 ({bench.state?.pins.feedback})</p>
      <fieldset disabled={disabled || !!bench.state?.connected} className="grid gap-5 md:grid-cols-2">
        <label className="text-lg font-bold">출력 ON 값<select className="field mt-2" value={setup.do_on_raw ?? ""} onChange={e => field("do_on_raw", e.target.value === "" ? null : Number(e.target.value))}><option value="">미확인</option><option value="0">0</option><option value="1">1</option></select></label>
        <label className="text-lg font-bold">운전 허가 GPIO<input className="field mt-2" type="number" min="0" max="1023" value={setup.permit_line ?? ""} onChange={e => field("permit_line", e.target.value === "" ? null : Number(e.target.value))}/></label>
        <label className="text-lg font-bold">운전 허가 입력값<select className="field mt-2" value={setup.permit_active_raw ?? ""} onChange={e => field("permit_active_raw", e.target.value === "" ? null : Number(e.target.value))}><option value="">미확인</option><option value="0">0</option><option value="1">1</option></select></label>
        <label className="text-lg font-bold">접촉기 응답 제한시간 (ms)<input className="field mt-2" type="number" min="20" max="10000" value={setup.feedback_timeout_ms ?? ""} onChange={e => field("feedback_timeout_ms", e.target.value === "" ? null : Number(e.target.value))}/></label>
        {[0, 1].map(i => <label key={i} className="text-lg font-bold">센서 {i + 1} 감지값<select className="field mt-2" value={setup.sensor_active_raw[i] ?? ""} onChange={e => field("sensor_active_raw", setup.sensor_active_raw.map((v: number | null, j: number) => j === i ? e.target.value === "" ? null : Number(e.target.value) : v))}><option value="">미확인</option><option value="0">0</option><option value="1">1</option></select></label>)}
        <label className="flex items-center gap-3 text-lg font-bold"><input className="h-6 w-6" type="checkbox" checked={setup.output_wiring_confirmed} onChange={e => field("output_wiring_confirmed", e.target.checked)}/>출력 배선과 OFF 상태 확인</label>
        <label className="flex items-center gap-3 text-lg font-bold"><input className="h-6 w-6" type="checkbox" checked={setup.stop_circuit_confirmed} onChange={e => field("stop_circuit_confirmed", e.target.checked)}/>현장 정지 회로 확인</label>
      </fieldset>
      <h3 className="text-xl font-extrabold">RFID 연결</h3>
      <fieldset disabled={disabled || !!bench.state?.connected} className="grid gap-5 md:grid-cols-2">
        <label className="text-lg font-bold">직렬 포트<select className="field mt-2" value={setup.rfid_port} onChange={e => field("rfid_port", e.target.value)}>
          <option value="">포트 선택</option>{setup.rfid_port && !ports.some(p => p.device === setup.rfid_port) && <option value={setup.rfid_port}>{setup.rfid_port}</option>}
          {ports.map(p => <option key={p.device} value={p.device}>{p.name} ({p.device})</option>)}
        </select></label>
        <label className="text-lg font-bold">읽기 시간 (ms)<input className="field mt-2" type="number" min="100" max="10000" value={setup.rfid_window_ms} onChange={e => field("rfid_window_ms", Number(e.target.value))}/></label>
        <label className="flex items-center gap-3 text-lg font-bold"><input className="h-6 w-6" type="checkbox" checked={setup.rfid_protocol_confirmed} onChange={e => field("rfid_protocol_confirmed", e.target.checked)}/>RFID 명령 규격 확인<Help text="YRM1006 리더의 제공 명령서와 현재 구현을 대조한 뒤 선택합니다. 읽기 시험은 지역과 출력 초기화 명령을 포함합니다."/></label>
      </fieldset>
      <button className="btn btn-primary" disabled={disabled || !!bench.state?.connected} onClick={() => bench.action(async () => { await api("/bench/setup", setup, "PUT"); setMessage("연결 설정을 저장했습니다"); })}>연결 설정 저장</button>
      {message === "연결 설정을 저장했습니다" && <p role="status" className="text-lg font-bold">{message}</p>}
    </details>}
  </div>;
}
