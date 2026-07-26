import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { LeonAidApiClient } from "@leonaid/api-client";
import "@leonaid/ui/styles.css";

import { App } from "./app";
import "./pwa.css";

const queryClient = new QueryClient({
  defaultOptions: {
    mutations: { retry: false },
    queries: { refetchOnWindowFocus: false, retry: false },
  },
});
const apiClient = new LeonAidApiClient("");
const root = document.querySelector("#root");

if (!root) {
  throw new Error("LeonAid PWA root element fehlt");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App client={apiClient} />
    </QueryClientProvider>
  </StrictMode>,
);
