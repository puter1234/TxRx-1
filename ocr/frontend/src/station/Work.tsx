import { useRef, useState } from "react";
import { Play, Square, Upload } from "lucide-react";
import {
  api,
  uuid,
  Field,
  Badge,
  ResultCard,
  PHASE,
  CHANNEL,
  ERR,
} from "./shared";
import type { Snapshot, Brand, Fields, Action } from "./shared";

export default function Work({
  state,
  brands,
  action,
  refresh,
  online,
  role = "admin",
}: {
  role?: string;
  state: Snapshot;
  brands: Brand[];
  action: Action;
  refresh: () => Promise<void>;
  online: boolean;
}) {
  const s = state.session;
  const [brandId, setBrandId] = useState(""),
    [targets, setTargets] = useState<Fields>({}),
    [channels, setChannels] = useState(["ocr", "rfid"]),
    [targetCount, setTargetCount] = useState("");
  const [productId, setProductId] = useState<string>(
      s?.active_product || uuid(),
    ),
    [epcs, setEpcs] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [reason, setReason] = useState(""),
    [delta, setDelta] = useState("1"),
    [submitting, setSubmitting] = useState(false),
    [fileKey, setFileKey] = useState(0);
  const brand = brands.find((b) => b.id === brandId),
    ended = !s || ["FINISHED", "DONE", "ABORTED"].includes(s.phase);
  const pending = useRef<Record<string, any>>({}),
    running = useRef(new Set<string>()),
    [sending, setSending] = useState<string[]>([]);
  const command = (name: string) =>
    action(async () => {
      if (running.current.has(name)) return;
      running.current.add(name);
      setSending([...running.current]);
      const prior = pending.current[name];
      const cmd =
        prior && prior.session_id === s!.id && prior.reason === reason
          ? prior
          : {
              request_id: uuid(),
              session_id: s!.id,
              action: name,
              reason,
              expected_revision: state.revision,
              issued_at: Date.now() / 1000,
            };
      pending.current[name] = cmd;
      try {
        await api("/commands", cmd);
        delete pending.current[name];
        await refresh();
      } catch (error) {
        let found = false;
        try {
          found = (await api("/commands/" + encodeURIComponent(cmd.request_id)))
            .found;
        } catch {}
        if (found) {
          delete pending.current[name];
          await refresh();
          return;
        }
        const status = (error as Error & { status?: number }).status;
        if (status && status >= 400 && status < 500)
          delete pending.current[name];
        throw error;
      } finally {
        running.current.delete(name);
        setSending([...running.current]);
      }
    });
  const inspect = () =>
    action(async () => {
      setSubmitting(true);
      try {
        const f = new FormData();
        f.set("product_id", productId);
        f.set("epcs", epcs);
        if (file) f.set("image", file);
        await api("/replay", f);
        await refresh();
      } finally {
        setSubmitting(false);
      }
    });
  return (
    <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
      <section className="space-y-5">
        <div className="card p-6">
          <div className="flex flex-wrap justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-ink-500">현재 작업</p>
              <h2 className="mt-1 text-3xl font-black">
                {s ? PHASE[s.phase] || s.phase : "작업을 준비하세요"}
              </h2>
            </div>
            <Badge red={["HOLD", "FAULT", "ABORTED"].includes(s?.phase || "")}>
              {state.mode === "REPLAY"
                ? "사진 검증 · 실물 출력 없음"
                : "실물 장비 모드"}
            </Badge>
          </div>
          {s && (
            <>
              <div className="mt-6 grid grid-cols-3 gap-3">
                {[
                  ["제품 수량", s.count],
                  ["합격", s.passed],
                  ["실패 검사", s.failed],
                ].map(([label, n]) => (
                  <div className="rounded-xl bg-panel p-4" key={label}>
                    <span className="font-bold">{label}</span>
                    <div className="mt-2 text-4xl font-black tabular-nums">
                      {n}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {Object.entries(s.recipe.targets).map(([k, v]) => (
                  <Badge key={k}>
                    {s.brand.options.find((o) => o.key === k)?.label || k}: {v}
                  </Badge>
                ))}
                <Badge>
                  {s.recipe.target_count
                    ? `목표 ${s.recipe.target_count}개`
                    : "계속 계수"}
                </Badge>
              </div>
              {s.fault && (
                <p
                  role="alert"
                  className="mt-4 rounded-xl bg-danger-bg p-4 font-bold text-danger"
                >
                  {ERR[s.fault] || s.fault}
                </p>
              )}
              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  className="btn btn-primary"
                  onClick={() => command("start")}
                  disabled={
                    sending.includes("start") ||
                    !online ||
                    state.busy ||
                    !state.can_start
                  }
                >
                  <Play size={21} />
                  운전 준비
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => command("stop")}
                  disabled={sending.includes("stop") || !online}
                >
                  <Square size={21} />
                  정지 요청
                </button>
                <button
                  className="btn btn-outline"
                  onClick={() => command("release")}
                  disabled={
                    sending.includes("release") ||
                    !online ||
                    state.busy ||
                    s.phase !== "PASSED"
                  }
                >
                  합격 제품 배출 확인
                </button>
              </div>
              {state.blockers?.length && s.phase === "READY" ? (
                <p className="mt-3 text-warn">
                  운전 준비 조건: {state.blockers.join(", ")}
                </p>
              ) : null}
              <p className="mt-3 text-sm text-ink-500">
                화면 정지는 소프트웨어 요청이며 현장 비상정지 버튼의 기능과
                구분됩니다.
              </p>
              <div className="mt-5 border-t border-line pt-5">
                <Field label="작업자 조치·보정 사유">
                  <input
                    className="field"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="미판독 제품 확인, 재검사 준비 등"
                    maxLength={500}
                  />
                </Field>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    className="btn btn-outline"
                    onClick={() => command("reset")}
                    disabled={
                      sending.includes("reset") ||
                      role === "operator" ||
                      !online ||
                      state.busy ||
                      reason.length < 3 ||
                      !["HOLD", "FAULT", "PAUSED"].includes(s.phase)
                    }
                  >
                    조치 확인 · 오류 해제
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={() => command("discard")}
                    disabled={
                      sending.includes("discard") ||
                      role === "operator" ||
                      !online ||
                      state.busy ||
                      reason.length < 3 ||
                      s.phase !== "HOLD"
                    }
                  >
                    불합격 제품 제거 확인
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={() => command("finish")}
                    disabled={
                      sending.includes("finish") ||
                      !online ||
                      state.busy ||
                      ended
                    }
                  >
                    작업 종료
                  </button>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <input
                    aria-label="수량 보정값"
                    className="field !w-28"
                    type="number"
                    value={delta}
                    onChange={(e) => setDelta(e.target.value)}
                  />
                  <button
                    className="btn btn-outline"
                    disabled={
                      role === "operator" ||
                      !online ||
                      state.busy ||
                      reason.length < 3 ||
                      !Number.isInteger(Number(delta))
                    }
                    onClick={() =>
                      action(async () => {
                        await api("/adjustments", {
                          request_id: uuid(),
                          session_id: s.id,
                          delta: Number(delta),
                          reason,
                        });
                        await refresh();
                      }, "수량 보정과 사유를 기록했습니다.")
                    }
                  >
                    수량 수동 보정
                  </button>
                  <span className="text-sm text-ink-500">
                    누적 보정 {s.adjustments}개
                  </span>
                </div>
              </div>
            </>
          )}
        </div>
        {ended && (
          <div className="card space-y-4 p-6">
            <h2 className="text-xl font-extrabold">새 검사 작업</h2>
            <Field label="메이커">
              <select
                className="field"
                value={brandId}
                onChange={(e) => {
                  setBrandId(e.target.value);
                  setTargets({});
                }}
              >
                <option value="">선택하세요</option>
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </Field>
            {brand?.options.map((o) => (
              <Field key={o.key} label={o.label}>
                <select
                  className="field"
                  value={targets[o.key] || ""}
                  onChange={(e) =>
                    setTargets({ ...targets, [o.key]: e.target.value })
                  }
                >
                  <option value="">목표값 선택</option>
                  {o.values.map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </Field>
            ))}
            <div className="flex flex-wrap gap-4">
              {Object.entries(CHANNEL).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 font-bold">
                  <input
                    type="checkbox"
                    className="h-5 w-5"
                    disabled={state.mode === "HARDWARE" && k !== "barcode"}
                    checked={channels.includes(k)}
                    onChange={(e) =>
                      setChannels(
                        e.target.checked
                          ? [...channels, k]
                          : channels.filter((x) => x !== k),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
            <p className="text-sm text-ink-500">
              선택한 항목에서 목표값을 하나라도 못 읽거나 값이 다르면 즉시
              보류·정지합니다.
            </p>
            <Field label="목표 수량 (비워 두면 계속 계수)">
              <input
                className="field"
                type="number"
                min="1"
                value={targetCount}
                onChange={(e) => setTargetCount(e.target.value)}
              />
            </Field>
            <button
              className="btn btn-primary w-full"
              disabled={
                !online ||
                !brand ||
                !brand.options.length ||
                !channels.length ||
                brand.options.some((o) => !targets[o.key])
              }
              onClick={() =>
                action(async () => {
                  await api("/sessions", {
                    brand_id: brand!.id,
                    brand_revision: brand!.revision,
                    targets,
                    channels,
                    target_count: targetCount ? Number(targetCount) : null,
                  });
                  await refresh();
                })
              }
            >
              선택한 목표로 작업 생성
            </button>
            {!brands.length && <p>설정에서 메이커와 옵션을 먼저 등록하세요.</p>}
          </div>
        )}
      </section>
      <section className="space-y-5">
        {state.mode === "REPLAY" && !ended && (
          <div className="card space-y-4 p-6">
            <h2 className="text-xl font-extrabold">정지 사진으로 검사 검증</h2>
            <p className="text-ink-500">
              재검사는 같은 제품 식별자를 유지하세요. 사진 검증 결과는 생산
              계수와 구분해 저장합니다.
            </p>
            <Field label="제품 식별자">
              <div className="flex gap-2">
                <input
                  className="field"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                  disabled={submitting}
                />
                <button
                  className="btn btn-outline shrink-0"
                  disabled={!!s?.active_product || state.busy}
                  onClick={() => {
                    setProductId(uuid());
                    setEpcs("");
                    setFile(null);
                    setFileKey((k) => k + 1);
                  }}
                >
                  다음 제품
                </button>
              </div>
            </Field>
            <Field label="정지 상태에서 촬영한 이미지">
              <input
                className="block w-full rounded-xl border-2 border-line p-3"
                key={fileKey}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                disabled={submitting}
              />
            </Field>
            <Field label="관측 EPC (여러 개는 줄바꿈)">
              <textarea
                className="field min-h-24 py-3 font-mono text-sm"
                value={epcs}
                onChange={(e) => setEpcs(e.target.value)}
                maxLength={10000}
                disabled={submitting}
              />
            </Field>
            <button
              className="btn btn-primary w-full"
              onClick={inspect}
              disabled={
                !online || submitting || state.busy || s?.phase !== "READY"
              }
            >
              <Upload size={20} />
              {submitting ? "검사 처리 중…" : "이 제품 검사"}
            </button>
          </div>
        )}
        <ResultCard result={state.last_result} />
      </section>
    </div>
  );
}
