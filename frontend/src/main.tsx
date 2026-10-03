import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "./api/client";
import { pushToast } from "./components/Toast";
import App from "./App";
import "./styles/tokens.css";

// A failed read shows one toast (not one per poll). 401 is handled by the login screen.
let lastErr = { msg: "", at: 0 };
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
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
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
