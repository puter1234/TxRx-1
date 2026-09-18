import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { useApp } from "../lib/store";
import {
  acceptSnapshot,
  brandView,
  startSession,
  sendCommand,
} from "../lib/station";
import { LoginGate } from "../screens/Settings";
import ControlBar from "../components/ControlBar";
import Help from "../components/Help";
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
describe("restored original screens", () => {
  it("opens the original two-choice main page without a login or account", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "계수 방식을 선택하세요" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "단순 계수 시작" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "조건 설정" })).toBeTruthy();
    expect(screen.queryByLabelText("사용자 ID")).toBeNull();
    expect(screen.queryByText(/admin/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "단순 계수 시작" }));
    expect(screen.getByRole("heading", { name: "단순 계수" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "수량 초기화" })).toBeTruthy();
  });
  it("preserves all three setup steps and submits dynamic options with barcode optional", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn(async (path: string, options?: any) => {
      if (path === "/api/brands") return response([brand]);
      if (path === "/api/sessions")
        return response({
          ...snapshot,
          session: { ...session, recipe: JSON.parse(options.body) },
        });
      return response({});
    });
    vi.stubGlobal("fetch", fetcher);
    render(
      <MemoryRouter initialEntries={["/condition/setup"]}>
        <App />
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole("button", { name: "헤지스" }));
    await user.click(screen.getByRole("button", { name: "OCR 문자 인식" }));
    await user.click(screen.getByRole("button", { name: "다음: 수량 설정" }));
    await user.click(screen.getByRole("button", { name: "다음: 조건 설정" }));
    await user.click(screen.getByRole("button", { name: "HUTS6C612" }));
    await user.click(screen.getByRole("button", { name: "N3" }));
    await user.click(screen.getByRole("button", { name: "095" }));
    const start = screen.getByRole("button", {
      name: "검사 화면 열기",
    }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "SS" }));
    await user.click(start);
    const creation = fetcher.mock.calls.find(
      ([path]) => path === "/api/sessions",
    )!;
    expect(JSON.parse(creation[1].body).channels).toEqual(["rfid"]);
    expect(JSON.parse(creation[1].body).targets).toEqual({
      style: "HUTS6C612",
      color: "N3",
      size: "095",
      season: "SS",
    });
    expect(
      await screen.findByRole("heading", { name: "조건 계수 헤지스" }),
    ).toBeTruthy();
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
  it("keeps STOP available during a pending start and never counts twice on correction", async () => {
    const user = userEvent.setup();
    acceptSnapshot({ ...snapshot, can_start: true, session });
    let finish: (v: any) => void = () => {};
    const fetcher = vi.fn((path: string, options?: any): Promise<any> => {
      if (
        path === "/api/commands" &&
        JSON.parse(options.body).action === "start"
      )
        return new Promise((resolve) => {
          finish = resolve;
        });
      return Promise.resolve(
        response(
          path === "/api/status"
            ? { ...snapshot, can_start: true, session }
            : {},
        ),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(
      <MemoryRouter>
        <ControlBar mode="condition" />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "검사 시작" }));
    expect(
      (screen.getByRole("button", { name: "검사 시작" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "정지" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: "정지" }));
    finish(response({}));
    await waitFor(() => expect(useApp.getState().pending).toHaveLength(0));
    expect(
      fetcher.mock.calls
        .filter(([p]) => p === "/api/commands")
        .map(([, args]) => JSON.parse(args.body).action),
    ).toEqual(["start", "stop"]);
    await user.click(screen.getByRole("button", { name: "수동 1개 더하기" }));
    await user.type(screen.getByLabelText("변경 사유"), "실제 수량 확인");
    await user.dblClick(screen.getByRole("button", { name: "확인" }));
    expect(
      fetcher.mock.calls.filter(([p]) => p === "/api/adjustments"),
    ).toHaveLength(1);
  });
  it("recovers a mismatch only after a reason and never resumes automatically", async () => {
    const user = userEvent.setup();
    acceptSnapshot({
      ...snapshot,
      can_start: false,
      session: {
        ...session,
        phase: "HOLD",
        active_product: "p1",
        fault: "TARGET_MISMATCH",
      },
    });
    const fetcher = vi.fn(async (path: string) =>
      response(path === "/api/status" ? { ...snapshot, session } : {}),
    );
    vi.stubGlobal("fetch", fetcher);
    render(
      <MemoryRouter>
        <ControlBar mode="condition" />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "조치 확인" }));
    expect(
      (screen.getByRole("button", { name: "재검사 준비" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await user.type(screen.getByLabelText("확인한 내용"), "제품 확인 완료");
    await user.click(screen.getByRole("button", { name: "재검사 준비" }));
    const calls = (
      fetcher.mock.calls as unknown as [string, RequestInit][]
    ).filter(([p]) => p === "/api/commands");
    expect(calls).toHaveLength(1);
    expect(JSON.parse(calls[0][1].body as string).action).toBe("reset");
  });
  it("opens help by touch or hover without persistent explanatory paragraphs", async () => {
    const user = userEvent.setup();
    render(<Help text="필요할 때만 보는 설명" />);
    expect(screen.queryByRole("tooltip")).toBeNull();
    await user.click(screen.getByRole("button", { name: "도움말" }));
    expect(screen.getByRole("tooltip").textContent).toBe(
      "필요할 때만 보는 설명",
    );
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
  it("keeps inspection evidence and saved target loading in the original history table", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn(async (path: string) => {
      if (path === "/api/history?offset=0")
        return response({ sessions: [session] });
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
              failures: [
                { code: "TARGET_MISMATCH", expected: "095", actual: "100" },
              ],
              evidence: { url: "/api/evidence/r" },
            },
          ],
        });
      if (path === "/api/brands") return response([brand]);
      return response({});
    });
    vi.stubGlobal("fetch", fetcher);
    render(
      <MemoryRouter initialEntries={["/history"]}>
        <App />
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole("button", { name: "검사 기록" }));
    expect(await screen.findByAltText("검사 사진")).toHaveProperty(
      "src",
      expect.stringContaining("/api/evidence/r"),
    );
    expect(screen.getByText("목표와 불일치")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "불러오기" }));
    expect(
      (await screen.findByRole("button", { name: "095" })).getAttribute(
        "aria-pressed",
      ),
    ).toBe("true");
    expect(
      (
        screen.getByRole("button", {
          name: "검사 화면 열기",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
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
  it("saves the original pass-photo switch only after the password gate", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/auth") return response({ configured: true });
      if (path === "/api/settings")
        return response({
          save_photos: options?.method === "PUT" ? false : true,
        });
      return response({ ok: true });
    });
    vi.stubGlobal("fetch", fetcher);
    render(
      <MemoryRouter initialEntries={["/settings"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("switch")).toBeNull();
    await user.type(
      await screen.findByLabelText("비밀번호"),
      "existing-password",
    );
    await user.click(screen.getByRole("button", { name: "확인" }));
    const toggle = await screen.findByRole("switch", {
      name: "통과 사진 저장",
    });
    await waitFor(() =>
      expect(toggle.getAttribute("aria-checked")).toBe("true"),
    );
    await user.click(toggle);
    await waitFor(() =>
      expect(toggle.getAttribute("aria-checked")).toBe("false"),
    );
    expect(
      fetcher.mock.calls.some(
        ([path, options]) =>
          path === "/api/settings" &&
          options?.method === "PUT" &&
          options.body === '{"save_photos":false}',
      ),
    ).toBe(true);
  });
});
