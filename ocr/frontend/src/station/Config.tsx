import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, Save, Upload, Download } from "lucide-react";
import OptionValues from "../components/OptionValues";
import { isColorOption } from "../lib/optionColors";
import { api, Field, download, readSettings, uuid } from "./shared";
import { useConfirm } from "../ui/kit";
import type { Action, Brand, Option } from "./shared";

const empty = (): Brand => ({
  id: uuid(),
  name: "",
  revision: 1,
  options: [],
  decoder: { kind: "none", records: {} },
  ocr_regions: [],
  barcode_records: {},
  note: "",
});
const brandDrafts = new Map<string, Brand>();
export default function Config({
  brands,
  action,
  refresh,
  locked,
  role = "admin",
  initialBrand,
  embedded = false,
}: {
  role?: string;
  brands: Brand[];
  action: Action;
  refresh: () => Promise<void>;
  locked: boolean;
  initialBrand?: Brand;
  embedded?: boolean;
}) {
  const [draft, setDraft] = useState<Brand>(() => {
      const cached = initialBrand && brandDrafts.get(initialBrand.id);
      return initialBrand
        ? structuredClone(
            cached?.revision === initialBrand.revision ? cached : initialBrand,
          )
        : empty();
    }),
    [existing, setExisting] = useState(!!initialBrand),
    [key, setKey] = useState("option_" + uuid().slice(0, 8)),
    [label, setLabel] = useState(""),
    [reason, setReason] = useState(embedded ? "브랜드 상품 설정 변경" : "");
  useEffect(() => {
    if (embedded) brandDrafts.set(draft.id, draft);
  }, [draft, embedded]);
  // In the brand screen every complete change is saved by itself.
  const [saved, setSaved] = useState(() => JSON.stringify(initialBrand ?? null));
  const [saveState, setSaveState] = useState<"" | "saving" | "saved">("");
  const [saveError, setSaveError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const complete = !!draft.id && !!draft.name.trim() && !draft.options.some((o) => !o.values.length);
  useEffect(() => setSaveError(""), [draft]);
  const pending = embedded && !locked && complete && saveState !== "saving" && !saveError && JSON.stringify(draft) !== saved;
  const saveNow = async () => {
    setSaveState("saving");
    const sent = draft;
    try {
      const updated = await api<Brand>("/brands", {
        brand: sent, expected_revision: existing ? sent.revision : null, reason: "브랜드 설정 변경",
      });
      setSaved(JSON.stringify(updated));
      setExisting(true);
      setDraft((d) => (JSON.stringify(d) === JSON.stringify(sent) ? updated : { ...d, revision: updated.revision }));
      setSaveState("saved");
      await refresh();
    } catch (e) {
      setSaveState("");
      setSaveError((e as Error).message);
    }
  };
  useEffect(() => {
    clearTimeout(timer.current);
    if (!pending) return;
    timer.current = setTimeout(() => void saveNow(), 800);
    return () => clearTimeout(timer.current);
  }, [draft, locked, saveState, saveError]);
  // Leaving within the wait still saves the last change.
  const flushRef = useRef<() => void>(() => {});
  flushRef.current = () => { if (pending) void saveNow(); };
  useEffect(() => () => flushRef.current(), []);
  const { confirm, dialog } = useConfirm();
  const optionKey =
    (
      {
        품번: "style",
        색상: "color",
        사이즈: "size",
        style: "style",
        color: "color",
        size: "size",
      } as Record<string, string>
    )[label.trim()] || key;
  const option = (index: number, patch: Partial<Option>) =>
    setDraft({
      ...draft,
      options: draft.options.map((o, i) => {
        if (i !== index) return o;
        const next = { ...o, ...patch };
        if (patch.values)
          next.colors = Object.fromEntries(
            Object.entries(next.colors || {}).filter(([code]) =>
              patch.values!.includes(code),
            ),
          );
        return next;
      }),
    });
  const importFile = (file: File | undefined) => {
    if (!file) return;
    action(async () => {
      if (file.size > 8 * 1024 * 1024)
        throw new Error("파일 크기 8MB 초과");
      const parsed = await api<Brand>(
        "/brands/validate",
        await readSettings(file),
      );
      setDraft(parsed);
      setExisting(brands.some((b) => b.id === parsed.id));
    }, "불러옴, 저장 전");
  };
  return (
    <div
      className={
        embedded ? "space-y-5" : "grid gap-5 xl:grid-cols-[250px_1fr]"
      }
    >
      {!embedded && (
        <aside className="card space-y-3 self-start p-5">
          <h2 className="text-[28px] font-black">브랜드 설정</h2>
          {brands.map((b) => (
            <button
              className={
                "btn w-full justify-start " +
                (draft.id === b.id ? "btn-primary" : "btn-outline")
              }
              key={b.id}
              onClick={() => {
                setDraft(structuredClone(b));
                setExisting(true);
              }}
            >
              {b.name}
            </button>
          ))}
          <button
            disabled={role !== "admin"}
            className="btn btn-outline w-full"
            onClick={() => {
              setDraft(empty());
              setExisting(false);
            }}
          >
            <Plus size={20} />
            브랜드 추가
          </button>
          <label className="btn btn-outline w-full cursor-pointer">
            <Upload size={18} />
            설정 가져오기
            <input
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => importFile(e.target.files?.[0])}
            />
          </label>
        </aside>
      )}
      <div className="space-y-4">
        {locked && (
          <p role="alert" className="rounded-2xl bg-warn-bg p-5 text-[26px] font-extrabold">
            작업 진행 중
          </p>
        )}
        {!embedded && (
          <Field label="설정 변경 사유">
            <input
              className="field"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
        )}
        {dialog}
        <fieldset disabled={role !== "admin" || (embedded && locked)} className="card relative p-6">
          {embedded ? (
            <p role="status" className={"mb-2 text-[24px] font-extrabold " + (saveError || !complete ? "text-danger" : "text-ink-700")}>
              {saveError || (locked ? "" : !draft.name.trim() ? "브랜드 이름 필요" : !complete ? "값 없는 항목 있음"
                : saveState === "saving" || JSON.stringify(draft) !== saved ? "저장 중" : saveState === "saved" ? "저장됨" : "")}
            </p>
          ) : (
          <div className="sticky top-0 z-10 -mx-6 -mt-6 mb-4 flex justify-end rounded-t-[1.25rem] border-b-2 border-line bg-white px-6 py-4">
            <button
              className="btn btn-primary"
              disabled={
                locked ||
                !draft.id ||
                !draft.name ||
                draft.options.some((o) => !o.values.length) ||
                reason.trim().length < 3
              }
              onClick={() =>
                action(async () => {
                  const updated = await api<Brand>("/brands", {
                    brand: draft,
                    expected_revision: existing ? draft.revision : null,
                    reason,
                  });
                  setDraft(updated);
                  setExisting(true);
                  await refresh();
                }, "저장됨")
              }
            >
              <Save size={28} />
              설정 저장
            </button>
          </div>
          )}
          <div className="divide-y divide-line">
            {draft.options.map((o, i) => (
              <section
                key={`${draft.id}:${o.key}`}
                className="grid gap-4 py-6 sm:grid-cols-[160px_minmax(0,1fr)]"
              >
                <h3 className="pt-3 text-[28px] font-black">{o.label}</h3>
                <OptionValues
                  option={o}
                  onChange={(patch) => option(i, patch)}
                />
              </section>
            ))}
          </div>
          <div className="mt-4 border-t-2 border-line pt-6">
            <div className="space-y-8">
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="브랜드 이름">
                  <input
                    className="field"
                    value={draft.name}
                    onChange={(e) =>
                      setDraft({ ...draft, name: e.target.value })
                    }
                  />
                </Field>
              </div>
              <div className="grid gap-6 lg:grid-cols-3">
                {draft.options.map((o, i) => (
                  <div className="min-w-0 self-start" key={o.key}>
                    <div className="mb-1 flex items-center justify-between gap-3 border-b-2 border-line pb-2">
                      <strong className="text-[24px] font-black">
                        {o.label}
                      </strong>
                      <button
                        className="btn btn-outline btn-sm text-danger"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            options: draft.options.filter((_, n) => n !== i),
                            ocr_regions: draft.ocr_regions.filter(
                              (r) => r.field !== o.key,
                            ),
                          })
                        }
                      >
                        옵션 삭제
                      </button>
                    </div>
                    <div className="mt-3">
                      <Field label="표시 이름">
                        <input
                          className="field"
                          value={o.label}
                          onChange={(e) => option(i, { label: e.target.value })}
                        />
                      </Field>
                      <label className="mt-3 flex items-center gap-3 text-xl font-bold">
                        <input
                          type="checkbox"
                          className="h-8 w-8 accent-brand-600"
                          checked={isColorOption(o)}
                          onChange={(e) =>
                            option(i, {
                              display: e.target.checked ? "colors" : "buttons",
                            })
                          }
                        />
                        색상 버튼 사용
                      </label>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-3">
                <input
                  aria-label="새 옵션 이름"
                  className="field !w-44"
                  placeholder="예: 사이즈"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                />
                <button
                  className="btn btn-outline"
                  disabled={
                    !/^[a-z][a-z0-9_]{0,31}$/.test(key) ||
                    !label ||
                    draft.options.some((o) => o.key === optionKey)
                  }
                  onClick={() => {
                    setDraft({
                      ...draft,
                      options: [
                        ...draft.options,
                        { key: optionKey, label: label.trim(), values: [] },
                      ],
                    });
                    setKey("option_" + uuid().slice(0, 8));
                    setLabel("");
                  }}
                >
                  <Plus size={20} />
                  옵션 추가
                </button>
              </div>
              {existing && (
                <RfidTags
                  brand={draft}
                  locked={locked}
                  onSaved={(b) => {
                    setDraft(b);
                    setSaved(JSON.stringify(b));
                    void refresh();
                  }}
                  onRemove={(epc) => {
                    const records = { ...draft.decoder.records };
                    delete records[epc];
                    setDraft({ ...draft, decoder: { ...draft.decoder, records } });
                  }}
                />
              )}
              <div className="space-y-4 border-t border-line pt-5">
                <Field label="메모">
                  <textarea
                    className="field min-h-24 py-3"
                    value={draft.note}
                    onChange={(e) =>
                      setDraft({ ...draft, note: e.target.value })
                    }
                  />
                </Field>
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  className="btn btn-outline"
                  onClick={() =>
                    download(`${draft.id || "maker"}-settings.json`, draft)
                  }
                >
                  <Download size={20} />
                  설정 내보내기
                </button>
                {existing && role === "admin" && (
                  <button
                    className="btn btn-outline text-danger"
                    disabled={locked}
                    onClick={() =>
                      action(async () => {
                        if (!(await confirm(`${draft.name} 삭제`, "삭제"))) return;
                        await api(
                          `/brands/${encodeURIComponent(draft.id)}?revision=${draft.revision}&reason=${encodeURIComponent(reason || "브랜드 삭제 확인")}`,
                          undefined,
                          "DELETE",
                        );
                        setDraft(empty());
                        setExisting(false);
                        await refresh();
                      })
                    }
                  >
                    <Trash2 size={20} />
                    브랜드 삭제
                  </button>
                )}
              </div>
            </div>
          </div>
        </fieldset>
      </div>
    </div>
  );
}

type Registered = { epc: string; replaced: Record<string, string> | null; count: number; brand: Brand };

// A tag read here is remembered as a product with the chosen values; 조건 계수 checks RFID against these.
function RfidTags({ brand, locked, onSaved, onRemove }: {
  brand: Brand; locked: boolean; onSaved: (b: Brand) => void; onRemove: (epc: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const records = brand.decoder.kind === "lookup" ? Object.entries(brand.decoder.records) : [];
  const ready = brand.options.length > 0 && brand.options.every((o) => o.values.includes(values[o.key]));
  const label = (key: string) => brand.options.find((o) => o.key === key)?.label || key;
  const read = async () => {
    setBusy(true);
    setMessage("");
    try {
      const r = await api<Registered>("/bench/rfid/register", { brand_id: brand.id, targets: values });
      onSaved(r.brand);
      setMessage((r.replaced ? "다시 등록됨 " : "등록됨 ") + r.epc);
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-labelledby="rfid-title" className="space-y-4 border-t border-line pt-5">
      <div className="flex flex-wrap items-center gap-4">
        <h3 id="rfid-title" className="mr-auto text-[28px] font-black">RFID 태그 {records.length}개</h3>
        {!adding && (
          <button className="btn btn-primary" disabled={locked || !brand.options.length} onClick={() => { setAdding(true); setMessage(""); }}>
            <Plus size={20} />
            RFID 태그 추가하기
          </button>
        )}
      </div>
      {adding && (
        <div className="card space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-3">
            {brand.options.map((o) => (
              <label key={o.key} className="space-y-1 text-[20px] font-extrabold">
                {o.label}
                <select
                  aria-label={o.label}
                  className="field"
                  value={values[o.key] || ""}
                  onChange={(e) => setValues({ ...values, [o.key]: e.target.value })}
                >
                  <option value="" disabled>고르기</option>
                  {o.values.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </label>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn btn-primary" disabled={!ready || busy || locked} onClick={() => void read()}>
              {busy ? "읽는 중" : "태그 읽기"}
            </button>
            <button className="btn btn-outline" disabled={busy} onClick={() => setAdding(false)}>닫기</button>
            {message && <span role="status" className="text-[20px] font-extrabold">{message}</span>}
          </div>
        </div>
      )}
      {records.length > 0 && (
        <ul className="space-y-2">
          {records.map(([epc, fields]) => (
            <li key={epc} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-2">
              <span className="mr-auto text-[18px] font-bold">
                {Object.entries(fields).map(([k, v]) => `${label(k)} ${v}`).join(", ")}
              </span>
              <code className="text-[15px] text-ink-700">{epc}</code>
              <button className="value-action" aria-label={`${epc} 삭제`} disabled={locked} onClick={() => onRemove(epc)}>
                <Trash2 size={20} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
