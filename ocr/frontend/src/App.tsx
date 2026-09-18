import { Routes, Route } from "react-router-dom";
import { useEffect } from "react";
import { connectWS } from "./lib/ws";
import { useApp } from "./lib/store";
import TopBar from "./components/TopBar";
import Home from "./screens/Home";
import SimpleCount from "./screens/SimpleCount";
import ConditionWizard from "./screens/ConditionWizard";
import ConditionRun from "./screens/ConditionRun";
import Equipment from "./screens/Equipment";
import History from "./screens/History";
import Settings from "./screens/Settings";

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
          <Route path="/simple" element={<SimpleCount />} />
          <Route path="/condition/setup" element={<ConditionWizard />} />
          <Route path="/condition/run" element={<ConditionRun />} />
          <Route path="/equipment" element={<Equipment />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
      {error && (
        <div
          role="alert"
          className="fixed top-20 left-1/2 z-50 flex w-[min(92vw,960px)] -translate-x-1/2 items-center gap-5 rounded-xl border-2 border-danger bg-white p-5 shadow-xl"
        >
          <p className="flex-1 text-xl font-bold text-danger">{error}</p>
          <button className="btn btn-outline" onClick={() => clearError("")}>
            닫기
          </button>
        </div>
      )}
    </div>
  );
}
