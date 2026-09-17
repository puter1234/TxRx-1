import { useState } from "react";
import { Plus, Trash2, Save, Upload, Download } from "lucide-react";
import { api, Field, Badge, download } from "./shared";
import type { Action, Brand, Fields, Option, Region } from "./shared";

const empty = (): Brand => ({
  id: "",
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
    [key, setKey] = useState(""),
    [label, setLabel] = useState(""),
    [reason, setReason] = useState("");
  const option = (index: number, patch: Partial<Option>) =>
    setDraft({
      ...draft,
      options: draft.options.map((o, i) =>
        i === index ? { ...o, ...patch } : o,
      ),
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
  const region = (field: string) =>
    draft.ocr_regions.find((r) => r.field === field);
  const setRegion = (field: string, patch: Partial<Region>) => {
    const prior = region(field) || {
      field,
      box: [0, 0, 1, 1] as Region["box"],
      rotation: 0 as const,
      min_char_confidence: null,
    };
    setDraft({
      ...draft,
      ocr_regions: [
        ...draft.ocr_regions.filter((r) => r.field !== field),
        { ...prior, ...patch },
      ],
    });
  };
  return (
    <div className="grid gap-5 xl:grid-cols-[250px_1fr]">
      <aside className="card space-y-3 self-start p-5">
        <h2 className="text-xl font-extrabold">메이커 설정</h2>
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
          메이커 추가
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
            현재 작업을 종료한 후 설정을 저장할 수 있습니다. 진행 중인 검사는
            시작 시점의 설정을 유지합니다.
          </p>
        )}
        <fieldset disabled={role !== "admin"} className="space-y-5">
          <div className="card space-y-5 p-6">
            <div className="flex flex-wrap justify-between gap-3">
              <h2 className="text-2xl font-extrabold">
                목표 옵션과 메이커 규칙
              </h2>
              <Badge>개정 {draft.revision}</Badge>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="메이커 ID (영문/숫자/-/_)">
                <input
                  className="field"
                  value={draft.id}
                  disabled={existing}
                  onChange={(e) =>
                    setDraft({ ...draft, id: e.target.value.toLowerCase() })
                  }
                />
              </Field>
              <Field label="표시 이름">
                <input
                  className="field"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </Field>
            </div>
            <h3 className="text-lg font-extrabold">선택 가능한 옵션</h3>
            <p className="text-ink-500">
              값은 쉼표 또는 줄바꿈으로 구분합니다. 검사 화면에서 각 옵션의
              목표값을 선택합니다.
            </p>
            {draft.options.map((o, i) => (
              <div className="rounded-xl border border-line p-4" key={o.key}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <strong>
                    {o.label}{" "}
                    <span className="text-sm text-ink-500">({o.key})</span>
                  </strong>
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
              </div>
            ))}
            <div className="flex flex-wrap gap-3">
              <input
                aria-label="새 옵션 키"
                className="field !w-44"
                placeholder="예: size"
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
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
                  setKey("");
                  setLabel("");
                }}
              >
                <Plus size={20} />
                옵션 추가
              </button>
            </div>
          </div>
          <div className="card space-y-5 p-6">
            <h3 className="text-xl font-extrabold">RFID · 바코드 기준</h3>
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
                <option value="none">미등록 · RFID 검사 시작 차단</option>
                <option value="hazzys_6bit_crc8">
                  헤지스 · 제공 표본의 6-bit/CRC 규칙
                </option>
                <option value="lookup">메이커별 EPC 기준표</option>
              </select>
            </Field>
            {draft.decoder.kind === "hazzys_6bit_crc8" && (
              <p className="rounded-xl bg-warn-bg p-4">
                품번·색상·사이즈만 해독합니다. 후행 01·일련번호 의미는
                미확정이며 CRC는 정품 인증이 아닙니다.
              </p>
            )}
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
            <p className="text-ink-500">
              EPC {Object.keys(draft.decoder.records).length}건 · 바코드{" "}
              {Object.keys(draft.barcode_records).length}건. 바코드는 검사 시작
              시 선택한 경우에만 필수 판정에 포함됩니다.
            </p>
            <Field label="규칙 근거·메모">
              <textarea
                className="field min-h-24 py-3"
                value={draft.note}
                onChange={(e) => setDraft({ ...draft, note: e.target.value })}
              />
            </Field>
          </div>
        </fieldset>
        <div className="card space-y-4 p-6">
          <h3 className="text-xl font-extrabold">OCR 촬영 영역</h3>
          <p className="text-ink-500">
            정지 촬영 이미지에서 각 옵션의 한 줄 영역을 지정합니다. 좌표는
            이미지 대비 0~1입니다. 기존 PARSeq 인식기를 사용하며 바코드 검출을
            요구하지 않습니다.
          </p>
          {draft.options.map((o) => {
            const r = region(o.key);
            return (
              <div key={o.key} className="rounded-xl border border-line p-4">
                <label className="flex items-center gap-3 font-bold">
                  <input
                    type="checkbox"
                    checked={!!r}
                    onChange={(e) =>
                      e.target.checked
                        ? setRegion(o.key, {})
                        : setDraft({
                            ...draft,
                            ocr_regions: draft.ocr_regions.filter(
                              (v) => v.field !== o.key,
                            ),
                          })
                    }
                  />
                  {o.label} OCR 영역
                </label>
                {r && (
                  <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                    {["왼쪽", "위쪽", "너비", "높이"].map((name, i) => (
                      <Field label={name} key={i}>
                        <input
                          className="field"
                          type="number"
                          min="0"
                          max="1"
                          step="0.001"
                          value={r.box[i]}
                          onChange={(e) => {
                            const box = [...r.box] as Region["box"];
                            box[i] = Number(e.target.value);
                            setRegion(o.key, { box });
                          }}
                        />
                      </Field>
                    ))}
                    <Field label="회전">
                      <select
                        className="field"
                        value={r.rotation}
                        onChange={(e) =>
                          setRegion(o.key, {
                            rotation: Number(
                              e.target.value,
                            ) as Region["rotation"],
                          })
                        }
                      >
                        {[0, 90, 180, 270].map((n) => (
                          <option key={n} value={n}>
                            {n}°
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="최소 문자 신뢰도">
                      <input
                        className="field"
                        type="number"
                        min="0"
                        max="1"
                        step="0.01"
                        placeholder="실측 후 지정"
                        value={r.min_char_confidence ?? ""}
                        onChange={(e) =>
                          setRegion(o.key, {
                            min_char_confidence:
                              e.target.value === ""
                                ? null
                                : Number(e.target.value),
                          })
                        }
                      />
                    </Field>
                  </div>
                )}
              </div>
            );
          })}
        </div>
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
              }, "메이커 설정을 저장했습니다.")
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
                    `/brands/${encodeURIComponent(draft.id)}?revision=${draft.revision}&reason=${encodeURIComponent(reason || "메이커 삭제 확인")}`,
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
              메이커 삭제
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
