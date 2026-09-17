import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export default function Modal({
  title,
  children,
  onClose,
  width,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  width?: string
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/50 p-6" onClick={onClose}>
      <div className={'card w-full p-6 ' + (width ?? 'max-w-lg')} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-xl font-extrabold">{title}</h3>
          <button className="rounded-lg p-2 hover:bg-panel" onClick={onClose} aria-label="닫기">
            <X size={24} />
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  )
}
