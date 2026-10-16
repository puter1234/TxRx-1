import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import SensorPipelineTest from "../components/SensorPipelineTest";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./shared", async original => ({ ...(await original<any>()), api: mocks.api }));
let state: any;
let bench: any;
beforeEach(() => {
  state = { active: false, busy: false, jobs: [], detected: 0, count: 0, passed: 0, failed: 0,
    settings: { conveyor_sync: true, low_speed_ms: 500, capture_delay_ms: 100, capture_interval_ms: 100,
      departure_timeout_ms: 10000, frame_count: 3, sensor_channel: 1, active_raw: 0, pattern: "" } };
  bench = { state: { connected: true, camera: { connected: true }, setup: {},
      sensors: [{ channel: 1, raw: 1 }, { channel: 2, raw: 1 }] },
    action: (fn: () => Promise<unknown>) => fn(), adoptRuns: vi.fn(), stop: vi.fn() };
  mocks.api.mockReset().mockImplementation(async (path: string, body: any) => {
    if (path === "/bench/pipeline") return structuredClone(state);
    if (path === "/bench/pipeline/settings") { state.settings = body; return body; }
    if (path === "/bench/pipeline/start") {
      state = { ...state, active: true, busy: true, settings: body };
      return { runs: { motor: { id: "motor-run", target: "motor" } }, sensor_ocr: state };
    }
    throw new Error("Unexpected request: " + path);
  });
});
afterEach(cleanup);

it("blocks OCR trial restart during motor wait while keeping stop available", async () => {
  bench.state.cooldown_ms = { motor: 4100 };
  const view = render(<SensorPipelineTest bench={bench} locked={false}/>);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline"));
  expect(screen.getByText("모터 재시작까지 5초")).toBeTruthy();
  expect(screen.getByRole("button", { name: "시험 시작" })).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByRole("button", { name: "시험 정지" }));
  expect(bench.stop).toHaveBeenCalled();
  bench.state.cooldown_ms.motor = 0;
  view.rerender(<SensorPipelineTest bench={bench} locked={false}/>);
  expect(screen.getByRole("button", { name: "시험 시작" })).toHaveProperty("disabled", false);
});

it("saves timings and starts physical OCR without a GPIO-number field", async () => {
  const view = render(<SensorPipelineTest bench={bench} locked={false}/>);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline"));
  fireEvent.change(screen.getByLabelText("저속 유지 (ms)"), { target: { value: "650" } });
  fireEvent.change(screen.getByLabelText("촬영 지연 (ms)"), { target: { value: "150" } });
  fireEvent.change(screen.getByLabelText("OCR 촬영 간격 (ms)"), { target: { value: "90" } });
  fireEvent.click(screen.getByRole("button", { name: "설정 저장" }));
  await screen.findByText("설정을 저장했습니다.");
  view.unmount();
  render(<SensorPipelineTest bench={bench} locked={false}/>);
  await waitFor(() => expect(screen.getByLabelText("저속 유지 (ms)")).toHaveProperty("value", "650"));
  expect(screen.getByLabelText("촬영 지연 (ms)")).toHaveProperty("value", "150");
  expect(screen.queryByLabelText(/GPIO/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "시험 시작" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline/start", expect.objectContaining({
    conveyor_sync: true, low_speed_ms: 650, capture_delay_ms: 150, capture_interval_ms: 90,
    frame_count: 3, sensor_channel: 1, active_raw: 0,
  })));
  expect(bench.adoptRuns).toHaveBeenCalled();
  await screen.findByText("시험 중");
  expect(screen.getByLabelText("저속 유지 (ms)")).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByRole("button", { name: "시험 정지" }));
  expect(bench.stop).toHaveBeenCalled();
});

it("supports one photo and retains the original selected-sensor trial", async () => {
  render(<SensorPipelineTest bench={bench} locked={false}/>);
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline"));
  fireEvent.change(screen.getByLabelText("OCR 촬영 방식"), { target: { value: "single" } });
  expect(screen.queryByLabelText("OCR 촬영 간격 (ms)")).toBeNull();
  expect(screen.getByLabelText("센서 감지 후 프레임 수")).toHaveProperty("value", "1");
  fireEvent.change(screen.getByLabelText("시험 방식"), { target: { value: "sensor" } });
  fireEvent.change(screen.getByLabelText("센서"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("감지값"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "시험 시작" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/pipeline/start", expect.objectContaining({
    conveyor_sync: false, sensor_channel: 2, active_raw: 1, frame_count: 1,
  })));
});
