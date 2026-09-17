import { Routes, Route } from 'react-router-dom'
import TopBar from './components/TopBar'
import Home from './screens/Home'
import SimpleCount from './screens/SimpleCount'
import ConditionWizard from './screens/ConditionWizard'
import ConditionRun from './screens/ConditionRun'
import Equipment from './screens/Equipment'
import History from './screens/History'
import Settings from './screens/Settings'

export default function App() {
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
    </div>
  )
}
