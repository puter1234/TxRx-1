import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import BrandSettings from "../components/BrandSettings";
import WorkPresets, { defaults } from "../components/WorkPresets";
import App from "../App";
import Config from "./Config";
import { useApp } from "../lib/store";
import {
  acceptSnapshot,
  brandView,
  refreshBrands,
  sendCommand,
  startSession,
} from "../lib/station";
import type { Brand, Snapshot } from "./shared";

vi.mock("../lib/ws", () => ({ connectWS: () => () => {} }));
const brand: Brand = {
  id: "brand",
  name: "브랜드 A",
  revision: 1,
  caps: { rfid: true, ocr: true, barcode_tag: true, barcode_poly: true },
  options: [{ key: "size", label: "사이즈", values: ["095", "100"] }],
  decoder: { kind: "lookup", records: { AABB: { size: "095" } } },
  barcode_records: { TAG: { size: "095" } },
  barcode_poly_records: { BAG: { size: "095" } },
  ocr_regions: [],
  note: "",
};
const preset = {
  id: "brand-work",
  name: "기본 설정",
  revision: 1,
  enabled: true,
  kind: "condition",
  brand_id: "brand",
  channels: ["ocr", "rfid"],
  flow: { ...defaults, capture_delay_ms: 250 },
};
const state: Snapshot = {
  boot_id: "workflow",
  revision: 1,
  mode: "HARDWARE",
  session: null,
  busy: false,
  last_result: null,
  stop_fault: null,
  io: {},
  vision: {
    loaded: false,
    local_assets_present: true,
    error: null,
    busy: false,
  },
};
const response = (body: unknown) =>
  ({ ok: true, json: async () => body }) as Response;
beforeEach(() => {
  HTMLElement.prototype.scrollTo = vi.fn();
  useApp.setState({
    snapshot: null,
    connected: true,
    equipment: null,
    pending: [],
    error: "",
    logs: [],
    brands: [brandView(brand)],
  });
  useApp.getState().resetWizard();
  acceptSnapshot(state);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("saves brand checkboxes without dropping decoder, options or either label table", async () => {
  const user = userEvent.setup();
  let current = structuredClone(brand);
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/brands" && options?.method === "POST") {
      current = { ...JSON.parse(options.body as string).brand, revision: 2 };
      return response(current);
    }
    if (path === "/api/brands") return response([current]);
    return response([]);
  });
  vi.stubGlobal("fetch", fetcher);
  function Panel() {
    const rows = useApp((s) => s.brands);
    return (
      <BrandSettings
        brands={rows.map((b) => b.source)}
        locked={false}
        refresh={async () => {
          await refreshBrands();
        }}
      />
    );
  }
  render(
    <MemoryRouter>
      <Panel />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole("checkbox", { name: "브랜드 A OCR" }));
  await waitFor(() =>
    expect(
      screen.getByRole("checkbox", { name: "브랜드 A OCR" }),
    ).toHaveProperty("checked", false),
  );
  expect(current.decoder).toEqual(brand.decoder);
  expect(current.barcode_records).toEqual(brand.barcode_records);
  expect(current.barcode_poly_records).toEqual(brand.barcode_poly_records);
  expect(current.options).toEqual(brand.options);
});

it("keeps product edits while opening the same brand's timing settings and saves its checks once", async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/presets" && options?.method === "POST")
      return response({
        ...JSON.parse(options.body as string).preset,
        revision: 2,
      });
    return response([preset]);
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <MemoryRouter>
      <BrandSettings brands={[brand]} locked={false} refresh={async () => {}} />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole("button", { name: "브랜드 A 상세 설정" }));
  await user.click(screen.getByRole("button", {name: "사이즈 추가"}));
  await user.type(screen.getByLabelText("사이즈 추가값"), "090");
  await user.click(screen.getByRole("button", {name: "사이즈 값 추가"}));
  await user.click(screen.getByRole("tab", { name: "촬영과 센서" }));
  const delay = await screen.findByLabelText("첫 촬영 (ms)");
  await user.clear(delay);
  await user.type(delay, "380");
  await user.click(screen.getByRole("button", { name: "저장" }));
  const call = fetcher.mock.calls.find(
    ([path, options]) => path === "/api/presets" && options?.method === "POST",
  )!;
  const saved = JSON.parse(call[1]!.body as string).preset;
  expect(saved.brand_id).toBe("brand");
  expect(saved.flow.capture_delay_ms).toBe(380);
  expect(saved.channels).toEqual(["rfid", "ocr", "barcode"]);
  expect(saved.barcode_targets).toEqual(["tag", "poly"]);
  await user.click(screen.getByRole("tab", { name: "상품 조건" }));
  expect(screen.getByRole("button", {name: "사이즈 090 수정"})).toBeTruthy();
  expect(screen.queryByText("설정 변경 사유")).toBeNull();
});

it("shows counting settings by function without mixing saved names with action buttons", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      response([
        {
          ...preset,
          id: "simple",
          name: "단순 계수",
          kind: "simple",
          brand_id: "__simple__",
          channels: [],
        },
      ]),
    ),
  );
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <WorkPresets />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "단순 계수 설정" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "새 작업" })).toBeNull();
  expect(screen.queryByRole("button", { name: "카메라 테스트" })).toBeNull();
  await user.click(screen.getByRole("tab", { name: "와펜 계수" }));
  expect(await screen.findByLabelText("계수 방법")).toBeTruthy();
  expect(screen.queryByLabelText("기능")).toBeNull();
});

it("starts the chosen brand with its saved timing and selected checks in one action", async () => {
  const user = userEvent.setup();
  let current = state;
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/brands") return response([brand]);
    if (path === "/api/presets") return response([preset]);
    if (path === "/api/presets/brand-work/start") {
      const body = JSON.parse(options!.body as string);
      current = {
        ...state,
        can_start: true,
        session: {
          id: "s",
          phase: "READY",
          count: 0,
          passed: 0,
          failed: 0,
          adjustments: 0,
          created_at: new Date().toISOString(),
          active_product: null,
          recipe: {
            ...body,
            kind: "condition",
            brand_id: brand.id,
            flow: preset.flow,
          },
          brand,
        },
      } as Snapshot;
      return response(current);
    }
    if (path === "/api/status") return response(current);
    return response({});
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <MemoryRouter initialEntries={["/condition/setup"]}>
      <App />
    </MemoryRouter>,
  );
  await user.click(await screen.findByRole("button", { name: "브랜드 A" }));
  await user.click(screen.getByRole("button", { name: "OCR 문자 인식" }));
  await user.click(screen.getByRole("button", { name: "바코드" }));
  await user.click(screen.getByRole("button", { name: "다음: 수량 설정" }));
  await user.click(screen.getByRole("button", { name: "다음: 조건 설정" }));
  await user.click(screen.getByRole("button", { name: "095" }));
  await user.click(screen.getByRole("button", { name: "검사 시작" }));
  await screen.findByRole("heading", { name: "조건 계수 브랜드 A" });
  const call = fetcher.mock.calls.find(
    ([path]) => path === "/api/presets/brand-work/start",
  )!;
  expect(JSON.parse(call[1]!.body as string)).toMatchObject({
    channels: ["rfid"],
    barcode_targets: [],
    targets: { size: "095" },
  });
  expect(
    fetcher.mock.calls
      .filter(([path]) => path === "/api/commands")
      .map(([, options]) => JSON.parse(options!.body as string).action),
  ).toEqual(["start"]);
});

it("cancels automatic motor start when STOP is pressed during session creation", async () => {
  let complete!: (response: Response) => void;
  const fetcher = vi.fn(
    () =>
      new Promise<Response>((resolve) => {
        complete = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const starting = startSession(
    { mode: "simple", countMode: "continuous" },
    true,
  );
  await sendCommand("stop");
  complete(
    response({
      ...state,
      session: {
        id: "s",
        phase: "READY",
        count: 0,
        recipe: { kind: "simple", channels: [], targets: {} },
        brand,
      },
    }),
  );
  await starting;
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(useApp.getState().snapshot?.session?.phase).toBe("READY");
  expect(useApp.getState().pending).toEqual([]);
});

it("uses the existing RFID field names when adding product options in Korean", async () => {
  const user = userEvent.setup();
  let saved: Brand | undefined;
  vi.stubGlobal("fetch", vi.fn(async (_path: string, options: RequestInit) => {
    saved = JSON.parse(options.body as string).brand;
    return response(saved);
  }));
  render(<Config brands={[]} initialBrand={{...brand, id: "new-fields", options: []}} embedded
    locked={false} refresh={async () => {}} action={async fn => {await fn();}}/>);
  for (const [label, value] of [["품번", "HUTS6C612"], ["색상", "N3"], ["사이즈", "095"]]) {
    await user.type(screen.getByLabelText("새 옵션 이름"), label);
    await user.click(screen.getByRole("button", {name: "옵션 추가"}));
    await user.click(screen.getByRole("button", {name: `${label} 추가`}));
    await user.type(screen.getByLabelText(`${label} 추가값`), value);
    await user.click(screen.getByRole("button", {name: `${label} 값 추가`}));
  }
  await user.click(screen.getByRole("button", {name: "설정 저장"}));
  expect(saved?.options.map(o => o.key)).toEqual(["style", "color", "size"]);
});

it("waits for the initial released-sensor debounce before issuing one start", async () => {
  const ready = {...state, can_start: true, io: {di_raw: [1, 1]}, blockers: [], session: {
    id: "debounce", phase: "READY", count: 0, recipe: {kind: "simple", channels: [], targets: {}}, brand}};
  const fetcher = vi.fn(async (path: string) => response(path === "/api/sessions"
    ? {...ready, can_start: false, blockers: ["DI1과 DI2의 해제 신호를 확인 중입니다."]}
    : path === "/api/status" ? ready : {}));
  vi.stubGlobal("fetch", fetcher);
  await startSession({mode: "simple", countMode: "continuous"}, true);
  expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
    "/api/sessions", "/api/status", "/api/commands", "/api/status",
  ]);
});
