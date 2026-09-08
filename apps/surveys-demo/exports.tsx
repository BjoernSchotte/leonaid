import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  SurveyExports,
  type ExportAdapter,
  type ExportMessages,
} from "@leonaid/surveys/exports";
import "@leonaid/surveys/export-styles";
import "./host.css";

const adapter: ExportAdapter = {
  async requestExport(snapshotId, product, operationId, options) {
    return (
      await fetch("/api/exports", {
        method: "POST",
        signal: options?.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshotId, product, operationId }),
      })
    ).json();
  },
  async exportStatus(id, options) {
    return (
      await fetch(`/api/exports/${encodeURIComponent(id)}`, {
        signal: options?.signal,
      })
    ).json();
  },
  async download(id, options) {
    const response = await fetch(
      `/api/exports/${encodeURIComponent(id)}/download`,
      { signal: options?.signal },
    );
    return response.ok
      ? { ok: true, value: await response.blob() }
      : response.json();
  },
};
const messages: ExportMessages = {
  heading: "Download your saved feedback",
  hint: "This independent host exports the saved revision selected when you opened this page.",
  products: {
    responses_csv: "Your feedback · CSV",
    responses_xlsx: "Feedback · Excel",
    analysis_xlsx: "Results · Excel",
    analysis_pdf: "Results · PDF",
  },
  statuses: {
    queued: "Waiting",
    running: "Preparing",
    retrying: "Will retry",
    completed: "Your file is ready",
    failed: "Creation failed",
    revoked: "Access ended",
  },
  create: "Prepare my file",
  retry: "Confirm the same request",
  check: "Check again",
  download: "Save my CSV",
  busy: "Working …",
  unavailable: "Connection interrupted. Try the same request again.",
};
function App() {
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/export-source", { signal: controller.signal })
      .then((r) => r.json())
      .then((result) => {
        if (controller.signal.aborted) return;
        if (result.ok) setSnapshotId(result.value.snapshotId);
        else setError(result.error.message);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("Unable to load saved feedback.");
      });
    return () => controller.abort();
  }, []);
  return (
    <main>
      <header>
        <h1>Independent feedback exports</h1>
        <a className="host-control" href="/">
          Return to feedback
        </a>
      </header>
      {error && <p role="alert">{error}</p>}
      {snapshotId && (
        <SurveyExports
          snapshotId={snapshotId}
          adapter={adapter}
          products={["responses_csv"]}
          messages={messages}
        />
      )}
    </main>
  );
}
createRoot(document.getElementById("app")!).render(<App />);
