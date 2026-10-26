import { useRef } from 'react'
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
import { OnboardingPage } from './pages/OnboardingPage'
import { OverviewPage } from './pages/OverviewPage'
import { SignupPage } from './pages/SignupPage'
import { SettingsPage } from './pages/SettingsPage'
import { SosPage } from './pages/SosPage'

import { LandingPage } from './pages/LandingPage'

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

function RootRoute() {
  const { state, api } = useAuth()
  const sessionFailedRef = useRef(false)

  if (!(api as any)._wrapped_restore) {
    ;(api as any)._wrapped_restore = true
    const origRestore = api.restore.bind(api)
    api.restore = async () => {
      const hadSession = api.hasSession
      const ok = await origRestore()
      if (!ok && hadSession) {
        sessionFailedRef.current = true
      }
      return ok
    }
  }

  if (state.status === 'loading') return <Loading label="Checking your session…" />
  if (state.status === 'anonymous') {
    if (state.notice || sessionFailedRef.current) return <Navigate to="/login" replace />
    return <LandingPage />
  }
  return <Protected />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/landing" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/join" element={<JoinPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/" element={<RootRoute />}>
        <Route index element={<OverviewPage />} />
      </Route>
      <Route element={<Protected />}>
        <Route path="map" element={<MapPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="family" element={<FamilyPage />} />
        <Route path="sos" element={<SosPage />} />
        <Route path="messages" element={<MessagesPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="welcome" element={<OnboardingPage />} />
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
