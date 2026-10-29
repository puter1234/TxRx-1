import { Navigate, Routes, Route, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { X } from "lucide-react";
import { connectWS } from "./lib/ws";
import { useApp } from "./lib/store";
import TopBar from "./components/TopBar";
import Home from "./screens/Home";
import SimpleStart from "./screens/SimpleStart";
import ConditionStart from "./screens/ConditionStart";
import Run from "./screens/Run";
import History from "./screens/History";
import Settings from "./screens/Settings";

function Legacy({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={to + location.search} replace />;
}

export default function App() {
  useEffect(connectWS, []);
  const error = useApp((s) => s.error);
  const clearError = useApp((s) => s.setError);
  return (
    <div className="flex h-full min-w-[1180px] flex-col overflow-hidden">
      <TopBar />
      <main className="min-h-0 flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/simple" element={<SimpleStart />} />
          <Route path="/condition" element={<ConditionStart />} />
          <Route path="/run" element={<Run />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/vision" element={<Navigate to="/simple?item=wappen" replace />} />
          <Route path="/condition/setup" element={<Navigate to="/condition" replace />} />
          <Route path="/condition/run" element={<Navigate to="/run" replace />} />
          <Route path="/equipment" element={<Legacy to="/settings" />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      {error && (
        <div
          role="alert"
          className="fixed left-1/2 top-24 z-[60] flex w-[min(94vw,1100px)] -translate-x-1/2 items-center gap-6 rounded-3xl border-4 border-danger bg-white p-6 shadow-2xl"
        >
          <p className="flex-1 text-[32px] font-black text-danger">{error}</p>
          <button className="btn btn-outline btn-lg" onClick={() => clearError("")} aria-label="닫기">
            <X size={36} strokeWidth={3} />
            닫기
          </button>
        </div>
      )}
    </div>
  );
}
