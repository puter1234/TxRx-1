import { useEffect, useState } from "react";

export function useCameraPreview(connected: boolean) {
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);
  const [frame, setFrame] = useState({ seq: "", revision: "" });
  useEffect(() => {
    if (!connected) { setUrl(""); setFailed(false); return; }
    let alive = true, current = "", fps = 30;
    let timer: ReturnType<typeof setTimeout>, deadline: ReturnType<typeof setTimeout>;
    let abort: AbortController | undefined;
    const next = async () => {
      const started = performance.now();
      let retry = false;
      abort = new AbortController();
      deadline = setTimeout(() => abort?.abort(), 1500);
      try {
        const response = await fetch("/api/camera/frame", { signal: abort.signal, cache: "no-store" });
        if (!response.ok) throw new Error("영상 수신 실패");
        const nextUrl = URL.createObjectURL(await response.blob());
        if (!alive) { URL.revokeObjectURL(nextUrl); return; }
        const requested = Number(response.headers?.get("X-Camera-Fps"));
        if (requested >= 1 && requested <= 120) fps = requested;
        const previous = current;
        current = nextUrl; setUrl(nextUrl); setFailed(false);
        setFrame({ seq: response.headers?.get("X-Camera-Frame") || "",
          revision: response.headers?.get("X-Camera-Revision") || "" });
        if (previous) URL.revokeObjectURL(previous);
      } catch { if (alive) { setFailed(true); retry = true; } }
      finally { clearTimeout(deadline); }
      // Include transfer time in the frame period instead of adding a fixed pause.
      if (alive) timer = setTimeout(next, retry ? 250 : Math.max(1, 1000 / fps - (performance.now() - started)));
    };
    void next();
    return () => {
      alive = false; abort?.abort(); clearTimeout(timer); clearTimeout(deadline);
      if (current) URL.revokeObjectURL(current);
    };
  }, [connected]);
  return { url, failed, frame };
}
