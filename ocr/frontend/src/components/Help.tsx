import { useId, useState } from "react";
export default function Help({
  text,
  label = "도움말",
}: {
  text: string;
  label?: string;
}) {
  const id = useId(),
    [open, setOpen] = useState(false);
  return (
    <span
      className="relative ml-auto inline-flex shrink-0"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            setOpen(false);
          }
        }}
        className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-line bg-white text-xl font-bold text-ink-900"
      >
        i
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute right-0 top-full z-40 mt-2 w-80 max-w-[80vw] rounded-xl border-2 border-line bg-white p-4 text-left text-lg font-semibold leading-relaxed text-ink-900 shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}
