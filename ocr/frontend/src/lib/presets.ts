import { useCallback, useEffect, useState } from "react";
import { api } from "../station/shared";
import type { Preset } from "../components/WorkPresets";

export function usePresets(kind: Preset["kind"]) {
  const [rows, setRows] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((v) => v + 1), []);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api<Preset[]>("/presets")
      .then((items) => { if (alive) setRows(items.filter((p) => p.enabled && p.kind === kind)); })
      .catch((e) => { if (alive) { setRows([]); setError(e.message); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [kind, attempt]);
  return { rows, loading, error, retry };
}
