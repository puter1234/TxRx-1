import { useEffect, useState } from "react";
import { useApp } from "../lib/store";

const clock = (d: Date) =>
  d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit" });

export default function TopBar() {
  const connected = useApp((s) => s.connected);
  const mode = useApp((s) => s.snapshot?.mode);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <header className="flex h-20 shrink-0 items-center gap-6 border-b-2 border-line bg-white px-8">
      <span className="text-[32px] font-black tracking-[0.18em] text-brand-800">TXRX</span>
      <span className="text-[26px] font-extrabold">자동 계수</span>
      <div className="ml-auto flex items-center gap-4">
        {mode === "REPLAY" && (
          <span className="rounded-xl bg-warn-bg px-4 py-2 text-[24px] font-extrabold">사진 시험</span>
        )}
        {!connected && (
          <span role="status" className="rounded-xl bg-danger px-4 py-2 text-[24px] font-extrabold text-white">
            연결 끊김
          </span>
        )}
        <div className="text-right leading-tight">
          <div className="text-[26px] font-extrabold tabular-nums">{clock(now)}</div>
          <div className="text-[18px] font-bold text-ink-700">JOOYOUNG FNC</div>
        </div>
      </div>
    </header>
  );
}
