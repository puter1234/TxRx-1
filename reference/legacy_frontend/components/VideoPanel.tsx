export default function VideoPanel() {
  return (
    <div className="card shrink-0 overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h3 className="text-lg font-bold">실시간 영상</h3>
        <span className="flex items-center gap-2 text-sm font-bold text-danger">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-danger" />
          LIVE
        </span>
      </div>
      <img src="/stream" className="aspect-video w-full bg-ink-900 object-cover" alt="실시간 영상" />
    </div>
  )
}
