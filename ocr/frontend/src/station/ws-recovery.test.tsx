import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { connectWS } from "../lib/ws";
import { useApp } from "../lib/store";

vi.mock("./shared", () => ({ api: vi.fn().mockResolvedValue({}) }));
vi.mock("../lib/station", () => ({
  acceptSnapshot: vi.fn(), refreshBrands: vi.fn().mockResolvedValue(undefined),
  refreshEquipment: vi.fn().mockResolvedValue(undefined), reportError: vi.fn(),
}));

class Socket {
  static instances: Socket[] = [];
  onopen?: () => void;
  onmessage?: (e: { data: string }) => void;
  onerror?: () => void;
  onclose?: () => void;
  readyState = 0;
  send = vi.fn();
  close = vi.fn(() => {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.();
  });
  constructor() { Socket.instances.push(this); }
  receive() { this.onmessage?.({ data: JSON.stringify({ state: {}, event_seq: 1 }) }); }
}
let dispose: (() => void) | undefined;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  Socket.instances = [];
  useApp.setState({ connected: false });
});
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals(); vi.useRealTimers(); });

it("gives a reconnect its own response deadline after the previous socket timed out", async () => {
  dispose = connectWS();
  await vi.advanceTimersByTimeAsync(0);
  const first = Socket.instances[0];
  first.receive();
  expect(useApp.getState().connected).toBe(true);
  await vi.advanceTimersByTimeAsync(3000);
  expect(first.close).toHaveBeenCalled();
  expect(useApp.getState().connected).toBe(false);
  await vi.advanceTimersByTimeAsync(1000);
  const second = Socket.instances[1];
  expect(second).toBeDefined();
  // A valid first response takes 800 ms, still within the 2.5 s deadline.
  await vi.advanceTimersByTimeAsync(800);
  expect(second.close).not.toHaveBeenCalled();
  second.receive();
  expect(useApp.getState().connected).toBe(true);
});

it("still disconnects a new socket that never supplies a response", async () => {
  dispose = connectWS();
  await vi.advanceTimersByTimeAsync(3000);
  expect(Socket.instances[0].close).toHaveBeenCalled();
  expect(useApp.getState().connected).toBe(false);
});

it("ignores late events from the disconnected socket", async () => {
  dispose = connectWS();
  await vi.advanceTimersByTimeAsync(0);
  const first = Socket.instances[0];
  first.close();
  await vi.advanceTimersByTimeAsync(1000);
  const second = Socket.instances[1];
  first.receive();
  expect(useApp.getState().connected).toBe(false);
  first.onerror?.();
  expect(second.close).not.toHaveBeenCalled();
  second.receive();
  expect(useApp.getState().connected).toBe(true);
  first.onclose?.();
  expect(useApp.getState().connected).toBe(true);
  dispose(); dispose = undefined;
  await vi.advanceTimersByTimeAsync(5000);
  expect(Socket.instances).toHaveLength(2);
});

it("loads the new screens when the server comes back after a restart", async () => {
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  dispose = connectWS();
  await vi.advanceTimersByTimeAsync(0);
  const first = Socket.instances[0];
  const say = (socket: Socket, boot: string) => socket.onmessage?.({ data: JSON.stringify({ state: { boot_id: boot }, event_seq: 1 }) });
  say(first, "boot-1");
  say(first, "boot-1");
  expect(reload).not.toHaveBeenCalled();
  first.close();
  await vi.advanceTimersByTimeAsync(1000);
  say(Socket.instances[1], "boot-2");
  expect(reload).toHaveBeenCalledTimes(1);
});
