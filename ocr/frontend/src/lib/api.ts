import { api as request } from "../station/shared";
import {
  refreshBrands,
  startSession,
  sendCommand,
  jobView,
  reportError,
} from "./station";
import type { Session } from "../station/shared";
export async function api<T = any>(
  path: string,
  body?: any,
  method?: string,
): Promise<T> {
  try {
    if (path === "/api/brands" && body === undefined)
      return (await refreshBrands()) as T;
    if (path === "/api/session/start") {
      await startSession(body);
      return { ok: true } as T;
    }
    if (path.startsWith("/api/jobs")) {
      const offset =
        new URLSearchParams(path.split("?")[1]).get("offset") || "0";
      const page = await request<{ sessions: Session[] }>(
        "/history?offset=" + offset,
      );
      return page.sessions.map(jobView) as T;
    }
    if (path === "/api/login") return await request("/auth/login", body);
    if (path === "/api/password") return await request("/auth/password", body);
    if (path.startsWith("/api/logs")) {
      const day = new URLSearchParams(path.split("?")[1]).get("date");
      const result = await request("/events");
      return {
        lines: result.events
          .filter(
            (v: any) =>
              !day ||
              new Date(v.created_at).toLocaleDateString("sv-SE") === day,
          )
          .map(
            (v: any) =>
              new Date(v.created_at).toLocaleTimeString("ko-KR") + " " + v.kind,
          ),
      } as T;
    }
    const actions: Record<string, string> = {
      pause: "stop",
      resume: "start",
      emergency: "stop",
      "emergency-release": "reset",
    };
    const action = actions[path.replace("/api/session/", "")];
    if (action) return (await sendCommand(action, body?.reason)) as T;
    return await request(path.replace(/^\/api/, ""), body, method);
  } catch (error) {
    reportError(error);
    throw error;
  }
}
