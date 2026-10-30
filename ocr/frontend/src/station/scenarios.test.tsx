import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import BrandSettings from "../components/BrandSettings";
import Statistics from "../components/Statistics";
import WorkPresets from "../components/WorkPresets";
import History from "../screens/History";
import { useApp } from "../lib/store";
import { acceptSnapshot, brandView, reportError } from "../lib/station";
import { api, type Brand, type Session, type Snapshot } from "./shared";

vi.mock("../lib/ws", () => ({ connectWS: () => () => {} }));

const brand: Brand = {
  id: "hazzys", name: "헤지스", revision: 1,
  options: [{ key: "size", label: "사이즈", values: ["095", "100"] }],
  decoder: { kind: "none", records: {} }, ocr_regions: [], barcode_records: {}, note: "",
};
const snapshot: Snapshot = {
  boot_id: "b", revision: 1, mode: "REPLAY", session: null, busy: false, last_result: null, stop_fault: null, io: {},
  vision: { loaded: false, local_assets_present: true, error: null, busy: false },
};
const job = (patch: Partial<Session>): Session => ({
  id: "s", phase: "READY", count: 0, passed: 0, failed: 0, adjustments: 0, created_at: "2026-10-30T01:00:00Z",
  active_product: null, brand, fault: null, mode: "REPLAY",
  recipe: { kind: "simple", brand_id: "__simple__", brand_revision: 1, channels: [], targets: {}, target_count: 40 },
  ...patch,
} as Session);
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const simplePreset = { id: "simple", name: "단순 계수", enabled: true, kind: "simple", brand_id: "__simple__", channels: [], flow: { counter: "sensor" }, revision: 1 };
const wappenPreset = { id: "wappen", name: "와펜 계수", enabled: true, kind: "vision", brand_id: "__simple__", channels: [], flow: { counter: "cvzone" }, revision: 1 };

beforeEach(() => {
  useApp.setState({ snapshot: null, server: null, equipment: null, connected: true, logs: [], brands: [brandView(brand)], error: "", pending: [] });
  acceptSnapshot(snapshot);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps the count of a job stopped by a restart on the home screen and redoes it in one press", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => response(path === "/api/presets" ? [simplePreset] : {})));
  acceptSnapshot({ ...snapshot, session: job({ phase: "ABORTED", fault: "PROCESS_RESTART", count: 7 }) });
  render(<MemoryRouter><App /></MemoryRouter>);
  const card = screen.getByRole("region", { name: "중단된 작업" });
  expect(within(card).getByText("중단됨")).toBeTruthy();
  expect(card.textContent).toContain("7 / 40개");
  fireEvent.click(within(card).getByRole("button", { name: "다시 하기" }));
  expect(await screen.findByText("옷 계수")).toBeTruthy();
});

it("shows why the line cannot start in words, not codes", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({})));
  acceptSnapshot({ ...snapshot, mode: "HARDWARE", can_start: false, session: job({ mode: "HARDWARE" }),
    blockers: ["MOTOR_PERMIT_LOST", "설치 점검 기록 없음", "IO_ACCESS_ERROR: [Errno 16] busy"] } as Snapshot);
  render(<MemoryRouter initialEntries={["/run"]}><App /></MemoryRouter>);
  expect(await screen.findByText("운전 허가 끊김")).toBeTruthy();
  expect(screen.getByText("설치 점검 기록 없음")).toBeTruthy();
  expect(screen.getByText("장비 제어 오류")).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/MOTOR_PERMIT_LOST|IO_ACCESS_ERROR|Errno/);
});

it("marks a brand without product values instead of letting a job start that the server refuses", async () => {
  const brands = [brand, { ...brand, id: "new", name: "새 브랜드", options: [] }];
  vi.stubGlobal("fetch", vi.fn(async (path: string) => response(path === "/api/presets" ? [simplePreset] : path === "/api/brands" ? brands : {})));
  render(<MemoryRouter initialEntries={["/condition"]}><App /></MemoryRouter>);
  const fresh = await screen.findByRole("button", { name: /새 브랜드/ });
  expect(fresh.textContent).toContain("설정 필요");
  expect(fresh).toHaveProperty("disabled", true);
  expect(screen.getByRole("button", { name: "헤지스" })).toHaveProperty("disabled", false);
});

it("shows no message box while the server cannot be reached", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  const failure = await api("/presets").catch((e) => e);
  expect(failure.message).toBe("서버 연결 끊김");
  reportError(failure);
  expect(useApp.getState().error).toBe("");
});

it("shows the choice with its reason when an address asks for wappen in the photo test mode", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => response(path === "/api/presets" ? [simplePreset, wappenPreset] : {})));
  render(<MemoryRouter initialEntries={["/simple?item=wappen"]}><App /></MemoryRouter>);
  const wappen = await screen.findByRole("button", { name: /와펜/ });
  await waitFor(() => expect(wappen.textContent).toContain("사진 시험 모드"));
  expect(wappen).toHaveProperty("disabled", true);
  expect(screen.getByRole("button", { name: "옷" })).toHaveProperty("disabled", false);
  expect(screen.queryByRole("button", { name: "시작" })).toBeNull();
});

it("asks inside the app before deleting a brand", async () => {
  const fetcher = vi.fn(async (_path: string, _options?: RequestInit) => response({ ok: true }));
  vi.stubGlobal("fetch", fetcher);
  const confirmSpy = vi.spyOn(window, "confirm");
  render(<MemoryRouter><BrandSettings brands={[brand]} locked={false} refresh={async () => {}} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "헤지스 삭제" }));
  const dialog = await screen.findByRole("dialog", { name: "헤지스 삭제" });
  fireEvent.click(within(dialog).getByRole("button", { name: "취소" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fetcher.mock.calls.some(([, o]) => o?.method === "DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "헤지스 삭제" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "삭제" }));
  await waitFor(() => expect(fetcher.mock.calls.some(([, o]) => o?.method === "DELETE")).toBe(true));
  expect(confirmSpy).not.toHaveBeenCalled();
});

it("does not create settings by just opening an empty settings list", async () => {
  const fetcher = vi.fn(async (path: string, options?: RequestInit) =>
    response(options?.method === "POST" ? { ...JSON.parse(options.body as string).preset, revision: 1 } : path === "/api/presets" ? [] : {}));
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter><WorkPresets initialKind="vision" /></MemoryRouter>);
  const name = await screen.findByRole("textbox", { name: "설정 이름" });
  await act(async () => { await new Promise((r) => setTimeout(r, 1200)); });
  const posts = () => fetcher.mock.calls.filter(([path, o]) => path === "/api/presets" && o?.method === "POST");
  expect(posts()).toHaveLength(0);
  fireEvent.change(name, { target: { value: "와펜 큰 것" } });
  await waitFor(() => expect(posts()).toHaveLength(1), { timeout: 3000 });
});

it("does not save a second setting with a name already in use", async () => {
  const fetcher = vi.fn(async (path: string, options?: RequestInit) =>
    response(options?.method === "POST" ? { ...JSON.parse(options.body as string).preset, revision: 1 }
      : path === "/api/presets" ? [{ ...simplePreset, id: "c1", name: "기본 설정", kind: "condition", brand_id: "hazzys", channels: ["ocr"] }] : {}));
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter><WorkPresets brandId="hazzys" /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "설정 추가" }));
  fireEvent.change(screen.getByRole("textbox", { name: "설정 이름" }), { target: { value: "기본 설정" } });
  expect(await screen.findByText("같은 이름 있음")).toBeTruthy();
  expect(screen.getByRole("button", { name: "시험 계수" })).toHaveProperty("disabled", true);
  await act(async () => { await new Promise((r) => setTimeout(r, 1200)); });
  const posts = () => fetcher.mock.calls.filter(([path, o]) => path === "/api/presets" && o?.method === "POST");
  expect(posts()).toHaveLength(0);
  fireEvent.change(screen.getByRole("textbox", { name: "설정 이름" }), { target: { value: "기본 설정 큰 것" } });
  await waitFor(() => expect(posts()).toHaveLength(1), { timeout: 3000 });
});

it("names each brand's setting in the statistics and leaves out settings of deleted brands", async () => {
  const condition = (id: string, brand_id: string) => ({ ...simplePreset, id, name: "기본 설정", kind: "condition", brand_id });
  vi.stubGlobal("fetch", vi.fn(async (path: string) => response(path === "/api/presets"
    ? [simplePreset, condition("c1", "hazzys"), condition("c2", "deleted")]
    : { daily: [], jobs: [] })));
  render(<MemoryRouter><Statistics /></MemoryRouter>);
  const works = screen.getByRole("combobox", { name: "통계 작업" });
  await waitFor(() => expect(within(works).getAllByRole("option").map((o) => o.textContent)).toEqual(["전체", "단순 계수", "헤지스 기본 설정"]));
  fireEvent.change(screen.getByRole("combobox", { name: "통계 브랜드" }), { target: { value: "hazzys" } });
  expect(within(works).getAllByRole("option").map((o) => o.textContent)).toEqual(["전체", "헤지스 기본 설정"]);
});

it("marks stopped and test jobs in the history", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ sessions: [
    job({ id: "a", phase: "ABORTED", fault: "PROCESS_RESTART", count: 3 }),
    job({ id: "b", phase: "FINISHED", count: 5, recipe: { ...job({}).recipe, test_run: true } }),
  ] })));
  render(<MemoryRouter><History /></MemoryRouter>);
  expect(await screen.findByText("중단")).toBeTruthy();
  expect(screen.getByText("시험")).toBeTruthy();
});
