import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TestBench from "../screens/TestBench";
import ProcessTest from "../components/bench/ProcessTest";
import { WiringPanel } from "../components/DeviceSettings";
import CameraBox from "../ui/CameraBox";
import ResultView from "../components/bench/ResultView";
import { useApp } from "../lib/store";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./shared", async (original) => ({ ...(await original<any>()), api: mocks.api }));

const clone = <T,>(v: T): T => structuredClone(v);
let bench: any;
let pipeline: any;
let values: Record<string, number>;
let ports: { device: string; name: string; usb: boolean }[];
let rfidReply: () => any;
let trial: any;
let extraModes: any[];
const saved = { device: "/dev/video0", width: 640, height: 480, fps: 30, pixel_format: "YUYV", controls: { focus_absolute: 10 } };
const caps = () => ({
  revision: bench.camera.revision, saved_profile: bench.camera.saved_profile,
  modes: [{ width: 640, height: 480, fps: 30, pixel_format: "YUYV" }, ...extraModes],
  current: { width: 640, height: 480, fps: 30, pixel_format: "YUYV" },
  controls: Object.entries(values).map(([name, value]) => ({ name, value,
    type: name.endsWith("auto") ? "bool" : "int", min: 0, max: 100, step: 1, flags: "", menu: {} })),
});
const job = {
  id: "job1", number: 1, state: "passed", counted: true, missed_frames: 0, capture_error: null, matched_text: "AB12",
  frames: [{ seq: 42, after_trigger_ms: 100, state: "passed", image_available: true, crop_count: 1,
    result: { error: null, reads: [{ lines: [{ text: "AB12", confidence: 0.99 }] }] } }],
};
const fetches = (path: string) => vi.mocked(fetch).mock.calls.filter(([p]) => p === path);

beforeEach(() => {
  useApp.setState({ connected: true, snapshot: null, equipment: null } as any);
  values = { focus_absolute: 10, focus_auto: 0 };
  extraModes = [];
  ports = [{ device: "/dev/ttyUSB0", name: "CP2102", usb: true }];
  rfidReply = () => ({ ok: true, tags: [{ epc: "E200", count: 3, max_rssi: -41 }], detail: "읽은 태그 1개" });
  trial = { active: false, total: 7, boxes: [], width: 0, height: 0, inference_ms: null, frames: 0, error: null, preset: null };
  bench = {
    connected: true, native_busy: false, rfid_busy: false, generation: 1, error: null, run: null, runs: {}, io: {},
    cooldown_ms: { motor: 0, led: 0, speed: 0 }, output_blockers: [], sensor_ocr: { active: false, busy: false },
    sensors: [{ channel: 1, line: 105, raw: 1, active: null }, { channel: 2, line: 144, raw: 1, active: null }],
    feedback: { channel: 3, line: 106, raw: 1, active: false },
    camera: { connected: true, wanted: true, revision: 1, profile: saved, saved_profile: saved },
    pins: { motor: 51, led: 52, speed: 50, feedback: 106, chip: "/dev/gpiochip0" }, wiring_fixed: true,
    setup: { do_on_raw: null, permit_line: null, permit_active_raw: null, sensor_active_raw: [null, null],
      output_wiring_confirmed: false, stop_circuit_confirmed: false, rfid_port: "", rfid_window_ms: 500,
      rfid_power: 2600, rfid_protocol_confirmed: false },
    rfid: null,
  };
  pipeline = { active: false, busy: false, error: null, stop_reason: null, jobs: [], detected: 0, count: 0, passed: 0,
    failed: 0, await_clear: false,
    settings: { conveyor_sync: true, low_speed_ms: 500, capture_delay_ms: 100, capture_interval_ms: 100,
      departure_timeout_ms: 10000, frame_count: 3, sensor_channel: 1, active_raw: 0, pattern: "", locator: "opencv" } };
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:camera");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, blob: async () => new Blob(["frame"]), headers: new Headers() })));
  mocks.api.mockReset().mockImplementation(async (path: string, body: any) => {
    if (path === "/bench") return clone(bench);
    if (path === "/bench/io/connect") { bench.connected = true; return clone(bench); }
    if (path === "/bench/output") {
      bench.runs[body.target] = { id: "run-" + body.target, target: body.target, remaining_ms: null };
      bench.io[body.target + "_requested"] = true;
      return clone(bench);
    }
    if (path === "/bench/heartbeat") return { active: true };
    if (path === "/bench/camera/connect") { bench.camera.connected = true; bench.camera.wanted = true; return clone(bench); }
    if (path === "/bench/camera/devices") return { devices: [{ device: "/dev/video0", name: "Test camera" }] };
    if (path === "/bench/camera/inspect") return caps();
    if (path === "/bench/camera/apply") {
      values = { ...values, ...body.profile.controls };
      bench.camera.revision++;
      bench.camera.saved_profile = body.profile;
      return { revision: bench.camera.revision, capabilities: caps() };
    }
    if (path === "/bench/ocr/read") return {
      reads: [{ lines: [{ text: "ABC123", confidence: 0.94, preview: "data:image/png;base64,dGVzdA==" }] }], error: null,
      ms_model_load: 0, ms_barcode: 2, ms_ocr: 6, ocr_device: "cuda:0", ocr_gpu_name: "Orin",
      preview_url: "/api/bench/ocr/frames/f1", original_url: "/api/bench/ocr/frames/f1?original=true",
    };
    if (path === "/bench/pipeline") return clone(pipeline);
    if (path === "/bench/pipeline/settings") { pipeline.settings = body; return body; }
    if (path === "/bench/pipeline/start") {
      pipeline = { ...pipeline, active: true, busy: true, settings: body };
      return { ...clone(bench), runs: { motor: { id: "motor-run", target: "motor" } } };
    }
    if (path === "/bench/ports") return { ports };
    if (path === "/bench/rfid/setup") { bench.setup = { ...bench.setup, ...body }; return clone(bench); }
    if (path === "/bench/rfid") { bench.rfid = rfidReply(); return bench.rfid; }
    if (path === "/bench/setup") { bench.setup = { ...body }; return clone(bench); }
    if (path === "/bench/batches/latest") return null;
    if (path === "/presets") return [{ id: "wappen", name: "와펜 계수", kind: "vision", enabled: true, flow: {} },
      { id: "simple", name: "단순 계수", kind: "simple", enabled: true, flow: {} }];
    if (path === "/bench/vision") return clone(trial);
    if (path === "/bench/vision/start") {
      trial = { ...trial, active: true, total: 0, preset: { id: body.preset_id, name: "와펜 계수", flow: { axis: "y", line: 0.5 } } };
      return clone(trial);
    }
    if (path === "/bench/vision/stop") { trial = { ...trial, active: false }; return clone(trial); }
    throw new Error("Unexpected API request: " + path);
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const mount = (mode = "process") =>
  render(<MemoryRouter initialEntries={[`/settings?section=test&mode=${mode}`]}><TestBench /></MemoryRouter>);
const strip = () => within(screen.getByRole("region", { name: "장비 상태" }));

it("opens the inputs by itself and releases them when the screen is left", async () => {
  bench.connected = false;
  const view = mount();
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/io/connect", {}));
  await waitFor(() => expect(strip().getByText("센서 1 없음")).toBeTruthy());
  expect(screen.queryByRole("button", { name: /입력 연결/ })).toBeNull();
  view.unmount();
  expect(fetches("/api/bench/close")).toHaveLength(1);
  expect(fetches("/api/bench/stop")).toHaveLength(0);
});

it("switches outputs with one press and shows the restart wait on the button", async () => {
  bench.runs.led = { id: "led-run", target: "led", remaining_ms: null };
  bench.io.led_requested = true;
  bench.cooldown_ms.motor = 4100;
  mount();
  const motor = () => within(screen.getByRole("group", { name: "모터" }));
  await waitFor(() => expect(motor().getByRole("button", { name: "켜기 5초" })).toHaveProperty("disabled", true));
  expect(motor().getByRole("button", { name: "끄기" })).toHaveProperty("disabled", false);
  // The current choice stays marked while it cannot be pressed again.
  const led = within(screen.getByRole("group", { name: "LED" }));
  expect(led.getByRole("button", { name: "켜기" }).getAttribute("aria-pressed")).toBe("true");
  bench.cooldown_ms.motor = 0;
  await waitFor(() => expect(motor().getByRole("button", { name: "켜기" })).toHaveProperty("disabled", false));
  fireEvent.click(motor().getByRole("button", { name: "켜기" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/output", expect.objectContaining({ target: "motor" })));
});

it("warns on the contactor when the motor is on but DI3 does not answer", async () => {
  bench.runs.motor = { id: "run-motor", target: "motor", remaining_ms: null, feedback_checked: true, feedback_error: "접촉기 가동 응답 없음" };
  bench.io.motor_requested = true;
  mount();
  await waitFor(() => expect(strip().getByText("접촉기 가동 응답 없음")).toBeTruthy());
});

it("shows a dropped camera coming back with nothing to press, and turns a switched-off camera on with one press", async () => {
  bench.camera = { ...bench.camera, connected: false, reconnecting: true };
  mount();
  await waitFor(() => expect(strip().getByText("카메라 연결 중")).toBeTruthy());
  expect(screen.queryByRole("button", { name: "카메라 켜기" })).toBeNull();
  const blocked = screen.getAllByRole("button", { name: "카메라 연결 중" });
  expect(blocked).toHaveLength(2);
  for (const button of blocked) expect(button).toHaveProperty("disabled", true);
  bench.camera = { ...bench.camera, reconnecting: false, wanted: false, error: "카메라 연결을 확인하세요." };
  await waitFor(() => expect(strip().getByRole("alert").textContent).toBe("카메라 연결을 확인하세요."));
  fireEvent.click(await screen.findByRole("button", { name: "카메라 켜기" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/camera/connect", {}));
  await waitFor(() => expect(strip().getByText("카메라 640 × 480, 초당 30장")).toBeTruthy());
});

it("reads text with one press and shows the reading, the photo and its original in a sheet", async () => {
  mount();
  const read = await screen.findByRole("button", { name: "문자 읽기" });
  await waitFor(() => expect(read).toHaveProperty("disabled", false));
  fireEvent.click(read);
  const sheet = await screen.findByRole("dialog", { name: "문자 읽기" });
  // The process test's locator is used for the live reading too.
  expect(mocks.api).toHaveBeenCalledWith("/bench/ocr/read", { locator: "opencv" });
  expect(within(sheet).getByText("ABC123")).toBeTruthy();
  expect(within(sheet).getByText("신뢰도 94.0%")).toBeTruthy();
  expect(within(sheet).getByText("OCR GPU 사용: Orin")).toBeTruthy();
  expect(within(sheet).getByRole("button", { name: "판독 정보 저장" })).toBeTruthy();
  expect(within(sheet).getByAltText("문자 읽기").getAttribute("src")).toBe("/api/bench/ocr/frames/f1");
  expect(within(sheet).getByRole("link", { name: "원본 저장" }).getAttribute("href")).toBe("/api/bench/ocr/frames/f1?original=true");
  fireEvent.click(within(sheet).getByRole("button", { name: "닫기" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("reads text with the process test's saved locator when another tab is open", async () => {
  mount("rfid");
  const read = await screen.findByRole("button", { name: "문자 읽기" });
  await waitFor(() => expect(read).toHaveProperty("disabled", false));
  fireEvent.click(read);
  await screen.findByRole("dialog", { name: "문자 읽기" });
  expect(mocks.api).toHaveBeenCalledWith("/bench/ocr/read", { locator: "opencv" });
});

it("reads RFID tags with one press without a reader confirmation step", async () => {
  mount("rfid");
  const read = await screen.findByRole("button", { name: "태그 읽기" });
  await waitFor(() => expect(read).toHaveProperty("disabled", false));
  expect(screen.queryByText("YRM 리더 사용")).toBeNull();
  fireEvent.click(read);
  expect(await screen.findByText("E200")).toBeTruthy();
  rfidReply = () => { throw new Error("RFID 응답이 없습니다."); };
  fireEvent.click(screen.getByRole("button", { name: "태그 읽기" }));
  expect((await screen.findByRole("alert")).textContent).toBe("RFID 응답이 없습니다.");
});

it("asks for the reader port when several USB serial devices are plugged in and lets it change later", async () => {
  ports = [{ device: "/dev/ttyTHS1", name: "n/a", usb: false }, { device: "/dev/ttyUSB0", name: "CP2102", usb: true },
    { device: "/dev/ttyUSB1", name: "CH340", usb: true }];
  mount("rfid");
  const select = await screen.findByLabelText("RFID 리더 포트");
  expect(within(select).queryByRole("option", { name: /ttyTHS1/ })).toBeNull();
  expect(screen.getByRole("button", { name: "태그 읽기" })).toHaveProperty("disabled", true);
  fireEvent.change(select, { target: { value: "/dev/ttyUSB1" } });
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/rfid/setup", { rfid_port: "/dev/ttyUSB1" }, "PUT"));
  await waitFor(() => expect(screen.getByRole("button", { name: "태그 읽기" })).toHaveProperty("disabled", false));
  const chosen = screen.getByLabelText("RFID 리더 포트");
  expect(chosen).toHaveProperty("value", "/dev/ttyUSB1");
  expect(within(chosen).queryByRole("option", { name: "고르기" })).toBeNull();
  fireEvent.change(chosen, { target: { value: "/dev/ttyUSB0" } });
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/rfid/setup", { rfid_port: "/dev/ttyUSB0" }, "PUT"));
});

it("saves every camera change by itself and starts from the saved values", async () => {
  bench.camera.saved_profile = { ...saved, controls: { focus_absolute: 30 } };
  mount("quality");
  const more = await screen.findByRole("button", { name: "초점 늘리기" });
  expect(screen.getByLabelText("초점")).toHaveProperty("value", "30");
  fireEvent.click(more);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/camera/apply", {
    profile: expect.objectContaining({ device: "/dev/video0", width: 640, controls: expect.objectContaining({ focus_absolute: 31 }) }),
    save: true,
  }), { timeout: 2000 });
  expect(await screen.findByText("저장됨")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /적용|저장/ })).toBeNull();
});

it("tells apart two picture formats of the same size and speed", async () => {
  extraModes = [{ width: 640, height: 480, fps: 30, pixel_format: "MJPG" }, { width: 1280, height: 720, fps: 30, pixel_format: "MJPG" }];
  mount("quality");
  const select = await screen.findByLabelText("해상도");
  expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
    "640 × 480, 초당 30장, YUYV", "640 × 480, 초당 30장, MJPG", "1280 × 720, 초당 30장"]);
});

it("keeps adjusting the camera during a process test but holds the resolution", async () => {
  bench.sensor_ocr = { active: true, busy: true };
  mount("quality");
  await screen.findByRole("button", { name: "초점 늘리기" });
  expect(screen.getByLabelText("해상도")).toHaveProperty("disabled", true);
  expect(screen.getByRole("button", { name: "초점 늘리기" })).toHaveProperty("disabled", false);
});

it("sends the chosen batch interval and cancels a pending batch when the page goes away", async () => {
  let release!: (value: any) => void;
  const fallback = mocks.api.getMockImplementation()!;
  mocks.api.mockImplementation((path: string, body: any) => path === "/bench/camera/batch"
    ? new Promise((resolve) => { release = resolve; }) : fallback(path, body));
  mount();
  const open = await screen.findByRole("button", { name: "여러 장" });
  await waitFor(() => expect(open).toHaveProperty("disabled", false));
  fireEvent.click(open);
  const sheet = await screen.findByRole("dialog", { name: "여러 장 찍기" });
  fireEvent.change(within(sheet).getByLabelText("촬영 장수"), { target: { value: "3" } });
  fireEvent.change(within(sheet).getByLabelText("촬영 간격 (ms)"), { target: { value: "250" } });
  fireEvent.click(within(sheet).getByRole("button", { name: "촬영 시작" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/camera/batch", { count: 3, interval_ms: 250 }));
  act(() => { window.dispatchEvent(new Event("pagehide")); });
  expect(fetch).toHaveBeenCalledWith("/api/bench/camera/batch/cancel", expect.objectContaining({ method: "POST", keepalive: true }));
  expect(fetches("/api/bench/stop")).toHaveLength(0);
  await act(async () => { release({ count: 3, saved_fps: 4, skipped_frames: 0, url: "/api/bench/batches/test" }); });
});

it("counts wappen on the live camera with one press, starting from zero", async () => {
  mount("wappen");
  const start = await screen.findByRole("button", { name: "시험 시작" });
  // The previous trial's count is not shown as this one's.
  expect(screen.getByText("0")).toBeTruthy();
  expect(screen.queryByText("7")).toBeNull();
  fireEvent.click(start);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/vision/start", { preset_id: "wappen" }));
  trial.total = 3;
  expect(await screen.findByText("3")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "시험 정지" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/vision/stop", {}));
  await screen.findByRole("button", { name: "시험 시작" });
  expect(screen.getByText("3")).toBeTruthy();
});

it("stops a wappen trial left running when another tab is opened", async () => {
  mount("wappen");
  fireEvent.click(await screen.findByRole("button", { name: "시험 시작" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/vision/start", { preset_id: "wappen" }));
  await screen.findByRole("button", { name: "시험 정지" });
  fireEvent.click(screen.getByRole("tab", { name: "RFID" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/vision/stop", {}));
});

it("still saves a camera change made just before leaving the tab", async () => {
  mount("quality");
  fireEvent.click(await screen.findByRole("button", { name: "초점 늘리기" }));
  fireEvent.click(screen.getByRole("tab", { name: "공정 시험" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/camera/apply",
    expect.objectContaining({ profile: expect.objectContaining({ controls: expect.objectContaining({ focus_absolute: 11 }) }) })));
});

it("offers the text finder only with the model locator and saves the choice", async () => {
  render(<ProcessTest bench={hook()} locked={false} onShow={() => {}} onSettings={() => {}} />);
  await screen.findByRole("button", { name: "시험 시작" });
  expect(screen.queryByLabelText("글자 위치 찾기")).toBeNull();
  fireEvent.change(screen.getByLabelText("바코드 위치 찾기"), { target: { value: "yolo26" } });
  fireEvent.change(screen.getByLabelText("글자 위치 찾기"), { target: { value: "lines" } });
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline/settings",
    expect.objectContaining({ locator: "yolo26", text_finder: "lines" }), "PUT"));
});

const hook = () => ({
  state: { connected: true, sensors: [{ channel: 1, raw: 1 }, { channel: 2, raw: 1 }], cooldown_ms: { motor: 0 } },
  busy: false, action: (fn: () => Promise<unknown>) => fn(), adoptRuns: vi.fn(), stop: vi.fn(), refresh: vi.fn(),
}) as any;

it("starts the process test with one press and saves setting changes by themselves", async () => {
  const h = hook();
  render(<ProcessTest bench={h} locked={false} onShow={() => {}} onSettings={() => {}} />);
  const start = await screen.findByRole("button", { name: "시험 시작" });
  fireEvent.change(screen.getByLabelText("촬영 지연 (ms)"), { target: { value: "150" } });
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline/settings",
    expect.objectContaining({ capture_delay_ms: 150, locator: "opencv" }), "PUT"));
  expect(screen.queryByRole("button", { name: /설정 저장/ })).toBeNull();
  fireEvent.click(start);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline/start", expect.objectContaining({ capture_delay_ms: 150 })));
  expect(h.adoptRuns).toHaveBeenCalled();
  await screen.findByText("시험 중");
  fireEvent.click(screen.getByRole("button", { name: "시험 정지" }));
  expect(h.stop).toHaveBeenCalled();
});

it("says on the start button what has to happen first", async () => {
  const h = hook();
  h.state.sensors[0].raw = 0;
  const view = render(<ProcessTest bench={h} locked={false} onShow={() => {}} onSettings={() => {}} />);
  expect(await screen.findByRole("button", { name: "센서 앞 제품 치우기" })).toHaveProperty("disabled", true);
  h.state = { ...h.state, sensors: [{ channel: 1, raw: 1 }, { channel: 2, raw: 1 }], cooldown_ms: { motor: 4100 } };
  view.rerender(<ProcessTest bench={{ ...h }} locked={false} onShow={() => {}} onSettings={() => {}} />);
  expect(screen.getByRole("button", { name: "모터 재시작 5초" })).toHaveProperty("disabled", true);
  view.rerender(<ProcessTest bench={{ ...h }} locked onShow={() => {}} onSettings={() => {}} />);
  expect(screen.getByRole("button", { name: "작업 진행 중" })).toHaveProperty("disabled", true);
});

it("keeps quiet about a stop the user asked for, reports one the test made, and opens product photos", async () => {
  pipeline.stop_reason = "정지";
  pipeline.jobs = [job];
  const onShow = vi.fn();
  render(<ProcessTest bench={hook()} locked={false} onShow={onShow} onSettings={() => {}} />);
  await screen.findByText("AB12");
  expect(screen.queryByRole("alert")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "1번 사진 읽음" }));
  const url = "/api/bench/pipeline/frames/job1/42";
  expect(onShow).toHaveBeenCalledWith(expect.objectContaining({
    url, download: url + "?original=true", lines: [{ text: "AB12", confidence: 0.99, image: url + "?crop=0" }],
  }));
  pipeline.stop_reason = "화면 연결 끊김";
  expect((await screen.findByRole("alert")).textContent).toBe("화면 연결 끊김");
});

it("opens a product photo whose reading has no location details", () => {
  const url = "/api/bench/pipeline/frames/job1/42";
  render(<ResultView shown={{ title: "1번 제품, 1번 사진", url, diagnostics: {} as any, lines: [{ text: "AB12" }],
    report: { after_trigger_ms: 112.4, error: null, reads: [], barcode_diagnostics: {} } }} />);
  expect(screen.getByText("AB12")).toBeTruthy();
  expect(screen.getByText("감지 후 112 ms")).toBeTruthy();
  expect(screen.getByRole("button", { name: "판독 정보 저장" })).toBeTruthy();
});

it("folds the documented wiring choices away, keeps them reachable and saves each choice by itself", async () => {
  const h = { state: clone(bench), refresh: vi.fn().mockResolvedValue({}) } as any;
  const view = render(<WiringPanel bench={h} />);
  expect(screen.getByText("GPIO 51")).toBeTruthy();
  expect(screen.getAllByText("켜짐 신호 1")).toHaveLength(2);
  expect(screen.getByText("배선 바꾸기").closest("details")?.open).toBe(false);
  expect(screen.getByLabelText("운전 허가 GPIO")).toBeTruthy();
  h.state.wiring_fixed = false;
  view.rerender(<WiringPanel bench={{ ...h }} />);
  fireEvent.click(within(screen.getByRole("group", { name: "출력 켜짐 신호" })).getByRole("button", { name: "1" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/setup", expect.objectContaining({ do_on_raw: 1 }), "PUT"));
  expect(await screen.findByText("저장됨")).toBeTruthy();
});

it("shows a worker's dropped camera coming back with nothing to press", () => {
  useApp.setState({ equipment: { camera: { connected: false, reconnecting: true } } } as any);
  render(<CameraBox />);
  expect(screen.getByText("카메라 연결 중")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "카메라 켜기" })).toBeNull();
  act(() => useApp.setState({ equipment: { camera: { connected: false, reconnecting: true, error: "카메라를 열 수 없습니다." } } } as any));
  expect(screen.getByRole("alert").textContent).toBe("카메라를 열 수 없습니다.");
  act(() => useApp.setState({ equipment: { camera: { connected: false, reconnecting: false, error: "카메라를 열 수 없습니다." } } } as any));
  expect(screen.getByRole("button", { name: "카메라 켜기" })).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toBe("카메라를 열 수 없습니다.");
});
