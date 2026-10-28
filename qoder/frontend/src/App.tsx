import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { Overview } from '@/pages/Overview'
import { Library } from '@/pages/Library'
import { Experiments } from '@/pages/Experiments'
import { AIResearch } from '@/pages/AIResearch'
import { Memory } from '@/pages/Memory'
import { Reports } from '@/pages/Reports'
import { Settings } from '@/pages/Settings'
import { useApp } from '@/state/AppContext'

export function App() {
  const { currentProjectId } = useApp()
  return (
    <AppLayout>
      <Routes key={currentProjectId}>
        <Route path="/" element={<Overview />} />
        <Route path="/library" element={<Library />} />
        <Route path="/experiments" element={<Experiments />} />
        <Route path="/research" element={<AIResearch />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  )
}
