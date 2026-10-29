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
        throw new Error("파일 크기 8MB 초과");
      const parsed = await api<Brand>(
        "/brands/validate",
        JSON.parse(await file.text()),
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
        <fieldset disabled={role !== "admin"} className="card relative p-6">
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
              <div className="space-y-4 border-t border-line pt-5">
                <h3 className="text-[28px] font-black">RFID 설정</h3>
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
                            `${draft.name} 설정을 삭제할까요?`,
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
          </div>
        </fieldset>
      </div>
    </div>
  );
}
