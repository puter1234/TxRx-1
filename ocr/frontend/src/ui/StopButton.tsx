import { Square } from "lucide-react";
import { useApp } from "../lib/store";
import { reportError, sendCommand } from "../lib/station";

// STOP never waits behind another command; during session creation it also
// cancels the automatic start.
export default function StopButton() {
  const online = useApp((s) => s.connected);
  const pending = useApp((s) => s.pending);
  return (
    <button
      className="btn btn-danger btn-xl min-w-[320px]"
      disabled={!online || pending.includes("stop")}
      onClick={() => sendCommand("stop").catch(reportError)}
    >
      <Square size={44} strokeWidth={3} fill="currentColor" />
      멈춤
    </button>
  );
}
