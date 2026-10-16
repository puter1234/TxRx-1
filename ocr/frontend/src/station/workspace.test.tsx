import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Equipment from "../screens/Equipment";
import { useApp } from "../lib/store";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./shared", async original => ({ ...(await original<any>()), api: mocks.api }));
vi.mock("./StationApp", () => ({ Equipment: () => null }));
let bench: any;
let values: Record<string, number>;
let lastCapture: any;
const caps = () => ({
  revision: bench.camera.revision,
  modes: [{ width: 640, height: 480, fps: 30, pixel_format: "YUYV" }],
  current: { width: 640, height: 480, fps: 30, pixel_format: "YUYV" },
  controls: Object.entries(values).map(([name, value]) => ({ name, value,
    type: name.endsWith("auto") ? "bool" : "int", min: 0, max: 100, step: 1, flags: "", menu: {} })),
});
const stopRequests = () => vi.mocked(fetch).mock.calls.filter(([path]) => path === "/api/bench/stop");
beforeEach(() => {
  useApp.setState({ connected: true, snapshot: null });
  values = { focus_absolute: 10, focus_auto: 0, white_balance_temperature_auto: 0 };
  lastCapture = null;
  bench = { connected: true, native_busy: false, rfid_busy: false, generation: 1, error: null,
    run: null, runs: {}, io: {}, cooldown_ms: { motor: 0, led: 0 },
    output_blockers: [], sensors: [], sensor_ocr: { active: false, busy: false },
    camera: { connected: true, revision: 1 }, pins: { motor: 51, led: 52, feedback: 106 },
    setup: { sensor_active_raw: [0, 0], rfid_port: "", rfid_window_ms: 500, rfid_protocol_confirmed: true },
  };
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:camera");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, blob: async () => new Blob(["frame"]),
    headers: new Headers({ "X-Camera-Frame": "5", "X-Camera-Revision": "1" }) })));
  mocks.api.mockReset().mockImplementation(async (path: string, body: any) => {
    if (path === "/bench") return structuredClone(bench);
    if (path === "/auth") return { authenticated: true, configured: true, user: { role: "admin" } };
    if (path === "/bench/camera/devices") return { devices: [{ device: "/dev/video0", name: "Test camera" }] };
    if (path === "/bench/ports") return { ports: [] };
    if (path === "/bench/camera/inspect") return caps();
    if (path === "/bench/camera/apply") {
      values = body.profile.controls; bench.camera.revision++;
      return { revision: bench.camera.revision, capabilities: caps() };
    }
    if (path === "/bench/pipeline") return { active: false, busy: false, jobs: [] };
    if (path === "/bench/captures/latest") return lastCapture;
    if (path === "/bench/batches/latest") return null;
    if (path === "/bench/output") {
      bench.runs[body.target] = { id: "run-" + body.target, target: body.target, remaining_ms: null };
      bench.io[body.target + "_requested"] = true;
      return structuredClone(bench);
    }
    if (path === "/bench/heartbeat") return { active: true };
    if (path === "/bench/close") { bench.runs = {}; bench.io = {}; bench.connected = false; return structuredClone(bench); }
    if (path === "/bench/camera/capture") return lastCapture = {
      id: "capture", url: "/api/bench/captures/capture", width: 640, height: 480,
      metadata: { seq: 6, camera_settings_revision: bench.camera.revision },
    };
    throw new Error("Unexpected API request: " + path);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const mount = () => render(<MemoryRouter initialEntries={["/equipment"]}><Routes>
  <Route path="/equipment" element={<Equipment/>}/><Route path="/" element={<p>작업 선택</p>}/>
</Routes></MemoryRouter>);

it("keeps adjustment drafts, sensor conditions and output ownership across tabs; stops on workspace exit", async () => {
  mount();
  const focus = await screen.findByLabelText("초점");
  await waitFor(() => expect((focus as HTMLInputElement).disabled).toBe(false));
  fireEvent.change(focus, { target: { value: "42" } });
  fireEvent.click(within(screen.getByRole("group", { name: "LED 스위치" })).getByRole("button", { name: "켜기" }));
  await screen.findByText("LED 켜기 명령 중");
  fireEvent.click(screen.getByRole("tab", { name: "센서 시험" }));
  fireEvent.change(screen.getByLabelText("센서 감지 후 프레임 수"), { target: { value: "7" } });
  fireEvent.click(screen.getByText("상품코드 형식"));
  fireEvent.change(screen.getByLabelText("확인할 형식"), { target: { value: "[A-Z]{4}" } });
  fireEvent.click(screen.getByRole("tab", { name: "연결 설정" }));
  fireEvent.click(screen.getByRole("tab", { name: "카메라 설정" }));
  expect(screen.getByLabelText("초점")).toHaveProperty("value", "42");
  expect(screen.getByText(/변경한 설정이 아직 적용되지 않았습니다./)).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "센서 시험" }));
  expect(screen.getByLabelText("센서 감지 후 프레임 수")).toHaveProperty("value", "7");
  expect(screen.getByLabelText("확인할 형식")).toHaveProperty("value", "[A-Z]{4}");
  expect(stopRequests()).toHaveLength(0);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/heartbeat", { run_id: "run-led" }));
  fireEvent.click(screen.getByRole("button", { name: "처음 화면" }));
  await screen.findByText("작업 선택");
  expect(mocks.api).toHaveBeenCalledWith("/bench/close", {});
  expect(bench.connected).toBe(false);
  expect(stopRequests()).toHaveLength(0);
});

it("shows unapplied, applied and saved settings; captures with outputs on and preserves the original frame", async () => {
  mount();
  const focus = await screen.findByLabelText("초점");
  await waitFor(() => expect((focus as HTMLInputElement).disabled).toBe(false));
  fireEvent.change(focus, { target: { value: "42" } });
  fireEvent.click(screen.getByRole("button", { name: "시험 적용" }));
  await screen.findByText("영상에 적용했습니다. 저장 전입니다.");
  await waitFor(() => expect((screen.getByRole("button", { name: "적용하고 저장" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "적용하고 저장" }));
  await screen.findByText("설정을 적용하고 저장했습니다");
  expect(mocks.api).toHaveBeenCalledWith("/bench/camera/apply", expect.objectContaining({ expected_revision: 2, save: true }));
  await waitFor(() => expect((within(screen.getByRole("group", { name: "모터 스위치" })).getByRole("button", { name: "켜기" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(within(screen.getByRole("group", { name: "모터 스위치" })).getByRole("button", { name: "켜기" }));
  await screen.findByText("모터 켜기 명령 중");
  await waitFor(() => expect((screen.getByRole("button", { name: "사진 촬영" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "사진 촬영" }));
  const image = await screen.findByAltText("카메라 시험 촬영 결과");
  expect(image.getAttribute("src")).toBe(screen.getByRole("link", { name: "원본 사진 저장" }).getAttribute("href"));
  fireEvent.click(screen.getByRole("button", { name: "원본 1:1" }));
  expect(image.style.width).toBe("640px");
  fireEvent.click(screen.getByRole("tab", { name: "OCR 시험" }));
  await waitFor(() => expect((screen.getByRole("button", { name: "현재 영상 OCR 검사" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("tab", { name: "카메라 설정" }));
  expect(screen.getByAltText("카메라 시험 촬영 결과")).toBe(image);
  expect(stopRequests()).toHaveLength(0);
});

it("does not fault a READY job merely by leaving during a camera read", async () => {
  bench.connected = false;
  let release!: (value: any) => void;
  const fallback = mocks.api.getMockImplementation()!;
  mocks.api.mockImplementation((path: string, body: any) => path === "/bench/camera/inspect"
    ? new Promise(resolve => { release = resolve; }) : fallback(path, body));
  useApp.setState({ snapshot: { busy: false, session: { phase: "READY", active_product: null } } as any });
  mount();
  await waitFor(() => expect(release).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "처음 화면" }));
  expect(stopRequests()).toHaveLength(0);
  await act(async () => { release(caps()); });
});

it("does not silently overwrite a draft with a newer revision polled from another client", async () => {
  mount();
  const focus = await screen.findByLabelText("초점");
  await waitFor(() => expect((focus as HTMLInputElement).disabled).toBe(false));
  fireEvent.change(focus, { target: { value: "42" } });
  bench.camera.revision = 9;
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)); });
  fireEvent.click(screen.getByRole("button", { name: "시험 적용" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/camera/apply", expect.objectContaining({ expected_revision: 1 })));
});

it("sends the chosen capture interval and cancels a pending batch on page exit without faulting a job", async () => {
  let release!: (value: any) => void;
  const fallback = mocks.api.getMockImplementation()!;
  mocks.api.mockImplementation((path: string, body: any) => path === "/bench/camera/batch"
    ? new Promise(resolve => { release = resolve; }) : fallback(path, body));
  mount();
  const focus = await screen.findByLabelText("초점");
  await waitFor(() => expect((focus as HTMLInputElement).disabled).toBe(false));
  fireEvent.change(screen.getByLabelText("촬영 방식"), { target: { value: "multiple" } });
  fireEvent.change(screen.getByLabelText("촬영 장수"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("촬영 간격 (ms)"), { target: { value: "250" } });
  fireEvent.click(screen.getByRole("button", { name: "촬영 시작" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/camera/batch", { count: 3, interval_ms: 250 }));
  act(() => { window.dispatchEvent(new Event("pagehide")); });
  expect(fetch).toHaveBeenCalledWith("/api/bench/camera/batch/cancel", expect.objectContaining({ method: "POST", keepalive: true }));
  expect(stopRequests()).toHaveLength(0);
  await act(async () => { release({ count: 3, saved_fps: 4, skipped_frames: 0, url: "/api/bench/batches/test" }); });
});
