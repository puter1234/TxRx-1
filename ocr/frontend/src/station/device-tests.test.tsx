import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useApp } from "../lib/store";
import { OutputTests } from "../components/DeviceTests";
import DeviceSettings from "../components/DeviceSettings";
import Equipment, { OcrLiveTest } from "../screens/Equipment";

const mocks = vi.hoisted(() => ({ api: vi.fn(), bench: {} as any }));
vi.mock("./shared", async importOriginal => ({ ...(await importOriginal<any>()), api: mocks.api }));
vi.mock("../components/DeviceTests", async importOriginal => ({ ...(await importOriginal<any>()), useBench: () => mocks.bench }));
vi.mock("./StationApp", () => ({ Equipment: () => null }));
beforeEach(() => {
  useApp.setState({ connected: true, snapshot: null });
  mocks.api.mockReset();
  mocks.bench = {
    busy: false, error: "", pulse: vi.fn(), stop: vi.fn(), refresh: vi.fn().mockResolvedValue({}),
    action: async (fn: () => Promise<any>) => fn(),
    state: { connected: true, native_busy: false, rfid_busy: false, error: null,
      run: { id: "led-run", target: "led", remaining_ms: null },
      runs: { led: { id: "led-run", target: "led", remaining_ms: null } },
      io: { motor_requested: false, led_requested: true, km2_on: false },
      cooldown_ms: { motor: 0, led: 1000 }, output_blockers: [], led_blockers: [],
      sensors: [], camera: {}, pins: { motor: 51, led: 52, feedback: 106 },
      setup: { sensor_active_raw: [null, null], rfid_port: "", rfid_window_ms: 500, rfid_protocol_confirmed: true },
    },
  };
});
afterEach(cleanup);

it("keeps motor ON available while LED is on and within its own cooldown", () => {
  render(<MemoryRouter><OutputTests bench={mocks.bench}/></MemoryRouter>);
  const motor = within(screen.getByRole("group", { name: "모터 스위치" }));
  const on = motor.getByRole("button", { name: "켜기" }) as HTMLButtonElement;
  expect(on.disabled).toBe(false);
  fireEvent.click(on);
  expect(mocks.bench.pulse).toHaveBeenCalledWith("motor");
});

it("finds and saves RFID ports independently of camera errors and connected GPIO", async () => {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/bench/camera/devices") throw new Error("카메라 검색 실패");
    if (path === "/bench/ports") return { ports: [{ device: "/dev/ttyUSB0", name: "USB Serial" }] };
    return {};
  });
  render(<MemoryRouter><DeviceSettings/></MemoryRouter>);
  const port = await screen.findByRole("option", { name: "USB Serial (/dev/ttyUSB0)" });
  expect(port).toBeTruthy();
  const select = screen.getByLabelText("직렬 포트") as HTMLSelectElement;
  expect(select.closest("fieldset")?.disabled).toBe(false);
  fireEvent.change(select, { target: { value: "/dev/ttyUSB0" } });
  fireEvent.click(screen.getByRole("button", { name: "RFID 설정 저장" }));
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/bench/rfid/setup", {
    rfid_port: "/dev/ttyUSB0", rfid_window_ms: 500, rfid_protocol_confirmed: true,
  }, "PUT"));
});

it("sends motor attempts to the server instead of silently disabling for setup blockers", () => {
  mocks.bench.state.output_blockers = ["DI3 접촉기 꺼짐을 확인하세요."];
  mocks.bench.state.native_busy = true;
  render(<MemoryRouter><OutputTests bench={mocks.bench}/></MemoryRouter>);
  const on = within(screen.getByRole("group", { name: "모터 스위치" })).getByRole("button", { name: "켜기" }) as HTMLButtonElement;
  expect(on.disabled).toBe(false);
  fireEvent.click(on);
  expect(mocks.bench.pulse).toHaveBeenCalledWith("motor");
});

it("allows RFID reading with both outputs on and displays read errors beside the button", async () => {
  mocks.bench.state.runs.motor = { id: "motor-run", target: "motor", remaining_ms: null };
  mocks.bench.state.io.motor_requested = true;
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/bench/rfid") throw new Error("RFID response timeout: 08");
    return {};
  });
  render(<MemoryRouter><Equipment/></MemoryRouter>);
  const read = screen.getByRole("button", { name: "태그 읽기" }) as HTMLButtonElement;
  expect(read.disabled).toBe(false);
  fireEvent.click(read);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "RFID response timeout: 08");
});

it("reads automatically detected OCR lines with correction", async () => {
  mocks.bench.state.camera = { connected: true };
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/bench/ocr/correction") return { gain: 1, offset: 0, gamma: 1, contrast: 1, clahe: false };
    if (path === "/bench/ocr/read") return {
      reads: [{ barcode: "ABC123", verdict: "match", lines: [{
        text: "ABC123", confidence: 0.94, min_char: 0.9, ms: 8,
        crop_width: 320, crop_height: 100, preview: "data:image/jpeg;base64,dGVzdA==",
        chars: [{ ch: "A", p: 0.95 }],
      }] }], error: null, capture_ms: 1, processing_ms: 8,
      ms_model_load: 0, ms_barcode: 2, ms_ocr: 6,
    };
    return {};
  });
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true, blob: async () => new Blob(["frame"], { type: "image/jpeg" }),
  } as Response);
  const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:frame");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  try {
    render(<OcrLiveTest bench={mocks.bench} locked={false} checkOcr={() => {}} ocr={null} ocrBusy={false}/>);
    const read = screen.getByRole("button", { name: "현재 영상 OCR 검사" }) as HTMLButtonElement;
    await waitFor(() => expect(read.disabled).toBe(false));
    fireEvent.click(read);
    expect(await screen.findByText("ABC123")).toBeTruthy();
    expect(screen.getByAltText("자동 검출한 글자 줄")).toHaveProperty("src", "data:image/jpeg;base64,dGVzdA==");
    expect(mocks.api).toHaveBeenCalledWith("/bench/ocr/read", {
      correction: { gain: 1, offset: 0, gamma: 1, contrast: 1, clahe: false },
    });
  } finally {
    fetchMock.mockRestore(); create.mockRestore(); revoke.mockRestore();
  }
});
