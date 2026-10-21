import { useState } from "react";
import { ArrowLeft, Plus, Settings, Trash2, Upload } from "lucide-react";
import Config from "../station/Config";
import WorkPresets from "./WorkPresets";
import { api, uuid, type Brand } from "../station/shared";
import { brandView, reportError } from "../lib/station";

const checks = [
  ["rfid", "RFID"],
  ["ocr", "OCR"],
  ["barcode_tag", "가격택"],
  ["barcode_poly", "폴리백"],
] as const;

export default function BrandSettings({
  brands,
  refresh,
  locked,
}: {
  brands: Brand[];
  refresh: () => Promise<void>;
  locked: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState("product");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const brand = brands.find((b) => b.id === selected);
  const action = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };
  const save = async (b: Brand, existing: boolean) => {
    const result = await api<Brand>("/brands", {
      brand: b,
      expected_revision: existing ? b.revision : null,
      reason: "브랜드 설정 변경",
    });
    await refresh();
    return result;
  };
  if (brand)
    return (
      <div className="settings-compact space-y-4">
        <div className="flex items-center gap-4">
          <button className="btn btn-outline" onClick={() => setSelected(null)}>
            <ArrowLeft size={20} />
            브랜드 목록
          </button>
          <h2 className="text-xl font-semibold">{brand.name}</h2>
        </div>
        <div
          className="settings-tabs flex gap-5 border-b border-line"
          role="tablist"
          aria-label="브랜드 상세 설정"
        >
          {[
            ["product", "상품 조건"],
            ["capture", "촬영과 센서"],
          ].map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              className="settings-tab"
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div hidden={tab !== "product"}>
          <Config
            key={brand.id}
            initialBrand={brand}
            embedded
            brands={brands}
            refresh={refresh}
            locked={locked || busy}
            action={action}
          />
        </div>
        <div hidden={tab !== "capture"}>
          <WorkPresets key={brand.id} brandId={brand.id} />
        </div>
      </div>
    );
  return (
    <div className="settings-compact max-w-6xl space-y-4">
      <h2 className="text-xl font-semibold">브랜드 설정</h2>
      {locked && (
        <p role="alert" className="rounded-xl bg-warn-bg p-4 font-bold">
          작업 종료 후 설정을 변경하세요.
        </p>
      )}
      <div className="card overflow-x-auto">
        <table className="w-full text-[15px]">
          <thead className="border-b border-line bg-panel text-left">
            <tr>
              <th className="px-4 py-3 font-medium">브랜드</th>
              {checks.map(([key, label]) => (
                <th className="px-4 py-3 text-center font-medium" key={key}>
                  {label}
                </th>
              ))}
              <th className="px-4 py-3 font-medium">
                <span className="sr-only">관리</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {brands.map((b) => (
              <tr key={b.id} className="border-b border-line last:border-0">
                <th className="px-4 py-3 text-left font-medium">{b.name}</th>
                {checks.map(([key, label]) => (
                  <td className="px-4 py-3 text-center font-medium" key={key}>
                    <input
                      type="checkbox"
                      aria-label={`${b.name} ${label}`}
                      className="h-5 w-5 cursor-pointer accent-brand-600"
                      checked={brandView(b).caps[key]}
                      disabled={locked || busy}
                      onChange={(e) => {
                        const enabled = e.target.checked;
                        void action(() =>
                          save(
                            {
                              ...b,
                              caps: { ...brandView(b).caps, [key]: enabled },
                            },
                            true,
                          ),
                        );
                      }}
                    />
                  </td>
                ))}
                <td className="px-4 py-3 font-medium">
                  <div className="flex justify-end gap-2">
                    <button
                      className="btn btn-outline"
                      aria-label={`${b.name} 상세 설정`}
                      onClick={() => {
                        setSelected(b.id);
                        setTab("product");
                      }}
                    >
                      <Settings size={20} />
                      상세 설정
                    </button>
                    <button
                      className="btn btn-outline text-danger"
                      aria-label={`${b.name} 삭제`}
                      disabled={locked || busy}
                      onClick={() => {
                        if (window.confirm(`${b.name} 설정을 삭제할까요?`))
                          void action(async () => {
                            await api(
                              `/brands/${encodeURIComponent(b.id)}?revision=${b.revision}&reason=${encodeURIComponent("브랜드 삭제")}`,
                              undefined,
                              "DELETE",
                            );
                            await refresh();
                          });
                      }}
                    >
                      <Trash2 size={20} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!brands.length && <p className="p-6">등록된 브랜드가 없습니다.</p>}
      </div>
      <form
        className="flex flex-wrap gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return;
          void action(async () => {
            const b = await save(
              {
                id: uuid(),
                name: name.trim(),
                revision: 1,
                caps: {
                  rfid: false,
                  ocr: true,
                  barcode_tag: false,
                  barcode_poly: false,
                },
                options: [],
                decoder: { kind: "none", records: {} },
                ocr_regions: [],
                barcode_records: {},
                barcode_poly_records: {},
                note: "",
              },
              false,
            );
            setName("");
            setSelected(b.id);
            setTab("product");
          });
        }}
      >
        <input
          className="field !w-72"
          aria-label="새 브랜드 이름"
          placeholder="브랜드 이름"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={locked || busy}
        />
        <button
          className="btn btn-primary"
          disabled={locked || busy || !name.trim()}
        >
          <Plus size={20} />
          브랜드 추가
        </button>
        <label
          className={
            "btn btn-outline cursor-pointer " +
            (locked || busy ? "opacity-50" : "")
          }
        >
          <Upload size={20} />
          설정 가져오기
          <input
            type="file"
            accept=".json"
            className="hidden"
            disabled={locked || busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file)
                void action(async () => {
                  if (file.size > 8 * 1024 * 1024)
                    throw new Error("설정 파일은 8MB 이하여야 합니다.");
                  const imported = await api<Brand>(
                    "/brands/validate",
                    JSON.parse(await file.text()),
                  );
                  const current = brands.find((b) => b.id === imported.id);
                  if (
                    current &&
                    !window.confirm(
                      `${current.name} 설정을 가져온 파일로 변경할까요?`,
                    )
                  )
                    return;
                  const saved = await save(
                    { ...imported, revision: current?.revision || 1 },
                    !!current,
                  );
                  setSelected(saved.id);
                  setTab("product");
                });
            }}
          />
        </label>
      </form>
    </div>
  );
}
