import { useState } from "react";
import { ArrowLeft, Plus, Settings, Trash2, Upload } from "lucide-react";
import Config from "../station/Config";
import WorkPresets from "./WorkPresets";
import { api, uuid, type Brand } from "../station/shared";
import { brandView, reportError } from "../lib/station";

const checks = [
  ["ocr", "OCR"],
  ["rfid", "RFID"],
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
      <div className="space-y-6">
        <div className="flex items-center gap-6">
          <button className="btn btn-outline btn-lg" onClick={() => setSelected(null)}>
            <ArrowLeft size={32} />
            브랜드 목록
          </button>
          <h2 className="text-[44px] font-black">{brand.name}</h2>
        </div>
        <div className="flex gap-4" role="tablist" aria-label="브랜드 상세 설정">
          {[
            ["product", "상품 조건"],
            ["capture", "촬영과 센서"],
          ].map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              className={"btn btn-lg min-w-[240px] " + (tab === id ? "btn-primary" : "btn-outline")}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div hidden={tab !== "product"}>
          <Config key={brand.id} initialBrand={brand} embedded brands={brands} refresh={refresh} locked={locked || busy} action={action} />
        </div>
        <div hidden={tab !== "capture"}>
          <WorkPresets key={brand.id} brandId={brand.id} />
        </div>
      </div>
    );
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <h2 className="mr-auto text-[36px] font-black">브랜드</h2>
        <form
          className="flex flex-wrap gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            void action(async () => {
              const b = await save(
                {
                  id: uuid(),
                  name: name.trim(),
                  revision: 1,
                  caps: { rfid: false, ocr: true, barcode_tag: false, barcode_poly: false },
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
            className="field !w-80"
            aria-label="새 브랜드 이름"
            placeholder="새 브랜드 이름"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={locked || busy}
          />
          <button className="btn btn-primary" disabled={locked || busy || !name.trim()}>
            <Plus size={28} />
            브랜드 추가
          </button>
          <label className={"btn btn-outline cursor-pointer " + (locked || busy ? "opacity-50" : "")}>
            <Upload size={28} />
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
                    if (file.size > 8 * 1024 * 1024) throw new Error("파일 크기 8MB 초과");
                    const imported = await api<Brand>("/brands/validate", JSON.parse(await file.text()));
                    const current = brands.find((b) => b.id === imported.id);
                    if (current && !window.confirm(`${current.name} 설정을 가져온 파일로 변경할까요?`)) return;
                    const saved = await save({ ...imported, revision: current?.revision || 1 }, !!current);
                    setSelected(saved.id);
                    setTab("product");
                  });
              }}
            />
          </label>
        </form>
      </div>
      {locked && (
        <p role="alert" className="rounded-2xl bg-warn-bg p-5 text-[26px] font-extrabold">
          작업 진행 중
        </p>
      )}
      <div className="space-y-4">
        {brands.map((b) => (
          <article key={b.id} className="card flex flex-wrap items-center gap-6 p-6">
            <h3 className="w-64 truncate text-[34px] font-black">{b.name}</h3>
            <div className="flex flex-wrap gap-4">
              {checks.map(([key, label]) => (
                <label
                  key={key}
                  className="flex cursor-pointer items-center gap-3 rounded-2xl border-2 border-line px-4 py-3 text-[24px] font-extrabold"
                >
                  <input
                    type="checkbox"
                    aria-label={`${b.name} ${label}`}
                    className="h-8 w-8 cursor-pointer accent-brand-600"
                    checked={brandView(b).caps[key]}
                    disabled={locked || busy}
                    onChange={(e) => {
                      const enabled = e.target.checked;
                      void action(() => save({ ...b, caps: { ...brandView(b).caps, [key]: enabled } }, true));
                    }}
                  />
                  {label}
                </label>
              ))}
            </div>
            <div className="ml-auto flex gap-3">
              <button
                className="btn btn-primary btn-lg"
                aria-label={`${b.name} 상세 설정`}
                onClick={() => {
                  setSelected(b.id);
                  setTab("product");
                }}
              >
                <Settings size={30} />
                편집
              </button>
              <button
                className="btn btn-outline btn-lg text-danger"
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
                <Trash2 size={30} />
              </button>
            </div>
          </article>
        ))}
        {!brands.length && <p className="p-6 text-[28px] font-extrabold text-ink-700">등록된 브랜드 없음</p>}
      </div>
    </div>
  );
}
