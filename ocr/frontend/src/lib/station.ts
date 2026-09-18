import { api as request, uuid, PHASE, ERR } from "../station/shared";
import type {
  Snapshot,
  Brand as StationBrand,
  Session,
  Recipe,
} from "../station/shared";
import type { Brand, ServerState, Job, SessionConfig } from "./types";
import { useApp } from "./store";

export const ended = (s: Session | null | undefined) =>
  !s || ["FINISHED", "DONE", "ABORTED"].includes(s.phase);
export const brandView = (b: StationBrand): Brand => ({
  ...b,
  source: b,
  caps: {
    ocr: true,
    rfid: b.decoder.kind !== "none",
    barcode_tag: Object.keys(b.barcode_records).length > 0,
    barcode_poly: false,
  },
});
export const configView = (s: Session): SessionConfig => ({
  mode: s.recipe.kind === "simple" ? "simple" : "condition",
  brandId: s.recipe.brand_id,
  brandName: s.brand.name,
  checks: {
    ocr: s.recipe.channels.includes("ocr"),
    rfid: s.recipe.channels.includes("rfid"),
    barcode_tag: s.recipe.channels.includes("barcode"),
    barcode_poly: false,
  },
  countMode: s.recipe.target_count ? "target" : "continuous",
  target: s.recipe.target_count,
  item: {
    sku: s.recipe.targets.style || "",
    color: s.recipe.targets.color || "",
    size: s.recipe.targets.size || "",
  },
  targets: s.recipe.targets,
});
export const jobView = (s: Session): Job => ({
  id: s.id,
  date: new Date(s.created_at).toLocaleDateString("sv-SE"),
  time: new Date(s.created_at).toLocaleTimeString("ko-KR"),
  mode: configView(s).mode,
  count: s.count,
  config: configView(s),
  dir: "검사 기록",
});
export function acceptSnapshot(next: Snapshot) {
  const store = useApp.getState(),
    prior = store.snapshot;
  if (prior && prior.boot_id === next.boot_id && prior.revision > next.revision)
    return;
  const s = next.session,
    io = next.io,
    equip = store.equipment;
  const first = next.last_result?.failures[0];
  const devices: ServerState["devices"] = {
    camera: equip?.camera?.connected === true ? "ok" : "off",
    sensor: io.connected === true && Array.isArray(io.di_raw) ? "ok" : "off",
    rfid: io.rfid_ready === true ? "ok" : io.rfid_error ? "fault" : "off",
    conveyor:
      io.connected !== true
        ? "off"
        : io.fault
          ? "fault"
          : io.km2_on === true
            ? "busy"
            : io.km2_on === false
              ? "idle"
              : "off",
  };
  store.setSnapshot(next);
  store.setServer({
    devices,
    pipeline: {
      infeed: "idle",
      sensor: "idle",
      camera: "idle",
      rfid: "idle",
      conveyor: io.km2_on === true ? "active" : "idle",
      outfeed: "idle",
    },
    session: {
      mode: s ? configView(s).mode : null,
      status:
        !s || ["FINISHED", "ABORTED"].includes(s.phase)
          ? "idle"
          : s.phase === "DONE"
            ? "done"
            : s.phase === "HOLD"
              ? "mismatch"
              : s.phase === "FAULT"
                ? "emergency"
                : s.phase === "PAUSED"
                  ? "paused"
                  : [
                        "FEEDING",
                        "INSPECTING",
                        "STOPPING",
                        "EJECTING",
                        "RETRY_PENDING",
                      ].includes(s.phase)
                    ? "running"
                    : "idle",
      count: s?.count || 0,
      startedAt: s?.created_at || null,
      lastPassAt:
        next.last_result?.status === "PASS"
          ? new Date(next.last_result.created_at).toLocaleTimeString("ko-KR")
          : null,
      config: s ? configView(s) : null,
      mismatch: first
        ? {
            field:
              s?.brand.options.find((o) => o.key === first.field)?.label ||
              first.field ||
              "",
            expected: first.expected || "",
            actual: first.actual || "미판독",
          }
        : null,
    },
    settings: {
      save_photos: true,
      threshold: 0,
      data_dir: equip?.data_dir || "runtime",
    },
  });
  if (next.last_result && prior?.last_result?.id !== next.last_result.id) {
    store.pushLog({
      ts: new Date(next.last_result.created_at).toLocaleTimeString("ko-KR"),
      text:
        next.last_result.status === "PASS"
          ? "검사 합격"
          : next.last_result.failures
              .map((f) => ERR[f.code] || f.code)
              .join(", "),
      kind: next.last_result.status === "PASS" ? "ok" : "error",
    });
  }
}
export async function refresh() {
  const next = await request<Snapshot>("/status");
  acceptSnapshot(next);
}
export async function refreshBrands() {
  const brands = (await request<StationBrand[]>("/brands")).map(brandView);
  useApp.getState().setBrands(brands);
  return brands;
}
export async function refreshEquipment() {
  useApp.getState().setEquipment(await request("/equipment"));
  const snapshot = useApp.getState().snapshot;
  if (snapshot) acceptSnapshot(snapshot);
}
export const reportError = (e: unknown) =>
  useApp
    .getState()
    .setError(
      (e instanceof Error ? e.message : String(e)).replace(
        /[\u00b7\u2014\u2013]/g,
        ", ",
      ),
    );
const pending = new Map<string, any>();
const active = new Set<string>();
export async function sendCommand(name: string, reason = "", delta?: number) {
  const state = useApp.getState().snapshot,
    s = state?.session;
  if (!s) throw new Error("진행 중인 작업이 없습니다.");
  const key = name;
  if (active.has(key)) return;
  active.add(key);
  useApp.getState().setPending([...active]);
  let cmd = pending.get(key);
  if (
    !cmd ||
    cmd.session_id !== s.id ||
    cmd.reason !== reason ||
    cmd.delta !== delta
  ) {
    cmd =
      name === "adjust"
        ? { request_id: uuid(), session_id: s.id, delta, reason }
        : {
            request_id: uuid(),
            session_id: s.id,
            action: name,
            reason,
            expected_revision: state.revision,
            issued_at: Date.now() / 1000,
          };
  }
  pending.set(key, cmd);
  try {
    const result = await request(
      name === "adjust" ? "/adjustments" : "/commands",
      cmd,
    );
    pending.delete(key);
    await refresh();
    return result;
  } catch (error) {
    try {
      if (
        (await request("/commands/" + encodeURIComponent(cmd.request_id))).found
      ) {
        pending.delete(key);
        await refresh();
        return;
      }
    } catch {}
    const status = (error as { status?: number }).status;
    if (status && status >= 400 && status < 500) pending.delete(key);
    throw error;
  } finally {
    active.delete(key);
    useApp.getState().setPending([...active]);
  }
}
export async function startSession(config: SessionConfig) {
  if (active.has("create")) return;
  if (!ended(useApp.getState().snapshot?.session))
    throw new Error("진행 중인 작업을 먼저 종료하세요.");
  let recipe: Recipe;
  if (config.mode === "simple") {
    recipe = {
      kind: "simple",
      brand_id: "__simple__",
      brand_revision: 1,
      targets: {},
      channels: [],
      target_count:
        config.countMode === "target" ? config.target || null : null,
    };
  } else {
    const b = useApp
      .getState()
      .brands.find((b) => b.id === config.brandId)?.source;
    if (!b) throw new Error("브랜드를 선택하세요.");
    recipe = {
      kind: "condition",
      brand_id: b.id,
      brand_revision: b.revision,
      targets: config.targets || {
        style: config.item?.sku || "",
        color: config.item?.color || "",
        size: config.item?.size || "",
      },
      channels: [
        config.checks?.ocr && "ocr",
        config.checks?.rfid && "rfid",
        (config.checks?.barcode_tag || config.checks?.barcode_poly) &&
          "barcode",
      ].filter(Boolean) as string[],
      target_count:
        config.countMode === "target" ? config.target || null : null,
    };
  }
  active.add("create");
  useApp.getState().setPending([...active]);
  try {
    acceptSnapshot(await request<Snapshot>("/sessions", recipe));
  } catch (error) {
    // Creation may have committed before a connection was lost. Read it back
    // before allowing the next attempt; the server also rejects an active job.
    try {
      await refresh();
    } catch {}
    throw error;
  } finally {
    active.delete("create");
    useApp.getState().setPending([...active]);
  }
}
