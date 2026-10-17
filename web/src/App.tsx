import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { ApiClient } from './api/client'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { FamilyProvider } from './auth/FamilyContext'
import { FleetProvider } from './auth/FleetContext'
import { SosProvider } from './auth/SosContext'
import { Layout } from './components/Layout'
import { Loading } from './components/ui'
import { ActivityPage } from './pages/ActivityPage'
import { FamilyPage } from './pages/FamilyPage'
import { HealthPage } from './pages/HealthPage'
import { JoinPage } from './pages/JoinPage'
import { LoginPage } from './pages/LoginPage'
import { AlertsPage } from './pages/AlertsPage'
import { MapPage } from './pages/MapPage'
import { MessagesPage } from './pages/MessagesPage'
import { OverviewPage } from './pages/OverviewPage'
import { SettingsPage } from './pages/SettingsPage'
import { SosPage } from './pages/SosPage'

/** Hiding pages is only convenience: every request is authorised again by the API. */
function Protected() {
  const { state } = useAuth()
  if (state.status === 'loading') return <Loading label="Checking your session…" />
  if (state.status === 'anonymous') return <Navigate to="/login" replace />
  return (
    <FamilyProvider familyId={state.family.id}>
      <FleetProvider>
        <SosProvider>
          <Layout />
        </SosProvider>
      </FleetProvider>
    </FamilyProvider>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/join" element={<JoinPage />} />
      <Route element={<Protected />}>
        <Route index element={<OverviewPage />} />
        <Route path="map" element={<MapPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="family" element={<FamilyPage />} />
        <Route path="sos" element={<SosPage />} />
        <Route path="messages" element={<MessagesPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="manage" element={<Navigate to="/family" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export function App({ api }: { api: ApiClient }) {
  return (
    <BrowserRouter>
      <AuthProvider api={api}>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
