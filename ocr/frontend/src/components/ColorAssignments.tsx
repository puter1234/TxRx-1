import { useState } from "react";
import Modal from "./Modal";
import type { Option } from "../station/shared";
import { colorInk, validColor, optionColorStyle } from "../lib/optionColors";

const palette = [
  ["흰색", "#FFFFFF"],
  ["검정", "#000000"],
  ["회색", "#808080"],
  ["빨강", "#E53935"],
  ["주황", "#FB8C00"],
  ["노랑", "#FDD835"],
  ["초록", "#2E7D32"],
  ["파랑", "#1565C0"],
  ["남색", "#142B49"],
  ["보라", "#7B1FA2"],
  ["분홍", "#F48FB1"],
  ["베이지", "#D8C4A2"],
];
export default function ColorAssignments({
  option,
  onChange,
  onlyCode,
}: {
  option: Option;
  onChange: (colors: Record<string, string>) => void;
  onlyCode?: string;
}) {
  const [code, setCode] = useState<string | null>(null),
    [custom, setCustom] = useState("#FFFFFF");
  const codes = [...new Set(option.values.filter((v) => v.trim() && (onlyCode === undefined || v === onlyCode)))];
  const assign = (color: string | null) => {
    if (code === null) return;
    const colors = { ...option.colors };
    if (color) colors[code] = color.toUpperCase();
    else delete colors[code];
    onChange(colors);
    setCode(null);
  };
  return (
    <div className={onlyCode === undefined ? "mt-4" : ""}>
      {onlyCode === undefined && <div className="mb-3 flex items-center">
        <h4 className="text-lg font-extrabold">코드별 색상</h4>

      </div>}
      <div className={onlyCode === undefined ? "flex max-h-80 flex-wrap gap-3 overflow-y-auto p-1" : "flex p-1"}>
        {codes.map((v) => (
          <button
            key={v}
            type="button"
            aria-label={v + " 색상 지정"}
            title="색상 지정"
            className={onlyCode === undefined ? "min-h-16 min-w-28 rounded-xl border-2 border-ink-700 bg-white px-5 py-3 text-xl font-extrabold" : "value-color-button"}
            style={optionColorStyle(option, v)}
            onClick={() => {
              setCode(v);
              setCustom(option.colors?.[v] || "#FFFFFF");
            }}
          >
            {onlyCode === undefined ? v : <span className="sr-only">색상</span>}
            {onlyCode === undefined && !option.colors?.[v] && (
              <span className="mt-1 block text-base font-bold">색상 지정</span>
            )}
          </button>
        ))}
      </div>
      {code !== null && (
        <Modal
          title={code + " 색상 지정"}
          onClose={() => setCode(null)}
          width="max-w-xl"
        >
          <div className="grid grid-cols-3 gap-3">
            {palette.map(([name, hex]) => (
              <button
                type="button"
                key={hex}
                className="min-h-20 rounded-2xl border-2 border-ink-500 px-3 text-2xl font-extrabold"
                style={{ backgroundColor: hex, color: colorInk(hex) }}
                onClick={() => assign(hex)}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-3 text-xl font-extrabold">
              직접 지정
              <input
                aria-label={code + " 직접 색상"}
                className="h-16 w-20 cursor-pointer rounded-xl border-2 border-ink-500 bg-white p-1"
                type="color"
                value={validColor(custom) ? custom : "#FFFFFF"}
                onChange={(e) => setCustom(e.target.value.toUpperCase())}
              />
            </label>
            <input
              aria-label="색상 값"
              className="field !w-36"
              value={custom}
              maxLength={7}
              onChange={(e) => setCustom(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={!validColor(custom)}
              onClick={() => assign(custom)}
            >
              적용
            </button>
          </div>
          <button
            type="button"
            className="btn btn-outline mt-4 w-full"
            onClick={() => assign(null)}
          >
            색상 해제
          </button>
        </Modal>
      )}
    </div>
  );
}
