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
  const frame = {ok: true, blob: async () => new Blob(["frame"]), headers: {get: () => "1"}};
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(frame).mockResolvedValueOnce({ok: false}).mockResolvedValue(frame));
  let view: ReturnType<typeof render>;
  await act(async () => { view = render(<CameraView connected/>); });
  expect(screen.getByAltText("카메라 시험 영상").getAttribute("src")).toBe("blob:frame-1");
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(screen.getByText("영상 갱신 지연")).toBeTruthy();
  expect(screen.getByAltText("카메라 시험 영상").getAttribute("src")).toBe("blob:frame-1");
  expect(screen.queryByText("영상 연결 끊김")).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(screen.queryByText("영상 갱신 지연")).toBeNull();
  expect(screen.getByAltText("카메라 시험 영상").getAttribute("src")).toBe("blob:frame-2");
  await act(async () => { view.rerender(<CameraView connected={false}/>); });
  expect(screen.queryByAltText("카메라 시험 영상")).toBeNull();
  expect(screen.getByText("카메라 미연결")).toBeTruthy();
});
