import { useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import ErrorBoundary from "./components/ErrorBoundary";
import Login from "./components/Login";
import Sidebar from "./components/Sidebar";
import Placeholder from "./pages/Placeholder";
import ProfilePage from "./pages/ProfilePage";
import OfferMapPage from "./pages/OfferMapPage";
import CampaignsPage from "./pages/CampaignsPage";
import RunsPage from "./pages/RunsPage";
import ActivityPage from "./pages/ActivityPage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";
import OutboxPage from "./pages/OutboxPage";
import RepliesPage from "./pages/RepliesPage";
import DashboardPage from "./pages/DashboardPage";
import CompaniesPage from "./pages/CompaniesPage";
import LeadsPage from "./pages/LeadsPage";
import UsagePage from "./pages/UsagePage";
import DncPage from "./pages/DncPage";
import CommandPalette from "./components/CommandPalette";
import LogDock from "./components/LogDock";
import { ToastProvider } from "./components/Toast";

const real: Record<string, JSX.Element> = {
  "/": <DashboardPage />, "/companies": <CompaniesPage />, "/leads": <LeadsPage />, "/usage": <UsagePage />, "/do-not-contact": <DncPage />,
  "/profile": <ProfilePage />, "/offer-map": <OfferMapPage />, "/campaigns": <CampaignsPage />, "/runs": <RunsPage />,
  "/activity": <ActivityPage />, "/review": <ReviewPage />, "/settings": <SettingsPage />,
  "/outbox": <OutboxPage />, "/replies": <RepliesPage />,
};
import { nav } from "./nav";

export default function App() {
  const [locked, setLocked] = useState(false);
  const qc = useQueryClient();
  const { pathname } = useLocation();
  useEffect(() => {
    const h = () => setLocked(true);
    window.addEventListener("auth-required", h);
    return () => window.removeEventListener("auth-required", h);
  }, []);
  if (locked) return <Login onDone={() => { setLocked(false); qc.invalidateQueries(); }} />;
  return (
    <ToastProvider>
    <div className="flex h-full">
      <Sidebar />
      <CommandPalette />
      <div className="flex min-w-0 flex-1 flex-col">
      <main className="min-h-0 flex-1">
        <ErrorBoundary resetKey={pathname}>
        <Routes>
          {nav.flatMap((g) => g.items).map((i) => (
            <Route key={i.path} path={i.path} element={real[i.path] ?? <Placeholder />} />
          ))}
          <Route path="*" element={<Placeholder />} />
        </Routes>
        </ErrorBoundary>
      </main>
      <LogDock />
      </div>
    </div>
    </ToastProvider>
  );
}
