import { useNavigate } from "react-router-dom";
import { FileClock, Layers, ScanBarcode, Settings, Play, RotateCcw } from "lucide-react";
import { useApp } from "../lib/store";
import { ended } from "../lib/station";
import { jobTitle, phaseView, TONE_BAR, useRedo } from "../lib/jobs";
import { Tile } from "../ui/kit";

export default function Home() {
  const nav = useNavigate();
  const session = useApp((s) => s.snapshot?.session);
  const resetWizard = useApp((s) => s.resetWizard);
  const active = !ended(session);
  const view = session ? phaseView(session.phase) : null;
  const redo = useRedo();
  // A restart ends the job for safety; its count stays visible until the next job.
  const stopped = session?.phase === "ABORTED" && session.fault === "PROCESS_RESTART" ? session : null;
  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1 flex-col justify-center gap-8 overflow-y-auto px-10 py-8">
        {active && session && view && (
          <section aria-label="진행 중인 작업" className="card flex items-center gap-8 border-4 border-brand-700 p-8">
            <span className={"rounded-2xl px-6 py-3 text-[32px] font-black " + TONE_BAR[view.tone]}>{view.label}</span>
            <div className="min-w-0">
              <p className="truncate text-[48px] font-black leading-tight">{jobTitle(session)}</p>
              <p className="text-[36px] font-extrabold tabular-nums text-ink-700">
                {session.count}
                {session.recipe.target_count ? ` / ${session.recipe.target_count}` : ""}개
              </p>
            </div>
            <button className="btn btn-go btn-xl ml-auto" onClick={() => nav("/run")}>
              <Play size={44} strokeWidth={3} />
              이어서 하기
            </button>
          </section>
        )}
        {stopped && (
          <section aria-label="중단된 작업" className="card flex items-center gap-8 border-4 border-warn p-8">
            <span className="rounded-2xl bg-warn px-6 py-3 text-[32px] font-black text-ink-900">중단됨</span>
            <div className="min-w-0">
              <p className="truncate text-[48px] font-black leading-tight">{jobTitle(stopped)}</p>
              <p className="text-[36px] font-extrabold tabular-nums text-ink-700">
                {stopped.count}
                {stopped.recipe.target_count ? ` / ${stopped.recipe.target_count}` : ""}개
              </p>
            </div>
            <button className="btn btn-primary btn-xl ml-auto" onClick={() => redo(stopped, !!stopped.recipe.test_run)}>
              <RotateCcw size={44} strokeWidth={3} />
              다시 하기
            </button>
          </section>
        )}
        <div className="grid grid-cols-2 gap-8">
          <Tile icon={Layers} label="단순 계수" disabled={active} onClick={() => nav("/simple")} />
          <Tile
            icon={ScanBarcode}
            label="조건 계수"
            disabled={active}
            onClick={() => {
              resetWizard();
              nav("/condition");
            }}
          />
        </div>
      </div>
      <nav className="flex shrink-0 items-center justify-center gap-6 border-t-2 border-line bg-white px-8 py-5">
        <button className="btn btn-outline btn-lg min-w-[280px]" onClick={() => nav("/history")}>
          <FileClock size={36} />
          작업 기록
        </button>
        <button className="btn btn-outline btn-lg min-w-[280px]" onClick={() => nav("/settings")}>
          <Settings size={36} />
          설정
        </button>
      </nav>
    </div>
  );
}
