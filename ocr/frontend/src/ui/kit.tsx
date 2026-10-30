import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, Delete, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export function Screen({
  title,
  onBack,
  backLabel = "처음",
  right,
  children,
  footer,
}: {
  title: ReactNode;
  onBack?: () => void;
  backLabel?: string;
  right?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-6 px-8 pb-4 pt-6">
        {onBack && (
          <button className="btn btn-outline btn-lg" onClick={onBack}>
            <ArrowLeft size={36} strokeWidth={3} />
            {backLabel}
          </button>
        )}
        <h1 className="min-w-0 truncate text-[44px] font-black leading-tight">{title}</h1>
        {right && <div className="ml-auto flex shrink-0 items-center gap-4">{right}</div>}
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto px-8 pb-6">{children}</main>
      {footer && (
        <footer className="flex shrink-0 items-center gap-5 border-t-2 border-line bg-white px-8 py-5">
          {footer}
        </footer>
      )}
    </div>
  );
}

export function Tile({
  icon: Icon,
  label,
  status,
  onClick,
  disabled,
  selected,
  className = "",
}: {
  icon?: LucideIcon;
  label: string;
  status?: string;
  onClick: () => void;
  disabled?: boolean;
  selected?: boolean;
  className?: string;
}) {
  return (
    <button
      className={"tile min-h-[380px] p-8 " + className}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
    >
      {Icon && <Icon size={128} strokeWidth={1.75} className="text-brand-700" aria-hidden="true" />}
      <span className="text-[64px] font-black leading-none">{label}</span>
      {status && <span className="text-[28px] font-extrabold text-danger">{status}</span>}
    </button>
  );
}

export function Sheet({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: ReactNode;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const heading = useId();
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    return () => prior?.focus();
  }, []);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/60 p-6" onClick={onClose}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading}
        tabIndex={-1}
        className={"card max-h-[92vh] w-full overflow-y-auto p-8 " + (wide ? "max-w-5xl" : "max-w-3xl")}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            close.current();
          }
        }}
      >
        <div className="flex items-center gap-4">
          <h2 id={heading} className="text-[40px] font-black leading-tight">
            {title}
          </h2>
          <button className="btn btn-quiet btn-lg ml-auto !px-5" onClick={onClose} aria-label="닫기">
            <X size={40} strokeWidth={3} />
          </button>
        </div>
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}

// Confirmation inside the app, with large buttons, instead of the browser's own small dialog.
export function useConfirm() {
  const [ask, setAsk] = useState<{ title: string; action: string; resolve: (ok: boolean) => void } | null>(null);
  const answer = (ok: boolean) => {
    ask?.resolve(ok);
    setAsk(null);
  };
  const confirm = (title: string, action: string) =>
    new Promise<boolean>((resolve) => setAsk({ title, action, resolve }));
  const dialog = ask && (
    <Sheet title={ask.title} onClose={() => answer(false)}>
      <div className="grid grid-cols-2 gap-5">
        <button className="btn btn-danger btn-xl" onClick={() => answer(true)}>{ask.action}</button>
        <button className="btn btn-outline btn-xl" onClick={() => answer(false)}>취소</button>
      </div>
    </Sheet>
  );
  return { confirm, dialog };
}

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];

export function Keypad({ onKey, disabled }: { onKey: (key: string) => void; disabled?: boolean }) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {KEYS.map((k) => (
        <button
          key={k}
          type="button"
          disabled={disabled}
          aria-label={k === "back" ? "한 글자 지우기" : k === "clear" ? "모두 지우기" : k}
          className="btn btn-outline !min-h-[96px] text-[40px] font-black"
          onClick={() => onKey(k)}
        >
          {k === "clear" ? "지움" : k === "back" ? <Delete size={44} /> : k}
        </button>
      ))}
    </div>
  );
}

export const typed = (value: string, key: string, limit: number) =>
  key === "clear" ? "" : key === "back" ? value.slice(0, -1) : (value + key).replace(/^0+/, "").slice(0, limit);

export function NumberSheet({
  title,
  initial,
  max,
  onDone,
  onClose,
}: {
  title: string;
  initial?: number | null;
  max: number;
  onDone: (value: number) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(initial ? String(initial) : "");
  const value = Number(text);
  const valid = Number.isInteger(value) && value >= 1 && value <= max;
  return (
    <Sheet title={title} onClose={onClose}>
      <output
        aria-label="입력한 수량"
        className="mb-6 block rounded-2xl border-4 border-ink-700 bg-white py-4 text-center text-[88px] font-black tabular-nums leading-none"
      >
        {text || "0"}
      </output>
      <Keypad onKey={(k) => setText((t) => typed(t, k, String(max).length))} />
      <button className="btn btn-primary btn-xl mt-6 w-full" disabled={!valid} onClick={() => onDone(value)}>
        확인
      </button>
    </Sheet>
  );
}

export const QUICK_TARGETS = [20, 40, 60, 100];

export function QuantityPicker({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  const [custom, setCustom] = useState(false);
  const isCustom = value !== null && !QUICK_TARGETS.includes(value);
  return (
    <section aria-labelledby="quantity-title">
      <h2 id="quantity-title" className="mb-5 text-[36px] font-black">
        목표 수량
      </h2>
      <div role="group" aria-labelledby="quantity-title" className="flex flex-wrap gap-4">
        <button className="choice !min-h-[124px] min-w-[240px] !text-[40px]" aria-pressed={value === null} onClick={() => onChange(null)}>
          제한 없음
        </button>
        {QUICK_TARGETS.map((n) => (
          <button key={n} className="choice !min-h-[124px] min-w-[180px] !text-[44px] tabular-nums" aria-pressed={value === n} onClick={() => onChange(n)}>
            {n}
          </button>
        ))}
        <button className="choice !min-h-[124px] min-w-[240px] !text-[40px] tabular-nums" aria-pressed={isCustom} onClick={() => setCustom(true)}>
          {isCustom ? value : "직접 입력"}
        </button>
      </div>
      {custom && (
        <NumberSheet
          title="목표 수량"
          initial={isCustom ? value : null}
          max={1000000}
          onClose={() => setCustom(false)}
          onDone={(v) => {
            onChange(v);
            setCustom(false);
          }}
        />
      )}
    </section>
  );
}

export function Notice({ tone = "danger", children }: { tone?: "danger" | "warn" | "ok"; children: ReactNode }) {
  const colors = {
    danger: "border-danger bg-danger-bg text-danger",
    warn: "border-warn bg-warn-bg text-ink-900",
    ok: "border-ok bg-ok-bg text-ok",
  }[tone];
  return (
    <p role={tone === "danger" ? "alert" : "status"} className={"rounded-2xl border-2 px-6 py-4 text-[28px] font-extrabold " + colors}>
      {children}
    </p>
  );
}
