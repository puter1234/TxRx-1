import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Layers,
  Zap,
  CircleSlash,
  Tag,
  Hash,
  Ruler,
  Palette,
  FolderOpen,
  FileClock,
  Wrench,
  Settings,
  Power,
  ChevronRight,
  ScanBarcode,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useApp } from "../lib/store";
import Modal from "../components/Modal";
import { ended } from "../lib/station";

function Feature({ icon: Icon, text }: { icon: LucideIcon; text: string }) {
  return (
    <li className="flex items-center gap-3 text-lg font-semibold text-ink-700">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-panel text-brand-600">
        <Icon size={20} />
      </span>
      {text}
    </li>
  );
}

function NavBtn({
  icon: Icon,
  label,
  danger,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={
        "btn " +
        (danger
          ? "btn-outline hover:!border-danger hover:!text-danger"
          : "btn-outline")
      }
      onClick={onClick}
    >
      <Icon size={22} /> {label}
    </button>
  );
}

export default function Home() {
  const nav = useNavigate();
  const resetWizard = useApp((s) => s.resetWizard);
  const [exitOpen, setExitOpen] = useState(false);
  const session = useApp((s) => s.snapshot?.session);

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-8 overflow-y-auto px-8 py-6">
        <div className="text-center">
          <h1 className="text-4xl font-extrabold">계수 방식을 선택하세요</h1>
          {!ended(session) && (
            <button
              className="btn btn-primary mt-5"
              onClick={() =>
                nav(
                  session?.recipe.kind === "simple"
                    ? "/simple"
                    : "/condition/run",
                )
              }
            >
              진행 중인 작업 열기
            </button>
          )}
        </div>

        <div className="grid w-full max-w-5xl grid-cols-2 gap-6">
          <div className="card flex flex-col p-8">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
              <Layers size={30} />
            </div>
            <h2 className="mt-5 text-3xl font-extrabold">단순 계수</h2>

            <ul className="mt-6 space-y-3">
              <Feature icon={Layers} text="전체 수량 계수" />
              <Feature icon={Zap} text="빠른 시작" />
              <Feature icon={CircleSlash} text="조건 없음" />
            </ul>
            <div className="flex-1" />
            <button
              className="btn btn-primary btn-lg mt-8 w-full"
              disabled={!ended(session)}
              onClick={() => nav("/simple")}
            >
              단순 계수 시작 <ChevronRight size={24} />
            </button>
          </div>

          <div className="card flex flex-col p-8">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
              <ScanBarcode size={30} />
            </div>
            <h2 className="mt-5 text-3xl font-extrabold">조건 계수</h2>

            <ul className="mt-6 space-y-3">
              <Feature icon={Tag} text="브랜드" />
              <Feature icon={Hash} text="품번" />
              <Feature icon={Ruler} text="사이즈" />
              <Feature icon={Palette} text="색상" />
            </ul>
            <div className="flex-1" />
            <button
              className="btn btn-primary btn-lg mt-8 w-full"
              disabled={!ended(session)}
              onClick={() => {
                resetWizard();
                nav("/condition/setup");
              }}
            >
              조건 설정 <ChevronRight size={24} />
            </button>
          </div>
        </div>
      </div>

      <nav className="flex shrink-0 items-center justify-center gap-3 border-t border-line bg-white px-6 py-4">
        <NavBtn
          icon={FolderOpen}
          label="이전 작업 불러오기"
          onClick={() => nav("/history?load=1")}
        />
        <NavBtn
          icon={FileClock}
          label="작업 기록"
          onClick={() => nav("/history")}
        />
        <NavBtn
          icon={Wrench}
          label="장비 점검"
          onClick={() => nav("/equipment")}
        />
        <NavBtn
          icon={Settings}
          label="환경 설정"
          onClick={() => nav("/settings")}
        />
        <NavBtn
          icon={Power}
          label="종료"
          danger
          onClick={() => setExitOpen(true)}
        />
      </nav>

      {exitOpen && (
        <Modal title="시스템 종료" onClose={() => setExitOpen(false)}>
          <p className="text-lg font-semibold text-ink-700">
            자동 계수 시스템을 종료하시겠습니까?
          </p>
          <div className="mt-6 grid grid-cols-2 gap-3">
            <button
              className="btn btn-outline"
              onClick={() => setExitOpen(false)}
            >
              취소
            </button>
            <button
              className="btn btn-danger"
              onClick={() => {
                setExitOpen(false);
                if (!ended(session)) {
                  useApp
                    .getState()
                    .setError("진행 중인 작업을 종료한 후 창을 닫으세요.");
                  return;
                }
                window.close();
                setTimeout(() => {
                  if (!window.closed)
                    useApp
                      .getState()
                      .setError("창의 닫기 버튼을 눌러 닫으세요.");
                }, 200);
              }}
            >
              <Power size={22} /> 종료
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
