import { useId, useState } from "react";
import { Check, Search } from "lucide-react";
import type { Option } from "../station/shared";
import { optionColorStyle } from "../lib/optionColors";

export default function OptionButtons({
  option,
  value,
  onChange,
}: {
  option: Option;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId(),
    [query, setQuery] = useState("");
  const values = option.values.filter((v) =>
    v.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  return (
    <section>
      <div className="mb-3 flex items-center gap-4">
        <h3 id={id} className="text-xl font-extrabold">
          {option.label}
        </h3>
        {value && (
          <span className="ml-auto text-lg font-bold">선택 {value}</span>
        )}
      </div>
      {option.values.length > 12 && (
        <label className="mb-3 flex items-center gap-3">
          <Search size={24} aria-hidden="true" />
          <input
            aria-label={option.label + " 검색"}
            className="field"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="검색"
          />
        </label>
      )}
      <div
        role="group"
        aria-labelledby={id}
        className="flex max-h-96 flex-wrap gap-3 overflow-y-auto p-1"
      >
        {values.map((v) => {
          const selected = value === v;
          return (
            <button
              key={v}
              type="button"
              aria-label={v}
              aria-pressed={selected}
              style={optionColorStyle(option, v)}
              className={
                "relative flex min-h-16 min-w-28 items-center justify-center gap-3 break-all rounded-xl border-2 px-5 py-4 text-2xl font-extrabold focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-brand-700 " +
                (selected
                  ? "border-brand-800 bg-brand-600 text-white ring-4 ring-brand-700 ring-offset-2"
                  : "border-ink-700 bg-white text-ink-900")
              }
              onClick={() => onChange(v)}
            >
              {v}
              {selected && (
                <Check size={26} strokeWidth={3} aria-hidden="true" />
              )}
            </button>
          );
        })}
        {!values.length && (
          <p className="py-4 text-lg font-bold">검색 결과 없음</p>
        )}
      </div>
    </section>
  );
}
