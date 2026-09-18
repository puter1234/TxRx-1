import { useEffect, useState } from "react";
import { useApp } from "../lib/store";
import { api, uuid } from "../station/shared";
import { refresh, reportError } from "../lib/station";
import Help from "./Help";

export default function VideoPanel() {
  const snapshot = useApp((s) => s.snapshot),
    equipment = useApp((s) => s.equipment),
    connected = useApp((s) => s.connected);
  const [frame, setFrame] = useState(0),
    [failed, setFailed] = useState(false);
  const [testing, setTesting] = useState(false),
    [file, setFile] = useState<File | null>(null),
    [epc, setEpc] = useState(""),
    [busy, setBusy] = useState(false);
  const [product, setProduct] = useState(
    () => snapshot?.session?.active_product || uuid(),
  );
  const [fileKey, setFileKey] = useState(0);
  const s = snapshot?.session;
  const live = connected && equipment?.camera?.connected === true;
  useEffect(() => {
    if (!live) return;
    setFailed(false);
    const timer = setInterval(() => {
      setFrame(Date.now());
      setFailed(false);
    }, 750);
    return () => clearInterval(timer);
  }, [live]);
  useEffect(() => {
    if (s?.active_product) setProduct(s.active_product);
    else {
      setProduct(uuid());
      setFile(null);
      setFileKey((k) => k + 1);
      setEpc("");
    }
  }, [s?.id, s?.active_product]);
  const inspect = async () => {
    if (busy || !s) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.set("product_id", product);
      form.set("epcs", epc);
      if (file) form.set("image", file);
      await api("/replay", form);
      await refresh();
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  const needsPhoto =
    s?.recipe.kind === "simple" ||
    s?.recipe.channels.some((c) => c === "ocr" || c === "barcode");
  return (
    <div className="card shrink-0 overflow-visible">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h3 className="text-lg font-bold">
          {live ? "실시간 영상" : "검사 영상"}
        </h3>
        <span className="text-lg font-bold">
          {live && !failed
            ? "연결됨"
            : snapshot?.mode === "REPLAY"
              ? "사진 시험"
              : "카메라 미연결"}
        </span>
      </div>
      {live && !failed ? (
        <img
          src={"/api/camera/frame?t=" + frame}
          onError={() => setFailed(true)}
          className="aspect-video w-full bg-ink-900 object-contain"
          alt="실시간 영상"
        />
      ) : snapshot?.last_result?.evidence?.url ? (
        <img
          src={snapshot.last_result.evidence.url}
          className="aspect-video w-full bg-ink-900 object-contain"
          alt="최근 검사 사진"
        />
      ) : (
        <div className="flex aspect-video items-center justify-center bg-ink-900 text-2xl font-bold text-white">
          {snapshot?.mode === "REPLAY" ? "검사 사진 없음" : "카메라 미연결"}
        </div>
      )}
      {snapshot?.mode === "REPLAY" &&
        s &&
        !["DONE", "FINISHED", "ABORTED"].includes(s.phase) && (
          <div className="p-4">
            <button
              className="btn btn-outline w-full"
              onClick={() => setTesting((v) => !v)}
              aria-expanded={testing}
            >
              사진으로 시험
            </button>
            {testing && (
              <div className="mt-4 space-y-4">
                <div className="flex items-center">
                  <strong className="text-xl">시험할 제품</strong>
                  <Help text="같은 제품을 다시 검사할 때는 제품 번호가 유지됩니다. 합격 후 다음 제품 버튼을 누르면 새 번호로 바뀝니다." />
                </div>
                {(needsPhoto || s.recipe.kind === "simple") && (
                  <label className="block text-lg font-bold">
                    사진 선택
                    <input
                      key={fileKey}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="mt-2 block w-full text-lg"
                      disabled={busy || snapshot.busy}
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                    />
                  </label>
                )}
                {s.recipe.channels.includes("rfid") && (
                  <label className="block text-lg font-bold">
                    RFID 읽은 값
                    <textarea
                      value={epc}
                      disabled={busy || snapshot.busy}
                      onChange={(e) => setEpc(e.target.value)}
                      className="field mt-2 min-h-24 py-3"
                    />
                  </label>
                )}
                <button
                  className="btn btn-primary w-full"
                  disabled={
                    !connected ||
                    busy ||
                    snapshot.busy ||
                    !snapshot.can_start ||
                    s.phase !== "READY" ||
                    (needsPhoto && !file)
                  }
                  onClick={inspect}
                >
                  {busy ? "검사 중" : "검사"}
                </button>
              </div>
            )}
          </div>
        )}
    </div>
  );
}
