import { useEffect, useRef, useState } from "react";
import type {
  AnalysisAdapter,
  ExportJob,
  ExportProduct,
  Result,
} from "./contracts";

export type ExportAdapter = Pick<
  AnalysisAdapter,
  "requestExport" | "exportStatus" | "download"
>;
export interface ExportMessages {
  heading: string;
  hint: string;
  products: Record<ExportProduct, string>;
  statuses: Record<ExportJob["status"], string>;
  create: string;
  retry: string;
  check: string;
  download: string;
  busy: string;
  unavailable: string;
}
const defaults: ExportMessages = {
  heading: "Export this result",
  hint: "Files use the displayed result, including its filters and capture time.",
  products: {
    responses_csv: "Responses · CSV",
    responses_xlsx: "Responses · Excel",
    analysis_xlsx: "Analysis · Excel",
    analysis_pdf: "Analysis · PDF",
  },
  statuses: {
    queued: "Queued",
    running: "Creating file",
    retrying: "Retry scheduled",
    completed: "Ready to download",
    failed: "Export failed",
    revoked: "Export no longer available",
  },
  create: "Create file",
  retry: "Retry request",
  check: "Check status again",
  download: "Download",
  busy: "Please wait …",
  unavailable: "The request could not be confirmed. Please try again.",
};

/** Host supplies authorization, credentials and translated copy. Never stores response blobs. */
export function SurveyExports({
  snapshotId,
  adapter,
  products,
  messages = defaults,
}: {
  snapshotId: string;
  adapter: ExportAdapter;
  products: readonly ExportProduct[];
  messages?: ExportMessages;
}) {
  if (!products.length) return null;
  return (
    <section className="survey-exports" aria-label={messages.heading}>
      <h3>{messages.heading}</h3>
      <p>{messages.hint}</p>
      <ul>
        {products.map((product) => (
          <ExportRow
            key={`${snapshotId}:${product}`}
            {...{ snapshotId, adapter, product, messages }}
          />
        ))}
      </ul>
    </section>
  );
}

function ExportRow({
  snapshotId,
  product,
  adapter,
  messages: m,
}: {
  snapshotId: string;
  product: ExportProduct;
  adapter: ExportAdapter;
  messages: ExportMessages;
}) {
  const [job, setJob] = useState<ExportJob | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [denied, setDenied] = useState(false);
  const operation = useRef<string | null>(null);
  const inFlight = useRef(false);
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, [adapter]);

  function accept<T>(result: Result<T>): T | null {
    if (result.ok) return result.value;
    setError(result.error.message);
    if (
      [
        "unauthenticated",
        "forbidden",
        "not_found",
        "closed",
        "access_expired",
      ].includes(result.error.code)
    ) {
      setJob(null);
      setDenied(true);
      operation.current = null;
      setUncertain(false);
    }
    return null;
  }

  const active = job && ["queued", "running", "retrying"].includes(job.status);
  useEffect(() => {
    if (!job || !active || error || denied) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void adapter
        .exportStatus(job.id, { signal: controller.signal })
        .then((result) => {
          if (controller.signal.aborted) return;
          const value = accept(result);
          if (value) setJob(value);
        })
        .catch(() => {
          if (!controller.signal.aborted) setError(m.unavailable);
        });
    }, 1000);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [adapter, job, active, error, denied, m.unavailable]);

  async function create() {
    if (inFlight.current || denied) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    operation.current ??= crypto.randomUUID();
    const signal = lifetime.current!.signal;
    try {
      const result = await adapter.requestExport(
        snapshotId,
        product,
        operation.current,
        { signal },
      );
      if (signal.aborted) return;
      const value = accept(result);
      if (value) {
        setJob(value);
        operation.current = null;
        setUncertain(false);
      } else if (!result.ok && result.error.code === "temporarily_unavailable")
        setUncertain(true);
      else {
        operation.current = null;
        setUncertain(false);
      }
    } catch {
      if (!signal.aborted) {
        setError(m.unavailable);
        setUncertain(true);
      }
    } finally {
      inFlight.current = false;
      if (!signal.aborted) setBusy(false);
    }
  }

  async function download() {
    if (!job || inFlight.current || denied) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    const signal = lifetime.current!.signal;
    try {
      const result = await adapter.download(job.id, { signal });
      if (signal.aborted) return;
      const blob = accept(result);
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download =
        job.filename ||
        `${product}.${product.endsWith("csv") ? "csv" : product.endsWith("pdf") ? "pdf" : "xlsx"}`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      if (!signal.aborted) setError(m.unavailable);
    } finally {
      inFlight.current = false;
      if (!signal.aborted) setBusy(false);
    }
  }

  return (
    <li aria-label={m.products[product]}>
      <div>
        <strong>{m.products[product]}</strong>
        {job && <p role="status">{m.statuses[job.status]}</p>}
        {error && <p role="alert">{error}</p>}
      </div>
      {!denied && (
        <div className="survey-exports-actions">
          {(!job || job.status === "failed") && (
            <button type="button" disabled={busy} onClick={() => void create()}>
              {busy ? m.busy : uncertain ? m.retry : m.create}
            </button>
          )}
          {active && error && (
            <button type="button" onClick={() => setError("")}>
              {m.check}
            </button>
          )}
          {job?.status === "completed" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void download()}
            >
              {busy ? m.busy : m.download}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
