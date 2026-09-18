export type DeviceKey = "camera" | "sensor" | "rfid" | "conveyor";
export type DeviceState = "ok" | "idle" | "busy" | "fault" | "off";
export type NodeState = "idle" | "active" | "ok" | "fault";
export type PipelineNode =
  | "infeed"
  | "sensor"
  | "camera"
  | "rfid"
  | "conveyor"
  | "outfeed";

export interface LogItem {
  ts: string;
  text: string;
  kind: "info" | "ok" | "warn" | "error";
}

export interface BrandCaps {
  rfid: boolean;
  ocr: boolean;
  barcode_tag: boolean;
  barcode_poly: boolean;
}
export type Checks = BrandCaps;

export interface Brand {
  id: string;
  name: string;
  caps: BrandCaps;
  source: import("../station/shared").Brand;
}

export interface ItemCond {
  sku: string;
  color: string;
  size: string;
}

export interface SessionConfig {
  mode: "simple" | "condition";
  brandId?: string;
  brandName?: string;
  checks?: Checks;
  countMode: "target" | "continuous";
  target?: number | null;
  item?: ItemCond;
  targets?: Record<string, string>;
}

export interface Mismatch {
  field: string;
  expected: string;
  actual: string;
}

export type SessionStatus =
  | "idle"
  | "running"
  | "paused"
  | "mismatch"
  | "emergency"
  | "done";

export interface SessionState {
  mode: "simple" | "condition" | null;
  status: SessionStatus;
  count: number;
  startedAt: string | null;
  lastPassAt: string | null;
  config: SessionConfig | null;
  mismatch: Mismatch | null;
}

export interface ServerState {
  devices: Record<DeviceKey, DeviceState>;
  pipeline: Record<PipelineNode, NodeState>;
  session: SessionState;
  settings: { save_photos: boolean; threshold: number; data_dir: string };
}

export interface Job {
  id: string;
  date: string;
  time: string;
  mode: "simple" | "condition";
  count: number;
  config: SessionConfig | null;
  dir: string;
}
