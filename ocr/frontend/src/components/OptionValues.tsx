import { useState } from "react";
import { Plus, X } from "lucide-react";
import type { Option } from "../station/shared";
import { isColorOption } from "../lib/optionColors";
import ColorAssignments from "./ColorAssignments";

export default function OptionValues({
  option,
  onChange,
}: {
  option: Option;
  onChange: (patch: Partial<Option>) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [replacement, setReplacement] = useState("");
  const [error, setError] = useState("");
  const close = () => {
    setAdding(false);
    setEditing(null);
    setError("");
  };
  const commit = () => {
    const next = (editing === null ? value : replacement).trim();
    if (!next) {
      setError("값 없음");
      return;
    }
    if (option.values.some((v) => v === next && v !== editing)) {
      setError("이미 있는 값");
      return;
    }
    const colors = { ...option.colors };
    if (editing !== null && editing !== next && colors[editing]) {
      colors[next] = colors[editing];
      delete colors[editing];
    }
    onChange({
      values:
        editing === null
          ? [...option.values, next]
          : option.values.map((v) => (v === editing ? next : v)),
      colors,
    });
    if (editing === null) setValue("");
    else setEditing(null);
    setError("");
  };
  return (
    <div
      className="min-w-0 space-y-3"
      role="group"
      aria-label={`${option.label} 목록`}
    >
      <div className="flex max-h-64 flex-wrap gap-2 overflow-y-auto p-1">
        {option.values.map((code) => (
          <button
            key={code}
            type="button"
            className="option-value"
            aria-label={`${option.label} ${code} 수정`}
            aria-expanded={editing === code}
            onClick={() => {
              setAdding(false);
              setEditing(code);
              setReplacement(code);
              setError("");
            }}
          >
            {isColorOption(option) && (
              <span
                aria-hidden="true"
                className="h-7 w-7 shrink-0 rounded-md border-2 border-ink-500"
                style={{ backgroundColor: option.colors?.[code] || "white" }}
              />
            )}
            {code}
          </button>
        ))}
        <button
          type="button"
          className="btn btn-quiet"
          aria-label={`${option.label} 추가`}
          aria-expanded={adding}
          onClick={() => {
            setEditing(null);
            setAdding(true);
            setValue("");
            setError("");
          }}
        >
          <Plus size={24} />
          추가
        </button>
      </div>
      {(adding || editing !== null) && (
        <div className="max-w-2xl rounded-2xl bg-panel p-4">
          <div className="flex flex-wrap items-center gap-2">
            <input
              key={editing ?? "add"}
              autoFocus
              className="field min-w-0 !w-44 flex-1"
              maxLength={100}
              aria-label={
                editing === null
                  ? `${option.label} 추가값`
                  : `${option.label} ${editing} 수정값`
              }
              placeholder={`${option.label} 입력`}
              value={editing === null ? value : replacement}
              onChange={(e) => {
                editing === null
                  ? setValue(e.target.value)
                  : setReplacement(e.target.value);
                setError("");
              }}
              onKeyDown={(e) => {
                if (e.nativeEvent.isComposing) return;
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit();
                }
                if (e.key === "Escape") close();
              }}
            />
            {editing !== null && isColorOption(option) && (
              <ColorAssignments
                option={option}
                onlyCode={editing}
                onChange={(colors) => onChange({ colors })}
              />
            )}
            <button
              type="button"
              className="btn btn-primary"
              aria-label={
                editing === null
                  ? `${option.label} 값 추가`
                  : `${option.label} ${editing} 수정 완료`
              }
              disabled={!(editing === null ? value : replacement).trim()}
              onClick={commit}
            >
              {editing === null ? "추가" : "적용"}
            </button>
            {editing !== null && (
              <button
                type="button"
                className="btn btn-quiet text-danger"
                aria-label={`${option.label} ${editing} 삭제`}
                onClick={() => {
                  onChange({
                    values: option.values.filter((v) => v !== editing),
                  });
                  close();
                }}
              >
                삭제
              </button>
            )}
            <button
              type="button"
              className="value-action"
              aria-label="편집 닫기"
              onClick={close}
            >
              <X size={28} />
            </button>
          </div>
          {error && (
            <p role="alert" className="mt-2 text-lg font-bold text-danger">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
