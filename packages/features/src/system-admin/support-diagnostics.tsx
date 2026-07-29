import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

export function SupportDiagnosticsPanel({
  client,
}: {
  readonly client: LeonAidApiClient;
}) {
  const [supportCode, setSupportCode] = useState("");
  const probe = useMutation({
    mutationFn: () => client.runSupportProbe(),
    onError: (error) => {
      if (error instanceof ApiError) {
        setSupportCode(error.detail.requestId);
      }
    },
  });
  const lookup = useMutation({
    mutationFn: (code: string) => client.getSupportRequestDiagnostic(code),
  });
  const probeError = probe.error ? actionErrorMessage(probe.error) : null;
  const lookupError = lookup.error ? actionErrorMessage(lookup.error) : null;

  function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = supportCode.trim();
    if (normalized) lookup.mutate(normalized);
  }

  return (
    <section
      aria-labelledby="support-diagnostics-title"
      className="support-diagnostics"
      data-testid="support-diagnostics"
      id="support"
    >
      <header className="support-diagnostics__header">
        <div>
          <p className="feature-admin-header__eyebrow">
            Support · ohne Inhaltszugriff
          </p>
          <h2 id="support-diagnostics-title">Anfrage sicher nachvollziehen</h2>
          <p>
            Ein Support-Code zeigt nur technischen Ausgang, Route und Release.
            Formulardaten, Namen, E-Mails und Dokumente bleiben unsichtbar.
          </p>
        </div>
        <Button
          data-testid="support-probe"
          disabled={probe.isPending}
          onClick={() => {
            probe.reset();
            lookup.reset();
            probe.mutate();
          }}
          variant="secondary"
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={Alert02Icon}
            size={17}
            strokeWidth={1.8}
          />
          {probe.isPending ? "Test läuft …" : "Diagnose-Test starten"}
        </Button>
      </header>

      <aside className="support-diagnostics__privacy">
        <HugeiconsIcon
          aria-hidden="true"
          icon={InformationCircleIcon}
          size={20}
          strokeWidth={1.8}
        />
        <p>
          Der Test erzeugt absichtlich einen kontrollierten Fehler ohne
          Schreibzugriff. Echte Support-Codes findest du in der jeweiligen
          Fehlermeldung.
        </p>
      </aside>

      {probeError && (
        <StatusMessage tone="info">
          <h3>Kontrollierter Fehler wurde erzeugt</h3>
          <p>{probeError.message}</p>
        </StatusMessage>
      )}

      <form className="support-diagnostics__form" onSubmit={submitLookup}>
        <label htmlFor="support-code">
          Support-Code
          <span>
            Den vollständigen Code aus der Fehlermeldung einfügen; er enthält
            keine fachlichen Daten.
          </span>
        </label>
        <div>
          <input
            autoComplete="off"
            id="support-code"
            maxLength={128}
            minLength={8}
            onChange={(event) => setSupportCode(event.target.value)}
            placeholder="z. B. 52f2f7c8-…"
            required
            spellCheck={false}
            value={supportCode}
          />
          <Button
            data-testid="support-lookup"
            disabled={lookup.isPending || supportCode.trim().length < 8}
            type="submit"
          >
            {lookup.isPending ? "Wird geprüft …" : "Sicher nachschlagen"}
          </Button>
        </div>
      </form>

      {lookupError && (
        <StatusMessage tone="error">
          <h3>Support-Code nicht gefunden</h3>
          <p>{lookupError.message}</p>
        </StatusMessage>
      )}

      {lookup.data && (
        <article
          aria-live="polite"
          className={`support-diagnostics__result is-${lookup.data.outcome}`}
          data-testid="support-diagnostic-result"
        >
          <div className="support-diagnostics__result-icon" aria-hidden="true">
            <HugeiconsIcon
              icon={
                lookup.data.outcome === "successful"
                  ? CheckmarkCircle02Icon
                  : Alert02Icon
              }
              size={22}
              strokeWidth={1.8}
            />
          </div>
          <div className="support-diagnostics__result-copy">
            <p>Technischer Befund</p>
            <h3>{lookup.data.impact}</h3>
            <dl>
              <div>
                <dt>Zeit</dt>
                <dd>{formatDate(lookup.data.occurredAt)}</dd>
              </div>
              <div>
                <dt>Bereich</dt>
                <dd>
                  {lookup.data.method} {lookup.data.route}
                </dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  HTTP {lookup.data.statusCode}
                  {lookup.data.errorCode ? ` · ${lookup.data.errorCode}` : ""}
                </dd>
              </div>
              <div>
                <dt>Release</dt>
                <dd>{lookup.data.release}</dd>
              </div>
            </dl>
            <div className="support-diagnostics__next-step">
              <strong>Nächster Schritt</strong>
              <p>{lookup.data.nextStep}</p>
            </div>
          </div>
        </article>
      )}
    </section>
  );
}
