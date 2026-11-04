import { useMutation } from "@tanstack/react-query";
import { FlaskConical, Info, Search } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  Button,
  DetailProps,
  Field,
  Icon,
  Input,
  StatusLabel,
  StatusMessage,
} from "@leonaid/ui";

import {
  actionErrorMessage,
  type ActionErrorMessage,
} from "../action-admin/errors";
import { formatDateTime } from "../shared/dates";

/**
 * "Support-Code nachschlagen": the technical outcome of one request
 * (route, status, release), never its content.
 */
export function SupportDiagnosticsPanel({
  client,
}: {
  readonly client: LeonAidApiClient;
}) {
  const [supportCode, setSupportCode] = useState("");
  const [probeError, setProbeError] = useState<ActionErrorMessage>();
  const [lookupError, setLookupError] = useState<ActionErrorMessage>();
  const probe = useMutation({
    mutationFn: () => client.runSupportProbe(),
    onError: (error) => {
      // The probe fails on purpose; its support code is the example.
      if (error instanceof ApiError) setSupportCode(error.detail.requestId);
      setProbeError(actionErrorMessage(error));
    },
  });
  const lookup = useMutation({
    mutationFn: (code: string) => client.getSupportRequestDiagnostic(code),
    onError: (error) => setLookupError(actionErrorMessage(error)),
  });

  function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = supportCode.trim();
    if (!normalized) return;
    setLookupError(undefined);
    lookup.mutate(normalized);
  }

  const result = lookup.data;

  return (
    <section
      aria-labelledby="support-diagnostics-title"
      className="panel"
      data-testid="support-diagnostics"
      id="support"
    >
      <header className="panel-header">
        <h2 id="support-diagnostics-title">Support-Code nachschlagen</h2>
        <Button
          data-testid="support-probe"
          icon={FlaskConical}
          loading={probe.isPending}
          onClick={() => {
            probe.reset();
            lookup.reset();
            setProbeError(undefined);
            setLookupError(undefined);
            probe.mutate();
          }}
          size="sm"
          variant="ghost"
        >
          Diagnose-Test starten
        </Button>
      </header>
      <div className="panel-pad stack">
        <p className="small muted">
          Ein Support-Code zeigt nur technischen Ausgang, Route und Release.
          Formulardaten, Namen, E-Mails und Dokumente bleiben unsichtbar.
        </p>
        {probeError ? (
          <div className="callout" role="status">
            <Icon icon={Info} size={16} />
            <span>
              <strong>Kontrollierter Fehler wurde erzeugt.</strong>{" "}
              {probeError.message}
            </span>
          </div>
        ) : null}
        <form className="support-form" onSubmit={submitLookup}>
          <Field
            hint="Den vollständigen Code aus der Fehlermeldung einfügen; er enthält keine fachlichen Daten."
            label="Support-Code"
          >
            <Input
              autoComplete="off"
              className="mono"
              id="support-code"
              maxLength={128}
              minLength={8}
              onChange={(event) => setSupportCode(event.target.value)}
              placeholder="z. B. 52f2f7c8-…"
              spellCheck={false}
              value={supportCode}
            />
          </Field>
          <Button
            data-testid="support-lookup"
            disabled={supportCode.trim().length < 8}
            icon={Search}
            loading={lookup.isPending}
            type="submit"
            variant="secondary"
          >
            Sicher nachschlagen
          </Button>
        </form>
        {lookupError ? (
          <StatusMessage tone="error">
            <strong>Support-Code nicht gefunden</strong>
            <p>{lookupError.message}</p>
          </StatusMessage>
        ) : null}
        {result ? (
          <div
            aria-live="polite"
            className="stack"
            data-testid="support-diagnostic-result"
          >
            <p>
              <StatusLabel
                shape={result.outcome === "successful" ? "done" : "alert"}
                status={result.impact}
              />
            </p>
            <DetailProps
              items={[
                { label: "Zeit", value: formatDateTime(result.occurredAt) },
                {
                  label: "Bereich",
                  value: (
                    <span className="mono">
                      {result.method} {result.route}
                    </span>
                  ),
                },
                {
                  label: "Status",
                  value: `HTTP ${result.statusCode}${result.errorCode ? ` · ${result.errorCode}` : ""}`,
                },
                {
                  label: "Release",
                  value: <span className="mono">{result.release}</span>,
                },
              ]}
            />
            <div className="callout">
              <Icon icon={Info} size={16} />
              <span>
                <strong>Empfehlung:</strong> {result.nextStep}
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
