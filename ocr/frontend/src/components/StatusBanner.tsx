import { AlertTriangle, CheckCircle2, Hand } from "lucide-react";
import { useApp } from "../lib/store";
import { PHASE, ERR } from "../station/shared";
export default function StatusBanner() {
  const state = useApp((s) => s.snapshot),
    online = useApp((s) => s.connected);
  const session = state?.session,
    failure = state?.last_result?.failures[0];
  const fault = session && ["HOLD", "FAULT"].includes(session.phase);
  const label = !online
    ? "연결 끊김"
    : session
      ? PHASE[session.phase] || session.phase
      : "계수 대기";
  const Icon = fault
    ? AlertTriangle
    : session?.phase === "DONE"
      ? CheckCircle2
      : Hand;
  return (
    <div
      className={
        "card flex items-start gap-4 p-5 " +
        (fault || !online
          ? "border-danger bg-danger-bg"
          : "border-brand-200 bg-brand-50")
      }
    >
      <Icon
        size={34}
        className={fault ? "shrink-0 text-danger" : "shrink-0 text-brand-700"}
      />
      <div className="space-y-2 text-lg font-bold">
        <h3 className="text-2xl">{label}</h3>
        {session?.fault && <p>{ERR[session.fault] || session.fault}</p>}
        {failure?.field && (
          <p>
            {session?.brand.options.find((o) => o.key === failure.field)
              ?.label || failure.field}{" "}
            목표 {failure.expected || "없음"} 판독 {failure.actual || "미판독"}
          </p>
        )}
        {fault && <p>제품 확인 후 조치 확인을 누르세요.</p>}
        {!!state?.blockers?.length &&
          ["READY", "PAUSED"].includes(session?.phase || "") && (
            <p>
              {state.blockers.join(", ").replace(/[\u00b7\u2014\u2013]/g, ", ")}
            </p>
          )}
      </div>
    </div>
  );
}
