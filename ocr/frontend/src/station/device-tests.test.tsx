import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useApp } from "../lib/store";
import { OutputTests } from "../components/DeviceTests";
import DeviceSettings from "../components/DeviceSettings";
import Equipment from "../screens/Equipment";

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
