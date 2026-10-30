import { useEffect, useState } from "react";
import { ScanLine } from "lucide-react";
import { api } from "../../station/shared";
import type { BenchHook } from "../DeviceTests";

// One button reads tags. The server finds the reader among the serial ports; a
// port is chosen here only when several USB serial devices are plugged in.
export default function RfidTest({ bench, locked }: { bench: BenchHook; locked: boolean }) {
  const setup = bench.state?.setup;
  const [ports, setPorts] = useState<{ device: string; name: string; usb?: boolean }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/bench/ports").then((r) => setPorts(r.ports || [])).catch(() => setPorts([]));
  }, []);
  const save = (fields: Record<string, unknown>) =>
    bench.action(() => api("/bench/rfid/setup", fields, "PUT"));
  const read = async () => {
    setError("");
    setBusy(true);
    try {
      await api("/bench/rfid", {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      await bench.refresh().catch(() => {});
    }
  };
  const result = bench.state?.rfid;
  const reading = busy || !!bench.state?.rfid_busy;
  const choices = ports?.some((p) => p.usb) ? ports.filter((p) => p.usb) : ports ?? [];
  const needsPort = choices.length > 1 && !choices.some((p) => p.device === setup?.rfid_port);
  return (
    <div className="space-y-6">
      {/* A wrong saved port that is still listed can be changed here too. */}
      {choices.length > 1 && (
        <label className="block space-y-2 text-[22px] font-extrabold">
          RFID 리더 포트
          <select className="field" value={setup?.rfid_port || ""} disabled={locked} onChange={(e) => save({ rfid_port: e.target.value })}>
            {needsPort && <option value="">고르기</option>}
            {choices.map((p) => <option key={p.device} value={p.device}>{p.name} ({p.device})</option>)}
          </select>
        </label>
      )}
      <button className="btn btn-primary btn-xl w-full" disabled={locked || reading || !!needsPort} onClick={read}>
        <ScanLine size={40} />
        {reading ? "읽는 중" : "태그 읽기"}
      </button>
      {error && <p role="alert" className="text-[24px] font-extrabold text-danger">{error}</p>}
      {!reading && !error && result && (
        <div className="space-y-3">
          <p className="text-[28px] font-black">{result.tags.length ? `태그 ${result.tags.length}개` : "태그 없음"}</p>
          {result.tags.map((tag: any) => (
            <div key={tag.epc} className="space-y-1 rounded-2xl border-2 border-line bg-white p-4">
              <p className="break-all font-mono text-[26px] font-black">{tag.epc}</p>
              <p className="text-[20px] font-bold text-ink-700">{tag.count}회 읽음, 신호 {tag.max_rssi}</p>
            </div>
          ))}
        </div>
      )}
      {setup && (
        <details className="rounded-2xl border-2 border-line bg-white p-4">
          <summary className="cursor-pointer text-[22px] font-extrabold">리더 설정</summary>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <NumberField label="읽기 시간 (ms)" value={setup.rfid_window_ms} min={100} max={10000} disabled={locked}
              onSave={(v) => save({ rfid_window_ms: v })} />
            <NumberField label="출력" value={setup.rfid_power} min={0} max={2600} disabled={locked}
              onSave={(v) => save({ rfid_power: v })} />
          </div>
          {setup.rfid_port && <p className="mt-3 text-[20px] font-bold text-ink-700">{setup.rfid_port}</p>}
        </details>
      )}
    </div>
  );
}

function NumberField({ label, value, min, max, disabled, onSave }: {
  label: string; value: number; min: number; max: number; disabled: boolean; onSave: (v: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const v = Number(text);
    if (Number.isInteger(v) && v >= min && v <= max && v !== value) onSave(v);
    else setText(String(value));
  };
  return (
    <label className="block space-y-2 text-[22px] font-extrabold">
      {label}
      <input className="field" type="number" min={min} max={max} value={text} disabled={disabled}
        onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
    </label>
  );
}
