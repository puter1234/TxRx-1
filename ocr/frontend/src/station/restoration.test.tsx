import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import Work from "../screens/Work";
import { useApp } from "../lib/store";
import {
  acceptSnapshot,
  brandView,
  startSession,
  sendCommand,
} from "../lib/station";
import { LoginGate } from "../screens/Settings";
import Run from "../screens/Run";
import type { Brand, Snapshot, Session } from "./shared";
vi.mock("../lib/ws", () => ({ connectWS: () => () => {} }));
const brand: Brand = {
  id: "hazzys",
  name: "헤지스",
  revision: 1,
  options: [
    { key: "style", label: "품번", values: ["HUTS6C612"] },
    { key: "color", label: "색상", values: ["N3", "BK"] },
    { key: "size", label: "사이즈", values: ["095", "100"] },
    { key: "season", label: "시즌", values: ["SS", "FW"] },
  ],
  decoder: {
    kind: "lookup",
    records: {
      AABB: { style: "HUTS6C612", color: "N3", size: "095", season: "SS" },
    },
  },
  ocr_regions: [],
  barcode_records: {},
  note: "",
};
const snapshot: Snapshot = {
  boot_id: "b",
  revision: 1,
  mode: "REPLAY",
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
const session: Session = {
  id: "s",
  phase: "READY",
  count: 0,
  passed: 0,
  failed: 0,
  adjustments: 0,
  created_at: "2026-09-18T01:00:00Z",
  active_product: null,
  recipe: {
    brand_id: "hazzys",
    brand_revision: 1,
    channels: ["rfid"],
    targets: { size: "095" },
    target_count: null,
  },
  brand,
  fault: null,
  mode: "REPLAY",
};
const response = (body: unknown) => ({ ok: true, json: async () => body });
beforeEach(() => {
  useApp.setState({
    snapshot: null,
    server: null,
    equipment: null,
    connected: true,
    logs: [],
    brands: [brandView(brand)],
    error: "",
    pending: [],
  });
  useApp.getState().resetWizard();
  acceptSnapshot(snapshot);
  Element.prototype.scrollTo = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const simplePreset = { id: "simple", name: "단순 계수", enabled: true, kind: "simple", brand_id: "__simple__", channels: [], flow: { counter: "sensor" }, revision: 1 };
const wappenPreset = { id: "wappen", name: "와펜 계수", enabled: true, kind: "vision", brand_id: "__simple__", channels: [], flow: { counter: "cvzone" }, revision: 1 };
const actions = (fetcher: ReturnType<typeof vi.fn>) =>
  fetcher.mock.calls.filter(([path]) => path === "/api/commands").map(([, options]) => JSON.parse(options.body));
const enabled = async (name: string) => {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toHaveProperty("disabled", false));
  return button;
};
describe("worker and admin flows", () => {
  it("allows STOP on the work screen before the start response arrives", async () => {
    const user = userEvent.setup();
    const current = { ...snapshot, mode: "HARDWARE" as const, can_start: true, session };
    acceptSnapshot(current);
    let finish: (v: any) => void = () => {};
    const fetcher = vi.fn((path: string, options?: any): Promise<any> => {
      if (path === "/api/presets") return Promise.resolve(response([]));
      if (path === "/api/status") return Promise.resolve(response(current));
      if (path === "/api/commands" && JSON.parse(options.body).action === "start")
        return new Promise(resolve => { finish = resolve; });
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter><Work /></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: "운전 시작" }));
    try {
      expect(screen.getByRole("button", { name: "정지" })).toHaveProperty("disabled", false);
      await user.click(screen.getByRole("button", { name: "정지" }));
      expect(fetcher.mock.calls.filter(([p]) => p === "/api/commands")
        .map(([, args]) => JSON.parse(args.body).action)).toEqual(["start", "stop"]);
      // The earlier start is still pending even though STOP finished first.
      expect(screen.getByRole("button", { name: "운전 시작" })).toHaveProperty("disabled", true);
    } finally {
      finish(response({}));
      await waitFor(() => expect(useApp.getState().pending).toHaveLength(0));
    }
  });
  it("starts clothes counting from home with a quantity and no password or help popups", async () => {
    const user = userEvent.setup();
    let current: Snapshot = { ...snapshot, can_start: true };
    const fetcher = vi.fn(async (path: string, options?: any) => {
      if (path === "/api/presets") return response([simplePreset, wappenPreset]);
      if (path === "/api/presets/simple/start") {
        const body = JSON.parse(options.body);
        current = { ...snapshot, can_start: true, session: { ...session, recipe: { ...session.recipe, kind: "simple", channels: [], targets: {}, target_count: body.target_count } } };
        return response(current);
      }
      if (path === "/api/status") return response(current);
      return response({});
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter><App /></MemoryRouter>);
    for (const name of ["단순 계수", "조건 계수", "작업 기록", "설정"]) expect(screen.getByRole("button", { name })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "단순 계수" }));
    expect(await enabled("와펜")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "옷" }));
    await user.click(screen.getByRole("button", { name: "40" }));
    expect(screen.queryByRole("button", { name: "도움말" })).toBeNull();
    expect(screen.queryByLabelText("비밀번호")).toBeNull();
    expect(screen.queryByLabelText("계수 방법")).toBeNull();
    await user.click(await enabled("시작"));
    expect((await screen.findByLabelText("현재 수량")).textContent).toBe("0");
    const call = fetcher.mock.calls.find(([path]) => path === "/api/presets/simple/start")!;
    expect(JSON.parse(call[1].body)).toMatchObject({ target_count: 40, targets: {} });
    expect(actions(fetcher).map((c) => c.action)).toEqual(["start"]);
  });
  it("turns the camera on from the wappen screen in one tap", async () => {
    const user = userEvent.setup();
    acceptSnapshot({ ...snapshot, mode: "HARDWARE" });
    useApp.setState({ equipment: { camera: { connected: false } } as any });
    const fetcher = vi.fn(async (path: string) => {
      if (path === "/api/presets") return response([simplePreset, wappenPreset]);
      if (path === "/api/equipment") return response({ camera: { connected: true } });
      if (path === "/api/camera/frame") return { ok: false };
      return response({});
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter initialEntries={["/simple"]}><App /></MemoryRouter>);
    await user.click(await enabled("와펜"));
    expect(screen.getByText("카메라 꺼짐")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "카메라 켜기" }));
    expect(await screen.findByText("영상 받는 중")).toBeTruthy();
    expect(fetcher.mock.calls.filter(([path]) => path === "/api/bench/camera/connect")).toHaveLength(1);
    expect(screen.queryByLabelText("비밀번호")).toBeNull();
  });
  it("asks one condition per screen and starts with every option of the brand", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn(async (path: string, options?: any) => {
      if (path === "/api/brands") return response([brand]);
      if (path === "/api/presets") return response([]);
      if (path === "/api/status") return response({ ...snapshot, session: { ...session, phase: "FEEDING" } });
      if (path === "/api/sessions") return response({ ...snapshot, session: { ...session, recipe: JSON.parse(options.body) } });
      return response({});
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter initialEntries={["/condition"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "헤지스" }));
    for (const [title, value] of [["품번", "HUTS6C612"], ["색상", "N3"], ["사이즈", "095"]]) {
      expect(screen.getByRole("heading", { name: title })).toBeTruthy();
      await user.click(screen.getByRole("button", { name: value }));
    }
    expect(screen.getByRole("heading", { name: "시즌" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "시작" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "SS" }));
    await user.click(screen.getByRole("button", { name: "문자" }));
    await user.click(await enabled("시작"));
    expect(await screen.findByRole("heading", { name: "헤지스 조건 계수" })).toBeTruthy();
    const creation = fetcher.mock.calls.find(([path]) => path === "/api/sessions")!;
    expect(JSON.parse(creation[1].body).channels).toEqual(["rfid"]);
    expect(JSON.parse(creation[1].body).targets).toEqual({ style: "HUTS6C612", color: "N3", size: "095", season: "SS" });
    expect(actions(fetcher).map((c) => c.action)).toEqual(["start"]);
  });
  it("goes back one condition at a time and changes a chosen value from its chip", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async (path: string) => response(path === "/api/brands" ? [brand] : [])));
    render(<MemoryRouter initialEntries={["/condition"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "헤지스" }));
    for (const value of ["HUTS6C612", "N3", "095", "SS"]) await user.click(screen.getByRole("button", { name: value }));
    expect(screen.getByRole("heading", { name: "수량" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "이전" }));
    expect(screen.getByRole("heading", { name: "시즌" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "이전" }));
    expect(screen.getByRole("heading", { name: "사이즈" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "100" }));
    // After going back, the following options are offered again in order.
    expect(screen.getByRole("heading", { name: "시즌" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "SS" }));
    await user.click(screen.getByRole("button", { name: "색상 N3 다시 고르기" }));
    await user.click(screen.getByRole("button", { name: "BK" }));
    // A value changed from its chip returns straight to the last step.
    expect(screen.getByRole("heading", { name: "수량" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "색상 BK 다시 고르기" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "사이즈 100 다시 고르기" })).toBeTruthy();
  });
  it("keeps STOP available during a pending start and never counts twice on correction", async () => {
    const user = userEvent.setup();
    acceptSnapshot({ ...snapshot, can_start: true, session });
    let finish: (v: any) => void = () => {};
    const fetcher = vi.fn((path: string, options?: any): Promise<any> => {
      if (path === "/api/commands" && JSON.parse(options.body).action === "start")
        return new Promise((resolve) => {
          finish = resolve;
        });
      return Promise.resolve(response(path === "/api/status" ? { ...snapshot, can_start: true, session } : {}));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter><Run /></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: "시작" }));
    expect(screen.getByRole("button", { name: "시작" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "멈춤" })).toHaveProperty("disabled", false);
    await user.click(screen.getByRole("button", { name: "멈춤" }));
    finish(response({}));
    await waitFor(() => expect(useApp.getState().pending).toHaveLength(0));
    expect(actions(fetcher).map((c) => c.action)).toEqual(["start", "stop"]);
    await user.click(await enabled("1개 더하기"));
    await user.dblClick(screen.getByRole("button", { name: "놓친 제품" }));
    const corrections = fetcher.mock.calls.filter(([path]) => path === "/api/adjustments");
    expect(corrections).toHaveLength(1);
    expect(JSON.parse(corrections[0][1].body)).toMatchObject({ delta: 1, reason: "놓친 제품" });
  });
  it("shows target and read values on a mismatch and recovers with one command, never resuming", async () => {
    const user = userEvent.setup();
    acceptSnapshot({
      ...snapshot,
      can_start: false,
      last_result: { failures: [{ code: "TARGET_MISMATCH", field: "size", expected: "095", actual: "100" }] } as any,
      session: { ...session, phase: "HOLD", active_product: "p1", fault: "TARGET_MISMATCH" },
    });
    const fetcher = vi.fn(async (path: string) => response(path === "/api/status" ? { ...snapshot, session } : {}));
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter><Run /></MemoryRouter>);
    const alert = screen.getByRole("alert");
    for (const text of ["사이즈", "095", "100"]) expect(alert.textContent).toContain(text);
    expect(screen.getByRole("button", { name: "시작" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "제품 뺐음" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "다시 검사" }));
    await waitFor(() => expect(actions(fetcher)).toHaveLength(1));
    expect(actions(fetcher)[0]).toMatchObject({ action: "reset" });
    expect(actions(fetcher)[0].reason.length).toBeGreaterThanOrEqual(3);
  });
  it("keeps a reached target on screen and repeats the job with the same choices", async () => {
    const user = userEvent.setup();
    const targets = { style: "HUTS6C612", color: "N3", size: "095", season: "SS" };
    acceptSnapshot({ ...snapshot, session: { ...session, phase: "DONE", count: 40, recipe: { ...session.recipe, targets, target_count: 40 } } });
    vi.stubGlobal("fetch", vi.fn(async (path: string) => response(path === "/api/brands" ? [brand] : [])));
    render(<MemoryRouter initialEntries={["/run"]}><App /></MemoryRouter>);
    expect(screen.getByText("목표 완료")).toBeTruthy();
    expect(screen.getByLabelText("현재 수량").textContent).toBe("40");
    expect(screen.queryByRole("button", { name: "1개 더하기" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "다시 하기" }));
    expect(await screen.findByRole("heading", { name: "수량" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "40" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "사이즈 095 다시 고르기" })).toBeTruthy();
    expect(await enabled("시작")).toBeTruthy();
  });
  it("shows inspection evidence in the history and repeats a job with its saved targets", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn(async (path: string) => {
      if (path === "/api/presets") return response([]);
      if (path === "/api/history?offset=0") return response({ sessions: [session] });
      if (path === "/api/history?session_id=s&offset=0")
        return response({
          inspections: [
            {
              id: "r",
              product_id: "p1",
              attempt: 1,
              status: "FAIL",
              mode: "REPLAY",
              created_at: session.created_at,
              observations: { rfid: { size: "100" } },
              failures: [{ code: "TARGET_MISMATCH", expected: "095", actual: "100" }],
              evidence: { url: "/api/evidence/r" },
            },
          ],
        });
      if (path === "/api/brands") return response([brand]);
      return response({});
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter initialEntries={["/history"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "검사 내역" }));
    expect(await screen.findByAltText("검사 사진")).toHaveProperty("src", expect.stringContaining("/api/evidence/r"));
    expect(screen.getByText("목표와 불일치")).toBeTruthy();
    expect(screen.getByText("사이즈 100")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "다시 하기" }));
    // Only the size was saved, so the remaining options are asked in order.
    expect(await screen.findByRole("heading", { name: "품번" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "사이즈 095 다시 고르기" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "시작" })).toBeNull();
  });
  it("unlocks settings with only a password and no user creation", async () => {
    const user = userEvent.setup(),
      ok = vi.fn();
    const fetcher = vi.fn(async (path: string) =>
      response(path === "/api/auth" ? { configured: true } : { ok: true }),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<LoginGate onOk={ok} />);
    await user.type(
      await screen.findByLabelText("비밀번호"),
      "existing-password",
    );
    await user.click(screen.getByRole("button", { name: "확인" }));
    await waitFor(() => expect(ok).toHaveBeenCalledOnce());
    expect(screen.queryByLabelText("사용자 ID")).toBeNull();
    const call = fetcher.mock.calls.find(
      ([path]) => path === "/api/auth/login",
    ) as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({
      password: "existing-password",
    });
  });
  it("guards session creation against a double tap and keeps the uncertain result visible", async () => {
    let finish: (v: any) => void = () => {};
    const fetcher = vi.fn(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    const first = startSession({ mode: "simple", countMode: "continuous" });
    await startSession({ mode: "simple", countMode: "continuous" });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(useApp.getState().pending).toContain("create");
    finish(
      response({
        ...snapshot,
        session: { ...session, recipe: { ...session.recipe, kind: "simple" } },
      }),
    );
    await first;
    expect(useApp.getState().snapshot?.session?.id).toBe("s");
    expect(useApp.getState().pending).not.toContain("create");
  });
  it("reads back a committed correction when the response is lost instead of sending it twice", async () => {
    acceptSnapshot({ ...snapshot, session });
    const fetcher = vi.fn(async (path: string) => {
      if (path === "/api/adjustments") throw new TypeError("connection lost");
      if (path.startsWith("/api/commands/"))
        return response({ found: true, result: { count: 1 } });
      if (path === "/api/status")
        return response({
          ...snapshot,
          revision: 2,
          session: { ...session, count: 1 },
        });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetcher);
    await sendCommand("adjust", "실제 수량 확인", 1);
    expect(useApp.getState().snapshot?.session?.count).toBe(1);
    expect(
      fetcher.mock.calls.filter(([path]) => path === "/api/adjustments"),
    ).toHaveLength(1);
  });
  it("saves the pass-photo choice only after the password gate", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/auth") return response({ configured: true });
      if (path === "/api/settings") return response({ save_photos: options?.method !== "PUT" });
      if (path === "/api/brands") return response([brand]);
      return response({ ok: true });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter initialEntries={["/settings?section=general"]}><App /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "저장 안 함" })).toBeNull();
    await user.type(await screen.findByLabelText("비밀번호"), "existing-password");
    await user.click(screen.getByRole("button", { name: "확인" }));
    const keep = await screen.findByRole("button", { name: "저장" });
    await waitFor(() => expect(keep.getAttribute("aria-pressed")).toBe("true"));
    await user.click(screen.getByRole("button", { name: "저장 안 함" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "저장 안 함" }).getAttribute("aria-pressed")).toBe("true"));
    expect(
      fetcher.mock.calls.some(([path, options]) => path === "/api/settings" && options?.method === "PUT" && options.body === '{"save_photos":false}'),
    ).toBe(true);
  });
});
