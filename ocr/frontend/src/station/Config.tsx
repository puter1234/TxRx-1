import { useState } from "react";
import { Plus, Trash2, Save, Upload, Download } from "lucide-react";
import Help from "../components/Help";
import ColorAssignments from "../components/ColorAssignments";
import { isColorOption } from "../lib/optionColors";
import { api, Field, Badge, download, uuid } from "./shared";
import type { Action, Brand, Fields, Option } from "./shared";

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
export default function Config({
  brands,
  action,
  refresh,
  locked,
  role = "admin",
}: {
  role?: string;
  brands: Brand[];
  action: Action;
  refresh: () => Promise<void>;
  locked: boolean;
}) {
  const [draft, setDraft] = useState<Brand>(empty()),
    [existing, setExisting] = useState(false),
    [key, setKey] = useState("option_" + uuid().slice(0, 8)),
    [label, setLabel] = useState(""),
    [reason, setReason] = useState("");
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
  const importFile = (
    file: File | undefined,
    kind: "brand" | "rfid" | "barcode",
  ) => {
    if (!file) return;
    action(async () => {
      if (file.size > 8 * 1024 * 1024)
        throw new Error("규칙 파일은 8MB 이하여야 합니다.");
      const data = JSON.parse(await file.text());
      if (kind === "brand") {
        const parsed = await api<Brand>("/brands/validate", data);
        setDraft(parsed);
        setExisting(brands.some((b) => b.id === parsed.id));
        return;
      }
      if (!Array.isArray(data) || !data.length)
        throw new Error(
          '기준표는 [{"epc":"HEX", "style":"품번", "color":"색상", "size":"사이즈"}] 형식입니다. 바코드는 epc 대신 barcode를 사용하세요.',
        );
      const records: Record<string, Fields> = {},
        idKey = kind === "rfid" ? "epc" : "barcode";
      for (const row of data) {
        if (!row || typeof row !== "object")
          throw new Error("잘못된 기준표 행입니다.");
        const id = String(row[idKey] ?? "").trim();
        if (!id) throw new Error(`${idKey} 값이 없습니다.`);
        if (records[id]) throw new Error(`중복 기준값: ${id}`);
        records[id] = {};
        for (const [k, v] of Object.entries(row))
          if (k !== idKey) {
            if (typeof v !== "string")
              throw new Error(
                "옵션 값은 095처럼 앞자리 0이 보존되는 문자열이어야 합니다.",
              );
            records[id][k] = v;
          }
      }
      const options = structuredClone(draft.options);
      for (const fields of Object.values(records))
        for (const [k, v] of Object.entries(fields)) {
          let o = options.find((x) => x.key === k);
          if (!o) {
            o = {
              key: k,
              label:
                ({ style: "품번", color: "색상", size: "사이즈" } as Fields)[
                  k
                ] || k,
              values: [],
            };
            options.push(o);
          }
          if (!o.values.includes(v)) o.values.push(v);
        }
      setDraft({
        ...draft,
        options,
        ...(kind === "rfid"
          ? { decoder: { kind: "lookup" as const, records } }
          : { barcode_records: records }),
      });
    }, "파일을 불러왔습니다. 내용을 확인한 후 저장하세요.");
  };
  return (
    <div className="grid gap-5 xl:grid-cols-[250px_1fr]">
      <aside className="card space-y-3 self-start p-5">
        <h2 className="text-xl font-extrabold">브랜드 설정</h2>
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
            onChange={(e) => importFile(e.target.files?.[0], "brand")}
          />
        </label>
      </aside>
      <div className="space-y-5">
        {locked && (
          <p role="alert" className="rounded-xl bg-warn-bg p-4 font-bold">
            작업 종료 후 설정을 저장하세요.
          </p>
        )}
        <fieldset disabled={role !== "admin"} className="space-y-5">
          <div className="card space-y-5 p-6">
            <div className="flex flex-wrap justify-between gap-3">
              <h2 className="text-2xl font-extrabold">
                목표 옵션과 브랜드 규칙
              </h2>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="표시 이름">
                <input
                  className="field"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </Field>
            </div>
            <h3 className="text-lg font-extrabold">선택 가능한 옵션</h3>
            <div className="flex justify-end">
              <Help text="사이즈나 색상의 선택값을 쉼표 또는 줄바꿈으로 나눠 입력합니다. 계수할 때는 등록한 값 중 하나를 선택합니다." />
            </div>
            {draft.options.map((o, i) => (
              <div className="rounded-xl border border-line p-4" key={o.key}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <strong className="text-xl">{o.label}</strong>
                  <button
                    className="btn btn-outline btn-sm"
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
                    <Trash2 size={17} />
                    옵션 삭제
                  </button>
                </div>
                <Field label="표시 이름">
                  <input
                    className="field"
                    value={o.label}
                    onChange={(e) => option(i, { label: e.target.value })}
                  />
                </Field>
                <textarea
                  aria-label={`${o.label} 선택값`}
                  className="field mt-3 min-h-24 py-3"
                  value={o.values.join(", ")}
                  onChange={(e) =>
                    option(i, {
                      values: e.target.value
                        .split(/[,\n]/)
                        .map((v) => v.trim()),
                    })
                  }
                />
                <label className="mt-4 flex items-center gap-3 text-lg font-bold">
                  <input
                    type="checkbox"
                    className="h-6 w-6 accent-brand-600"
                    checked={isColorOption(o)}
                    onChange={(e) =>
                      option(i, {
                        display: e.target.checked ? "colors" : "buttons",
                      })
                    }
                  />
                  색상 버튼 사용
                </label>
                {isColorOption(o) && (
                  <ColorAssignments
                    option={o}
                    onChange={(colors) => option(i, { colors })}
                  />
                )}
              </div>
            ))}
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
                  draft.options.some((o) => o.key === key)
                }
                onClick={() => {
                  setDraft({
                    ...draft,
                    options: [...draft.options, { key, label, values: [""] }],
                  });
                  setKey("option_" + uuid().slice(0, 8));
                  setLabel("");
                }}
              >
                <Plus size={20} />
                옵션 추가
              </button>
            </div>
          </div>
          <div className="card space-y-5 p-6">
            <h3 className="text-xl font-extrabold">RFID와 바코드 기준</h3>
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
                <option value="lookup">브랜드별 EPC 기준표</option>
              </select>
            </Field>
            <div className="flex justify-end">
              <Help text="제공한 헤지스 규칙으로 품번, 색상, 사이즈를 읽습니다. 다른 브랜드는 해당 브랜드의 기준표를 가져옵니다." />
            </div>
            <div className="flex flex-wrap gap-3">
              <label className="btn btn-outline cursor-pointer">
                <Upload size={18} />
                EPC 기준표 가져오기
                <input
                  className="hidden"
                  type="file"
                  accept=".json"
                  onChange={(e) => importFile(e.target.files?.[0], "rfid")}
                />
              </label>
              <label className="btn btn-outline cursor-pointer">
                <Upload size={18} />
                바코드 기준표 가져오기
                <input
                  className="hidden"
                  type="file"
                  accept=".json"
                  onChange={(e) => importFile(e.target.files?.[0], "barcode")}
                />
              </label>
              <button
                className="btn btn-outline"
                onClick={() =>
                  download("maker-epc-template.json", [
                    {
                      epc: "0123456789ABCDEF",
                      style: "EXAMPLE",
                      color: "BK",
                      size: "100",
                    },
                  ])
                }
              >
                <Download size={18} />
                기준표 양식
              </button>
            </div>
            <p className="text-lg font-bold">
              RFID 기준 {Object.keys(draft.decoder.records).length}건, 바코드
              기준 {Object.keys(draft.barcode_records).length}건
            </p>
            <Field label="메모">
              <textarea
                className="field min-h-24 py-3"
                value={draft.note}
                onChange={(e) => setDraft({ ...draft, note: e.target.value })}
              />
            </Field>
          </div>
        </fieldset>
        <Field label="설정 변경 사유">
          <input
            className="field"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <div className="flex flex-wrap gap-3">
          <button
            className="btn btn-primary"
            disabled={
              locked || !draft.id || !draft.name || reason.trim().length < 3
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
    </div>
  );
}
