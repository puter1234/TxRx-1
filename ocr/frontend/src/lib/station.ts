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
export const runPath = (kind?: string) =>
  kind === "simple" ? "/simple" : kind === "vision" ? "/vision" : "/condition/run";
// Only a fresh READY job can be adjusted without discarding the job. HOLD,
// PAUSED and recovery states may still own a product and remain protected.
export const cameraEditable = (s: Snapshot | null | undefined) =>
  !s?.busy && (ended(s?.session) || (s?.session?.phase === "READY" && !s.session.active_product));
export const brandView = (b: StationBrand): Brand => ({
  ...b,
  source: b,
  caps: b.caps || {
    ocr: true,
    rfid: b.decoder.kind !== "none",
    barcode_tag: Object.keys(b.barcode_records).length > 0,
    barcode_poly: Object.keys(b.barcode_poly_records || {}).length > 0,
  },
});
export const configView = (s: Session): SessionConfig => ({
  mode: s.recipe.kind || "condition",
  presetId: s.recipe.preset_id,
  presetRevision: s.recipe.preset_revision,
  workName: s.recipe.work_name,
  modelPath: s.recipe.flow?.model_path,
  testRun: s.recipe.test_run,
  brandId: s.recipe.brand_id,
  brandName: s.brand.name,
  checks: {
    ocr: s.recipe.channels.includes("ocr"),
    rfid: s.recipe.channels.includes("rfid"),
    barcode_tag: s.recipe.channels.includes("barcode") && (s.recipe.barcode_targets || ["tag"]).includes("tag"),
    barcode_poly: s.recipe.channels.includes("barcode") && (s.recipe.barcode_targets || []).includes("poly"),
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
  date: new Date(s.created_at).toLocaleDateString("sv-SE", {timeZone: "Asia/Seoul"}),
  time: new Date(s.created_at).toLocaleTimeString("ko-KR", {timeZone: "Asia/Seoul"}),
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
let stopGeneration = 0;
export async function sendCommand(name: string, reason = "", delta?: number) {
  if (["stop", "pause", "finish"].includes(name)) stopGeneration++;
  const state = useApp.getState().snapshot,
    s = state?.session;
  if (!s) {
    if (name === "stop" && active.has("create")) return;
    throw new Error("진행 중인 작업 없음");
  }
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
export async function startSession(config: SessionConfig, run = false) {
  if (active.has("create")) return;
  if (!ended(useApp.getState().snapshot?.session))
    throw new Error("진행 중인 작업 있음");
  let recipe: Recipe | undefined;
  let path = "/sessions";
  let body: unknown;
  const generation = stopGeneration;
  const channels = [config.checks?.ocr && "ocr", config.checks?.rfid && "rfid",
    (config.checks?.barcode_tag || config.checks?.barcode_poly) && "barcode"].filter(Boolean) as string[];
  const barcodeTargets = [config.checks?.barcode_tag && "tag", config.checks?.barcode_poly && "poly"].filter(Boolean) as ("tag" | "poly")[];
  if (config.presetId) {
    if (!config.presetRevision) throw new Error("작업 설정 다시 선택");
    const brand = useApp.getState().brands.find((b) => b.id === config.brandId)?.source;
    path = `/presets/${encodeURIComponent(config.presetId)}/start`;
    body = {
      preset_revision: config.presetRevision,
      brand_revision: brand?.revision || 1,
      targets: config.targets || {},
      target_count: config.countMode === "target" ? config.target || null : null,
      test_run: config.testRun || false,
      ...(config.mode === "condition" && config.checks ? { channels, barcode_targets: barcodeTargets } : {}),
    };
  } else {
  if (config.mode === "vision") throw new Error("와펜 계수 설정 없음");
  if (config.mode === "simple") {
    recipe = {
      kind: "simple",
      brand_id: "__simple__",
      brand_revision: 1,
      targets: {},
      channels: [],
      target_count:
        config.countMode === "target" ? config.target || null : null,
      default_flow: true,
      test_run: config.testRun || false,
    };
  } else {
    const b = useApp
      .getState()
      .brands.find((b) => b.id === config.brandId)?.source;
    if (!b) throw new Error("브랜드 선택 필요");
    recipe = {
      kind: "condition",
      brand_id: b.id,
      brand_revision: b.revision,
      targets: config.targets || {
        style: config.item?.sku || "",
        color: config.item?.color || "",
        size: config.item?.size || "",
      },
      channels,
      barcode_targets: barcodeTargets,
      default_flow: true,
      test_run: config.testRun || false,
      target_count:
        config.countMode === "target" ? config.target || null : null,
    };
  }
  body = recipe;
  }
  active.add("create");
  useApp.getState().setPending([...active]);
  try {
    const created = await request<Snapshot>(path, body);
    acceptSnapshot(created);
    // The I/O monitor arms the released sensors on its next ticks after a
    // session is created. Wait for that initial debounce before the one-click
    // start, while leaving STOP able to cancel the pending command.
    const deadline = Date.now() + 1500;
    while (run && generation === stopGeneration && Date.now() < deadline) {
      const next = useApp.getState().snapshot;
      if (next?.session?.id !== created.session?.id || next?.can_start !== false ||
          next.mode !== "HARDWARE" || !next.blockers?.length ||
          !next.blockers.every(reason => reason === "DI1과 DI2의 해제 신호를 확인 중입니다.")) break;
      const raw = next.io.di_raw;
      if (!Array.isArray(raw) || raw[0] !== 1 || raw[1] !== 1) break;
      await new Promise(resolve => setTimeout(resolve, 100));
      if (generation !== stopGeneration) break;
      await refresh();
    }
    if (run && generation === stopGeneration && useApp.getState().snapshot?.session?.id === created.session?.id)
      await sendCommand("start");
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
