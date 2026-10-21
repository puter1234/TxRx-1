import { useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import type { Option } from "../station/shared";
import { isColorOption } from "../lib/optionColors";
import ColorAssignments from "./ColorAssignments";

export default function OptionValues({ option, onChange }: {
  option: Option; onChange: (patch: Partial<Option>) => void;
}) {
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [replacement, setReplacement] = useState("");
  const [error, setError] = useState("");
  const commit = (old: string | null) => {
    if (old === null && editing !== null) return;
    const next = (old === null ? value : replacement).trim();
    if (!next) { setError("값을 입력하세요."); return; }
    if (option.values.some(v => v === next && v !== old)) {
      setError("이미 등록된 값입니다."); return;
    }
    const colors = {...option.colors};
    if (old !== null && old !== next && colors[old]) {
      colors[next] = colors[old]; delete colors[old];
    }
    onChange({values: old === null ? [...option.values, next] : option.values.map(v => v === old ? next : v), colors});
    if (old === null) setValue("");
    setEditing(null); setError("");
  };
  return <div className="space-y-3" role="group" aria-label={`${option.label} 목록`}>
    <ul className="max-h-64 divide-y divide-line overflow-y-auto">
      {option.values.map(code => <li key={code} className="flex min-h-11 items-center gap-1 py-1">
        {editing === code ? <>
          <input autoFocus aria-label={`${option.label} ${code} 수정값`} className="field min-w-0 flex-1" value={replacement} maxLength={100}
            onChange={e => {setReplacement(e.target.value); setError("");}}
            onKeyDown={e => {if (e.nativeEvent.isComposing) return; if (e.key === "Enter") {e.preventDefault(); commit(code);} if (e.key === "Escape") {setEditing(null); setError("");}}}/>
          <button type="button" className="value-action text-brand-700" aria-label={`${option.label} ${code} 수정 완료`} onClick={() => commit(code)}><Check size={18}/></button>
          <button type="button" className="value-action" aria-label="수정 취소" onClick={() => {setEditing(null); setError("");}}><X size={18}/></button>
        </> : <>
          <span className="min-w-0 flex-1 break-all text-[15px] tabular-nums">{code}</span>
          {isColorOption(option) && <ColorAssignments option={option} onlyCode={code} onChange={colors => onChange({colors})}/>}
          <button type="button" className="value-action" title="수정" aria-label={`${option.label} ${code} 수정`} onClick={() => {setEditing(code); setReplacement(code); setError("");}}><Pencil size={16}/></button>
          <button type="button" className="value-action hover:text-danger" title="삭제" aria-label={`${option.label} ${code} 삭제`}
            onClick={() => {onChange({values: option.values.filter(v => v !== code)}); setError("");}}><Trash2 size={16}/></button>
        </>}
      </li>)}
    </ul>
    <div className="flex gap-2">
      <input className="field min-w-0 flex-1" aria-label={`${option.label} 추가값`} placeholder={`${option.label} 입력`} value={value} maxLength={100}
        onChange={e => {setValue(e.target.value); setError("");}}
        onKeyDown={e => {if (e.key === "Enter" && !e.nativeEvent.isComposing) {e.preventDefault(); commit(null);}}}/>
      <button type="button" className="btn btn-outline" aria-label={`${option.label} 값 추가`} disabled={!value.trim() || editing !== null} onClick={() => commit(null)}><Plus size={16}/>추가</button>
    </div>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
  </div>;
}
