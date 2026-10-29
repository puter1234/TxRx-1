import { useEffect, useState } from "react";
import { Plus, Trash2, Save, Upload, Download } from "lucide-react";
import OptionValues from "../components/OptionValues";
import { isColorOption } from "../lib/optionColors";
import { api, Field, download, uuid } from "./shared";
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
    [advanced, setAdvanced] = useState(!initialBrand?.options.length),
    [key, setKey] = useState("option_" + uuid().slice(0, 8)),
    [label, setLabel] = useState(""),
    [reason, setReason] = useState(embedded ? "브랜드 상품 설정 변경" : "");
  useEffect(() => {
    if (embedded) brandDrafts.set(draft.id, draft);
  }, [draft, embedded]);
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
        throw new Error("설정 파일은 8MB 이하여야 합니다.");
      const parsed = await api<Brand>(
        "/brands/validate",
        JSON.parse(await file.text()),
      );
      setDraft(parsed);
      setExisting(brands.some((b) => b.id === parsed.id));
    }, "파일을 불러왔습니다. 내용을 확인한 후 저장하세요.");
  };
  return (
    <div
      className={
        "settings-compact brand-product-settings " +
        (embedded ? "space-y-5" : "grid gap-5 xl:grid-cols-[250px_1fr]")
      }
    >
      {!embedded && (
        <aside className="card space-y-3 self-start p-5">
          <h2 className="text-base font-semibold">브랜드 설정</h2>
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
          <p role="alert" className="rounded-md bg-warn-bg p-3">
            작업 종료 후 설정을 저장하세요.
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
        <fieldset disabled={role !== "admin"} className="card p-6">
          <div className="mb-2 flex justify-end">
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
                }, "브랜드 설정을 저장했습니다.")
              }
            >
              <Save size={20} />
              설정 저장
            </button>
          </div>
          <div className="divide-y divide-line">
            {draft.options.map((o, i) => (
              <section
                key={`${draft.id}:${o.key}`}
                className="grid gap-3 py-5 sm:grid-cols-[100px_minmax(0,1fr)]"
              >
                <h3 className="pt-2 text-lg font-semibold">{o.label}</h3>
                <OptionValues
                  option={o}
                  onChange={(patch) => option(i, patch)}
                />
              </section>
            ))}
          </div>
          <details
            className="mt-3 border-t border-line pt-4"
            open={advanced}
            onToggle={(e) => setAdvanced(e.currentTarget.open)}
          >
            <summary className="w-fit cursor-pointer py-2 text-sm text-ink-500">
              추가 설정
            </summary>
            <div className="mt-5 space-y-6">
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
                    <div className="mb-1 flex items-center justify-between gap-3 border-b border-line pb-1">
                      <strong className="text-base font-medium">
                        {o.label}
                      </strong>
                      <button
                        className="btn btn-quiet btn-sm"
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
                      <label className="mt-3 flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="h-5 w-5 accent-brand-600"
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
              <div className="space-y-4 border-t border-line pt-5">
                <h3 className="text-base font-semibold">RFID 설정</h3>
                <Field label="RFID 해독 방식">
                  <select
                    className="field"
                    value={draft.decoder.kind}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        decoder: {
                          ...draft.decoder,
                          kind: e.target.value as Brand["decoder"]["kind"],
                        },
                      })
                    }
                  >
                    <option value="none">미등록</option>
                    <option value="hazzys_6bit_crc8">헤지스 제공 규칙</option>
                    <option value="lookup">저장된 RFID 규칙</option>
                  </select>
                </Field>
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
                        if (
                          !window.confirm(
                            `${draft.name} 설정을 삭제할까요? 검사 이력은 보존됩니다.`,
                          )
                        )
                          return;
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
          </details>
        </fieldset>
      </div>
    </div>
  );
}
