import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import Statistics from "../components/Statistics";
import { useApp } from "../lib/store";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./shared", async original => ({ ...(await original<any>()), api: mocks.api }));
const report = (date: string) => ({ daily: [{date, count: 7, passed: 7, failed: 0,
  adjustments: 0, di1: 7, di2: 7, vision: 0, camera_retries: 0, run_seconds: 60, stopped_seconds: 0}],
  jobs: [], timing_unknown_jobs: 0 });

beforeEach(() => {
  useApp.setState({ brands: [], error: "" });
  mocks.api.mockReset().mockImplementation(async (path: string) => path === "/presets" ? [] : report("첫 조회 결과"));
});
afterEach(cleanup);

it("removes the earlier report and export links when the new filter request fails", async () => {
  render(<Statistics />);
  await screen.findByText("첫 조회 결과");
  mocks.api.mockRejectedValue(new Error("조회 실패"));
  fireEvent.click(screen.getByLabelText("시험 포함"));
  await waitFor(() => expect(screen.queryByText("첫 조회 결과")).toBeNull());
  expect(screen.getByText("CSV 내보내기").hasAttribute("href")).toBe(false);
  await screen.findByText("조회 실패");
  mocks.api.mockResolvedValue(report("재조회 결과"));
  fireEvent.click(screen.getByRole("button", { name: "다시 조회" }));
  await screen.findByText("재조회 결과");
  expect(screen.getByText("CSV 내보내기").getAttribute("href")).toContain("include_tests=true");
});

it("does not show the previous date range or allow CSV for reversed dates", async () => {
  render(<Statistics />);
  await screen.findByText("첫 조회 결과");
  fireEvent.change(screen.getByLabelText("시작일"), { target: { value: "2099-01-01" } });
  expect(screen.queryByText("첫 조회 결과")).toBeNull();
  expect(screen.getByText("CSV 내보내기").hasAttribute("href")).toBe(false);
  expect(screen.getByText("시작일과 종료일을 확인하세요.")).toBeTruthy();
});

it("ignores a failed old request after a newer filter has succeeded", async () => {
  let reject!: (error: Error) => void;
  mocks.api.mockImplementation((path: string) => path === "/presets" ? Promise.resolve([])
    : path.includes("include_tests=true") ? Promise.resolve(report("현재 조회 결과"))
    : new Promise((_, failed) => { reject = failed; }));
  render(<Statistics />);
  await waitFor(() => expect(reject).toBeTypeOf("function"));
  fireEvent.click(screen.getByLabelText("시험 포함"));
  await screen.findByText("현재 조회 결과");
  await act(async () => { reject(new Error("이전 조회 실패")); });
  expect(useApp.getState().error).toBe("");
  expect(screen.queryByText("이전 조회 실패")).toBeNull();
  expect(screen.getByText("현재 조회 결과")).toBeTruthy();
});
