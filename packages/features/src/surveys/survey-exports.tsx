import { useMemo } from "react";
import {
  ApiError,
  type LeonAidApiClient,
  type SurveyExportJob,
} from "@leonaid/api-client";
import {
  SurveyExports,
  type ExportAdapter,
  type ExportMessages,
} from "@leonaid/surveys/exports";
import type {
  ExportJob,
  ExportProduct,
  Result,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/export-styles";

const messages: ExportMessages = {
  heading: "Auswertung exportieren",
  hint: "Die Dateien enthalten den angezeigten Stand mit den angewendeten Filtern. Später eingegangene Antworten sind darin nicht enthalten.",
  products: {
    responses_csv: "Einzelantworten · CSV",
    responses_xlsx: "Einzelantworten · Excel",
    analysis_xlsx: "Auswertung · Excel",
    analysis_pdf: "Auswertung · PDF",
  },
  statuses: {
    queued: "Export wartet",
    running: "Datei wird erstellt …",
    retrying: "Erstellung wird automatisch erneut versucht",
    completed: "Bereit zum Herunterladen",
    failed: "Datei konnte nicht erstellt werden",
    revoked: "Export ist nicht mehr verfügbar",
  },
  create: "Datei erstellen",
  retry: "Anfrage erneut senden",
  check: "Status erneut laden",
  download: "Herunterladen",
  busy: "Bitte warten …",
  unavailable:
    "Die Anfrage konnte nicht bestätigt werden. Bitte versuchen Sie es erneut.",
};
function job(value: SurveyExportJob): ExportJob {
  const status: Record<SurveyExportJob["status"], ExportJob["status"]> = {
    queued: "queued",
    processing: "running",
    retrying: "retrying",
    failed: "failed",
    available: "completed",
    cancelled: "revoked",
  };
  return {
    id: value.id,
    snapshotId: value.snapshotId,
    product: value.product,
    status: status[value.status],
    filename: value.filename,
    error: null,
  };
}
async function result<T>(request: () => Promise<T>): Promise<Result<T>> {
  try {
    return { ok: true, value: await request() };
  } catch (cause) {
    const status = cause instanceof ApiError ? cause.status : 0;
    return {
      ok: false,
      error: {
        code:
          status === 401
            ? "unauthenticated"
            : status === 403
              ? "forbidden"
              : status === 404
                ? "not_found"
                : status === 409
                  ? "idempotency_conflict"
                  : status >= 400 && status < 500
                    ? "invalid_response"
                    : "temporarily_unavailable",
        message:
          status === 401 || status === 403 || status === 404
            ? "Dieser Export ist für Sie nicht mehr zugänglich. Öffnen Sie die Umfrage erneut."
            : messages.unavailable,
        diagnostics: [],
      },
    };
  }
}
export function LeonAidSurveyExports({
  client,
  surveyId,
  snapshotId,
  canExportRaw,
  canExportReports,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  snapshotId: string;
  canExportRaw: boolean;
  canExportReports: boolean;
}) {
  const adapter = useMemo<ExportAdapter>(
    () => ({
      requestExport: (snapshotId, product, operationId, options) =>
        result(async () =>
          job(
            await client.createSurveyExport(
              surveyId,
              { snapshotId, product, operationId },
              options,
            ),
          ),
        ),
      exportStatus: (id, options) =>
        result(async () =>
          job(await client.getSurveyExport(surveyId, id, options)),
        ),
      download: (id, options) =>
        result(() => client.downloadSurveyExport(surveyId, id, options)),
    }),
    [client, surveyId],
  );
  const products: ExportProduct[] = [];
  if (canExportReports) products.push("analysis_xlsx", "analysis_pdf");
  if (canExportRaw) products.push("responses_csv", "responses_xlsx");
  return <SurveyExports {...{ snapshotId, adapter, products, messages }} />;
}
