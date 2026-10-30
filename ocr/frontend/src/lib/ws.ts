import { useApp } from "./store";
import { api } from "../station/shared";
import {
  acceptSnapshot,
  refreshBrands,
  refreshEquipment,
  reportError,
} from "./station";

export function connectWS() {
  let alive = true,
    socket: WebSocket | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined,
    lastMessage = Date.now(),
    boot: string | undefined;
  const retryConnect = () => {
    if (alive) retry = setTimeout(connect, 1000);
  };
  const connect = async () => {
    try {
      await api("/auth/local", {});
      if (!alive) return;
      const current = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`,
      );
      socket = current;
      // A replacement connection has its own deadline. Reusing the expired
      // timestamp closes every retry before its first status can arrive.
      lastMessage = Date.now();
      current.onmessage = (e) => {
        if (!alive || socket !== current) return;
        try {
          const message = JSON.parse(e.data);
          // A restarted server may carry a new build. The open page reconnects by
          // itself and would keep running the old screens; load the new ones.
          const next = message.state?.boot_id;
          if (boot && next && next !== boot) {
            location.reload();
            return;
          }
          boot = next ?? boot;
          acceptSnapshot(message.state);
          lastMessage = Date.now();
          useApp.getState().setConnected(true);
          current.send(
            JSON.stringify({ type: "heartbeat", event_seq: message.event_seq }),
          );
        } catch {
          current.close();
        }
      };
      current.onerror = () => current.close();
      current.onclose = () => {
        if (alive && socket === current) {
          socket = undefined;
          useApp.getState().setConnected(false);
          retryConnect();
        }
      };
      await Promise.all([refreshBrands(), refreshEquipment()]).catch(
        reportError,
      );
    } catch (e) {
      if (alive) {
        reportError(e);
        retryConnect();
      }
    }
  };
  connect();
  const watchdog = setInterval(() => {
    if (Date.now() - lastMessage > 2500) {
      useApp.getState().setConnected(false);
      socket?.close();
    }
  }, 500);
  const equipment = setInterval(() => {
    if (useApp.getState().connected)
      refreshEquipment().catch(() => {
        useApp.getState().setEquipment(null);
        const snapshot = useApp.getState().snapshot;
        if (snapshot) acceptSnapshot(snapshot);
      });
  }, 3000);
  return () => {
    alive = false;
    clearTimeout(retry);
    clearInterval(watchdog);
    clearInterval(equipment);
    socket?.close();
  };
}
