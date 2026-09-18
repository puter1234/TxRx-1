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
    lastMessage = Date.now();
  const retryConnect = () => {
    if (alive) retry = setTimeout(connect, 1000);
  };
  const connect = async () => {
    try {
      await api("/auth/local", {});
      if (!alive) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`,
      );
      socket.onmessage = (e) => {
        if (!alive) return;
        try {
          const message = JSON.parse(e.data);
          acceptSnapshot(message.state);
          lastMessage = Date.now();
          useApp.getState().setConnected(true);
          socket?.send(
            JSON.stringify({ type: "heartbeat", event_seq: message.event_seq }),
          );
        } catch {
          socket?.close();
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (alive) {
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
