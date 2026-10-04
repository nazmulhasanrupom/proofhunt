import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryCache, QueryClient, QueryClientProvider, hashKey } from "@tanstack/react-query";
import { ApiError, getActiveProfile } from "./api/client";
import { pushToast } from "./components/Toast";
import { ProfileProvider } from "./lib/profile";
import App from "./App";
import "./styles/tokens.css";

// A failed read shows one toast (not one per poll). 401 is handled by the login screen.
let lastErr = { msg: "", at: 0 };
// The same page asks the same question for every profile. Cache each answer per profile, so one profile never shows
// another profile's data, not even for a moment. These keys are the same for every profile.
const SHARED_KEYS = new Set(["profiles", "settings", "sending-status", "dnc", "usage"]);
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1, refetchOnWindowFocus: false,
      queryKeyHashFn: (key) => hashKey(SHARED_KEYS.has(String(key[0])) ? key : [getActiveProfile(), ...key]),
    },
  },
  queryCache: new QueryCache({
    onError: (e) => {
      if (e instanceof ApiError && e.status === 401) return;
      if (e.message === lastErr.msg && Date.now() - lastErr.at < 30000) return;
      lastErr = { msg: e.message, at: Date.now() };
      pushToast(e.message, true);
    },
  }),
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ProfileProvider>
          <App />
        </ProfileProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
