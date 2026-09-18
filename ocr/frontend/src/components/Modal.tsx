import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export default function Modal({
  title,
  children,
  onClose,
  width,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  width?: string;
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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/50 p-6"
      onClick={onClose}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading}
        tabIndex={-1}
        className={
          "card max-h-[90vh] w-full overflow-y-auto p-6 " +
          (width ?? "max-w-lg")
        }
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            close.current();
            return;
          }
          if (e.key !== "Tab") return;
          const nodes = Array.from(
            panel.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]',
            ) || [],
          );
          const first = nodes[0],
            last = nodes[nodes.length - 1];
          if (!first) {
            e.preventDefault();
            return;
          }
          if (
            e.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === panel.current)
          ) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }}
      >
        <div className="flex items-center justify-between">
          <h3 id={heading} className="text-xl font-extrabold">
            {title}
          </h3>
          <button
            className="min-h-11 min-w-11 rounded-lg p-2 hover:bg-panel"
            onClick={onClose}
            aria-label="닫기"
          >
            <X size={24} />
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
