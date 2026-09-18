import type { ReactNode } from "react";

export type Option = { key: string; label: string; values: string[] };
export type Region = {
  field: string;
  box: [number, number, number, number];
  rotation: 0 | 90 | 180 | 270;
  min_char_confidence: number | null;
};
export type Fields = Record<string, string>;
export type Brand = {
  id: string;
  name: string;
  revision: number;
  options: Option[];
  decoder: {
    kind: "none" | "hazzys_6bit_crc8" | "lookup";
    records: Record<string, Fields>;
  };
  ocr_regions: Region[];
  barcode_records: Record<string, Fields>;
  note: string;
};
export type Recipe = {
  kind?: "condition" | "simple";
  brand_id: string;
  brand_revision: number;
  targets: Fields;
  channels: string[];
  target_count: number | null;
};
export type Session = {
  id: string;
  phase: string;
  count: number;
  passed: number;
  failed: number;
  adjustments: number;
  created_at: string;
  active_product: string | null;
  recipe: Recipe;
  brand: Brand;
  fault: string | null;
  mode: string;
};
export type Failure = {
  code: string;
  field?: string;
  channel?: string;
  expected?: string;
  actual?: string;
  detail?: string;
};
export type Result = {
  id: string;
  product_id: string;
  attempt: number;
  status: string;
  mode: string;
  created_at: string;
  observations: Record<string, Fields>;
  failures: Failure[];
  evidence?: { url?: string; retained?: boolean };
};
export type Snapshot = {
  can_start?: boolean;
  blockers?: string[];
  observed_at?: string;
  boot_id: string;
  revision: number;
  mode: string;
  session: Session | null;
  busy: boolean;
  last_result: Result | null;
  stop_fault: string | null;
  io: Record<string, unknown>;
  vision: {
    loaded: boolean;
    local_assets_present: boolean;
    error: string | null;
    busy: boolean;
  };
};
export type Action = (
  work: () => Promise<unknown>,
  success?: string,
) => Promise<void>;
export const PHASE: Record<string, string> = {
  READY: "검사 대기",
  RETRY_PENDING: "정지 상태 검사 준비",
  FEEDING: "제품 이송",
  STOPPING: "정지 확인",
  INSPECTING: "검사 중",
  HOLD: "작업자 확인 필요",
  PASSED: "합격, 배출 대기",
  EJECTING: "제품 배출",
  PAUSED: "일시 정지",
  FAULT: "장비 오류",
  DONE: "목표 완료",
  FINISHED: "작업 종료",
  ABORTED: "중단된 작업",
};
export const CHANNEL: Record<string, string> = {
  ocr: "OCR 문자",
  rfid: "RFID",
  barcode: "바코드 (선택)",
};
export const ERR: Record<string, string> = {
  REQUIRED_FIELD_MISSING: "필수 항목 미판독",
  TARGET_MISMATCH: "목표와 불일치",
  RFID_MISSING: "RFID 미판독",
  MULTIPLE_RFID_TAGS: "복수 RFID 감지",
  RFID_CRC_INVALID: "RFID 검증 오류",
  RFID_UNREGISTERED: "등록되지 않은 RFID",
  IMAGE_MISSING: "검사 이미지 없음",
  OCR_LOW_CONFIDENCE: "문자 판독 품질 부족",
  VISION_TIMEOUT: "영상 처리 시간 초과",
  INSPECTION_CANCELLED: "검사 중단",
  PROCESS_RESTART: "프로그램 재시작으로 중단",
  OPERATOR_SCREEN_DISCONNECTED: "운전 화면 연결 끊김",
  INSPECTION_ERROR: "검사 처리 오류",
  IO_STOP_UNCONFIRMED: "장비 정지 확인 불가",
  IO_DISCONNECTED: "장비 제어 연결 끊김",
  RFID_DISCONNECTED: "RFID 연결 끊김",
  CAMERA_STALE: "카메라 영상 수신 중단",
  PRODUCT_DEPARTURE_TIMEOUT: "제품 배출 확인 시간 초과",
  INSPECTION_TIMEOUT: "검사 시간 초과",
  KM2_FEEDBACK_STUCK: "접촉기 정지 신호 미확인",
  DATABASE_WRITE_FAILED: "검사 기록 저장 실패",
  SERVICE_SHUTDOWN: "프로그램 종료로 중단",
  RFID_ERROR: "RFID 읽기 오류",
  VISION_ERROR: "영상 판독 오류",
};
export const display = (v: unknown): string =>
  v === null || v === undefined
    ? "미확인"
    : typeof v === "boolean"
      ? v
        ? "예"
        : "아니요"
      : typeof v === "string"
        ? v
        : JSON.stringify(v);
export const uuid = () => crypto.randomUUID();
export async function api<T = any>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const form = body instanceof FormData;
  const res = await fetch("/api" + path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers:
      body !== undefined && !form
        ? { "Content-Type": "application/json" }
        : undefined,
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  const data = await res.json();
  if (res.status === 401 || res.status === 403)
    window.dispatchEvent(new Event("txrx-login-required"));
  if (!res.ok)
    throw Object.assign(
      new Error(
        (typeof data.detail === "string" ? data.detail : "요청 처리 실패") +
          (data.errors
            ? " " +
              data.errors
                .map(
                  (v: { field: string; message: string }) =>
                    v.field + ": " + v.message,
                )
                .join(" / ")
            : ""),
      ),
      { status: res.status },
    );
  return data;
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2 block font-bold text-ink-700">{label}</span>
      {children}
    </label>
  );
}
export function Badge({
  children,
  red = false,
}: {
  children: ReactNode;
  red?: boolean;
}) {
  return (
    <span
      className={
        "rounded-lg px-3 py-2 text-lg font-bold " +
        (red ? "bg-danger-bg text-danger" : "bg-brand-50 text-brand-800")
      }
    >
      {children}
    </span>
  );
}
export function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function ResultCard({ result: r }: { result: Result | null }) {
  return (
    <div className="card p-6">
      <h2 className="text-xl font-extrabold">검사 결과</h2>
      {!r ? (
        <p className="py-10 text-center text-ink-700">검사 결과 없음</p>
      ) : (
        <>
          <div className="my-4 flex flex-wrap gap-2">
            <Badge red={r.status !== "PASS"}>
              {r.status === "PASS"
                ? "합격"
                : r.status === "FAIL"
                  ? "불합격, 작업자 확인"
                  : "중단"}
            </Badge>
            <Badge>{r.mode === "REPLAY" ? "사진 시험" : "장비 검사"}</Badge>
            <Badge>{r.attempt}회차</Badge>
          </div>
          <p className="break-all text-base font-semibold text-ink-900">
            제품 {r.product_id}
          </p>
          {r.evidence?.url && (
            <img
              className="mt-4 max-h-80 w-full rounded-xl bg-panel object-contain"
              src={r.evidence.url}
              alt="검사 사진"
            />
          )}
          {r.evidence?.retained === false && (
            <p className="mt-3 text-lg font-bold">통과 사진 저장 꺼짐</p>
          )}
          <div className="mt-4 space-y-3">
            {Object.entries(r.observations).map(([c, fields]) => (
              <div key={c} className="rounded-xl bg-panel p-3">
                <strong>{CHANNEL[c] || c}</strong>
                {Object.entries(fields).map(([k, v]) => (
                  <div key={k}>
                    {k}: <strong>{v}</strong>
                  </div>
                ))}
              </div>
            ))}
            {r.failures.map((f, i) => (
              <div key={i} className="rounded-xl bg-danger-bg p-3 text-danger">
                <strong>{ERR[f.code] || f.code}</strong>
                <p>
                  {f.channel} {f.field}{" "}
                  {f.expected !== undefined
                    ? `목표 ${f.expected} / 판독 ${display(f.actual)}`
                    : ""}
                </p>
                {f.detail && <p className="break-all text-sm">{f.detail}</p>}
              </div>
            ))}
          </div>
          <button
            className="btn btn-outline mt-4"
            onClick={() => download(`inspection-${r.id}.json`, r)}
          >
            검사 기록 내보내기
          </button>
        </>
      )}
    </div>
  );
}
