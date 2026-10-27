import { lazy, Suspense, useRef } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ApiClient } from "./api/client";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { FamilyProvider } from "./auth/FamilyContext";
import { FleetProvider } from "./auth/FleetContext";
import { SosProvider } from "./auth/SosContext";
import { Loading } from "./components/ui";
import { JoinPage } from "./pages/JoinPage";
import { LoginPage } from "./pages/LoginPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { SignupPage } from "./pages/SignupPage";

import { LandingPage } from "./pages/LandingPage";

// The dashboard (maps, charts, all signed-in pages) loads only after sign-in, so the public pages stay small.
const ActivityPage = lazy(() =>
  import("./pages/ActivityPage").then((m) => ({ default: m.ActivityPage })),
);
const FamilyPage = lazy(() =>
  import("./pages/FamilyPage").then((m) => ({ default: m.FamilyPage })),
);
const HealthPage = lazy(() =>
  import("./pages/HealthPage").then((m) => ({ default: m.HealthPage })),
);
const AlertsPage = lazy(() =>
  import("./pages/AlertsPage").then((m) => ({ default: m.AlertsPage })),
);
const MapPage = lazy(() =>
  import("./pages/MapPage").then((m) => ({ default: m.MapPage })),
);
const MessagesPage = lazy(() =>
  import("./pages/MessagesPage").then((m) => ({ default: m.MessagesPage })),
);
const OnboardingPage = lazy(() =>
  import("./pages/OnboardingPage").then((m) => ({ default: m.OnboardingPage })),
);
const OverviewPage = lazy(() =>
  import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);
const SosPage = lazy(() =>
  import("./pages/SosPage").then((m) => ({ default: m.SosPage })),
);
const Layout = lazy(() =>
  import("./components/Layout").then((m) => ({ default: m.Layout })),
);

/** Hiding pages is only convenience: every request is authorised again by the API. */
function Protected() {
  const { state } = useAuth();
  if (state.status === "loading")
    return <Loading label="Checking your session…" />;
  if (state.status === "anonymous") return <Navigate to="/login" replace />;
  return (
    <FamilyProvider familyId={state.family.id}>
      <FleetProvider>
        <SosProvider>
          <Layout />
        </SosProvider>
      </FleetProvider>
    </FamilyProvider>
  );
}

function RootRoute() {
  const { state, api } = useAuth();
  const sessionFailedRef = useRef(false);

  if (!(api as any)._wrapped_restore) {
    (api as any)._wrapped_restore = true;
    const origRestore = api.restore.bind(api);
    api.restore = async () => {
      const hadSession = api.hasSession;
      const ok = await origRestore();
      if (!ok && hadSession) {
        sessionFailedRef.current = true;
      }
      return ok;
    };
  }

  if (state.status === "loading")
    return <Loading label="Checking your session…" />;
  if (state.status === "anonymous") {
    if (state.notice || sessionFailedRef.current)
      return <Navigate to="/login" replace />;
    return <LandingPage />;
  }
  return <Protected />;
}

export function AppRoutes() {
  return (
    <Suspense fallback={<Loading label="Loading…" />}>
      <Routes>
        <Route path="/landing" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/join" element={<JoinPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
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
    </Suspense>
  );
}

export function App({ api }: { api: ApiClient }) {
  return (
    <BrowserRouter>
      <AuthProvider api={api}>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
