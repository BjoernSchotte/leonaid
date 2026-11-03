import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { LeonAidApiClient } from "@leonaid/api-client";
import { ErrorBoundary } from "@leonaid/ui";
import "@leonaid/ui/styles.css";

import { App } from "./app";
import "./pwa.css";

const queryClient = new QueryClient({
  defaultOptions: {
    // Offline, TanStack would pause a save until the network returns and
    // send it later. LeonAid does not save in the background (the offline
    // banner says so), so a save fails at once and the form keeps its input.
    mutations: { networkMode: "always", retry: false },
    queries: { refetchOnWindowFocus: false, retry: false },
  },
});
const apiClient = new LeonAidApiClient("");
const root = document.querySelector("#root");

if (!root) {
  throw new Error("LeonAid PWA root element missing");
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App client={apiClient} />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
