import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { CameraView } from "../components/DeviceTests";
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
it("retains the last frame during a failed preview, retries, and clears it on actual disconnect", async () => {
  vi.useFakeTimers();
  const NativeURL = URL;
  let seq = 0;
  vi.stubGlobal("URL", class extends NativeURL {
    static createObjectURL() { return `blob:frame-${++seq}`; }
    static revokeObjectURL() {}
  });
  const frame = {ok: true, blob: async () => new Blob(["frame"]), headers: {get: (key: string) => key === "X-Camera-Fps" ? "30" : "1"}};
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(frame).mockResolvedValueOnce({ok: false}).mockResolvedValue(frame));
  let view: ReturnType<typeof render>;
  await act(async () => { view = render(<CameraView connected/>); });
  expect(screen.getByAltText("카메라 시험 영상").getAttribute("src")).toBe("blob:frame-1");
  await act(async () => { await vi.advanceTimersByTimeAsync(34); });
  expect(screen.getByText("영상 갱신 지연")).toBeTruthy();
  expect(screen.getByAltText("카메라 시험 영상").getAttribute("src")).toBe("blob:frame-1");
  expect(screen.queryByText("영상 연결 끊김")).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(250); });
  expect(screen.queryByText("영상 갱신 지연")).toBeNull();
  expect(screen.getByAltText("카메라 시험 영상").getAttribute("src")).toBe("blob:frame-2");
  await act(async () => { view.rerender(<CameraView connected={false}/>); });
  expect(screen.queryByAltText("카메라 시험 영상")).toBeNull();
  expect(screen.getByText("카메라 미연결")).toBeTruthy();
});

it.each([3, 30, 60])("paces preview requests at %i FPS instead of a fixed two FPS", async fps => {
  vi.useFakeTimers({toFake: ["setTimeout", "clearTimeout", "performance"]});
  const NativeURL = URL;
  vi.stubGlobal("URL", class extends NativeURL {
    static createObjectURL() { return "blob:preview"; }
    static revokeObjectURL() {}
  });
  const fetchFrame = vi.fn().mockResolvedValue({ok: true, blob: async () => new Blob(["frame"]),
    headers: {get: (name: string) => name === "X-Camera-Fps" ? String(fps) : "1"}});
  vi.stubGlobal("fetch", fetchFrame);
  await act(async () => { render(<CameraView connected/>); });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(fetchFrame.mock.calls.length).toBeGreaterThanOrEqual(fps);
  expect(fetchFrame.mock.calls.length).toBeLessThanOrEqual(fps + 3);
});

it("retries a preview request that never responds", async () => {
  vi.useFakeTimers();
  const fetchFrame = vi.fn((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")));
  }));
  vi.stubGlobal("fetch", fetchFrame);
  await act(async () => { render(<CameraView connected/>); });
  await act(async () => { await vi.advanceTimersByTimeAsync(1800); });
  expect(fetchFrame).toHaveBeenCalledTimes(2);
});
