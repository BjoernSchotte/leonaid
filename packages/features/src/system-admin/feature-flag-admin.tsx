import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Info } from "lucide-react";
import { useState } from "react";

import {
  ApiError,
  type FeatureFlagAdminResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  ConfirmDialog,
  ErrorState,
  Icon,
  SkeletonRows,
  StatusMessage,
  Switch,
  useOptionalToast,
} from "@leonaid/ui";

import {
  actionErrorMessage,
  type ActionErrorMessage,
} from "../action-admin/errors";
import { useActionErrorMessage } from "../action-admin/use-action-error";
import {
  FEATURE_FLAGS,
  useLeonAidBooleanFlag,
} from "../feature-flags/openfeature-provider";
import { formatDateTime } from "../shared/dates";

export interface FeatureFlagAdminPageProps {
  readonly client: LeonAidApiClient;
}

/** The server-side OpenFeature check, shown while its flag is on. */
function SystemStatusPanel({ client }: FeatureFlagAdminPageProps) {
  const enabled = useLeonAidBooleanFlag(FEATURE_FLAGS.systemStatusPanel);
  const status = useQuery({
    enabled,
    queryFn: () => client.getFeatureFlagSystemStatus(),
    queryKey: ["feature-flag-system-status"],
    retry: false,
  });
  if (!enabled) return null;
  return (
    <section
      aria-labelledby="feature-system-status-title"
      className="panel"
      data-testid="feature-system-status"
    >
      <header className="panel-header">
        <h2 id="feature-system-status-title">OpenFeature-Systemstatus</h2>
        <Badge tone={status.isSuccess ? "ok" : "neutral"}>
          Serverseitiger Nachweis
        </Badge>
      </header>
      <div className="panel-pad small">
        {status.isPending ? (
          <p className="muted">Der geschützte Endpunkt wird geprüft …</p>
        ) : status.isError ? (
          <p className="muted">
            Der Diagnose-Endpunkt ist trotz sichtbarem Browser-Flag nicht
            verfügbar.
          </p>
        ) : (
          <p className="cluster">
            <Icon icon={CircleCheck} size={16} />
            Betriebsbereit · ausgewertet durch{" "}
            <strong>{status.data.evaluatedBy}</strong> · Provider{" "}
            {status.data.provider}
          </p>
        )}
      </div>
    </section>
  );
}

/**
 * Funktionen (prototype System.tsx Flags): installation-wide switches with
 * a confirmation; the server versions them and asks for a fresh sign-in.
 */
export function FlagsTab({ client }: FeatureFlagAdminPageProps) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const [asking, setAsking] = useState<FeatureFlagAdminResponse>();
  const [error, setError] = useState<ActionErrorMessage>();
  const flags = useQuery({
    queryFn: () => client.listFeatureFlags(),
    queryKey: ["feature-flags", "admin"],
  });
  const loadError = useActionErrorMessage(flags.error);
  const update = useMutation({
    mutationFn: (flag: FeatureFlagAdminResponse) =>
      client.updateFeatureFlag(flag.key, {
        enabled: !flag.enabled,
        expectedRevision: flag.revision,
      }),
    onSuccess: async (_result, flag) => {
      setAsking(undefined);
      setError(undefined);
      toast?.show({
        title: `${flag.title}: ${flag.enabled ? "aus" : "an"}`,
        tone: "success",
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["feature-flags", "admin"] }),
        queryClient.invalidateQueries({ queryKey: ["feature-flags", "web"] }),
        queryClient.invalidateQueries({
          queryKey: ["feature-flag-system-status"],
        }),
      ]);
    },
    onError: (cause) => {
      setAsking(undefined);
      setError(actionErrorMessage(cause));
    },
  });

  if (flags.isPending) return <SkeletonRows rows={3} />;
  if (flags.isError) {
    const forbidden =
      flags.error instanceof ApiError && flags.error.status === 403;
    return (
      <ErrorState
        onRetry={forbidden ? undefined : () => void flags.refetch()}
        title={
          forbidden ? "Nur für System-Admins" : "Funktionen nicht erreichbar"
        }
      >
        {forbidden
          ? "Dieser Bereich steuert installationsweite Funktionen."
          : (loadError?.message ??
            "Die Schalter konnten nicht geladen werden.")}
      </ErrorState>
    );
  }

  const list = flags.data.flags;
  const changes = [...list].sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );

  return (
    <div className="system-grid">
      <section aria-labelledby="flags-title" className="panel">
        <header className="panel-header">
          <h2 id="flags-title">Funktionen dieser Installation</h2>
        </header>
        <div className="callout flag-note">
          <Icon icon={Info} size={16} />
          <span>
            Schalter ändern nur Sichtbarkeit und Einführung. Rollen und
            Berechtigungen bleiben unverändert; Schreibzugriffe prüft immer der
            Server.
          </span>
        </div>
        {error ? (
          <StatusMessage className="flag-note" tone="error">
            <p>{error.message}</p>
          </StatusMessage>
        ) : null}
        <ul aria-label="Installationsweite Funktionen" className="flag-list">
          {list.map((flag) => (
            <li className="flag-row" data-flag-key={flag.key} key={flag.key}>
              <div className="flag-text">
                <label className="flag-name" htmlFor={`flag-${flag.key}`}>
                  {flag.title}
                </label>
                <p className="small muted" id={`flag-${flag.key}-desc`}>
                  {flag.description}
                </p>
              </div>
              <span className="small muted num">Rev. {flag.revision}</span>
              <Badge tone={flag.enabled ? "ok" : "neutral"}>
                {flag.enabled ? "An" : "Aus"}
              </Badge>
              <Switch
                aria-describedby={`flag-${flag.key}-desc`}
                checked={flag.enabled}
                data-testid={`feature-switch-${flag.key}`}
                disabled={update.isPending}
                id={`flag-${flag.key}`}
                onChange={() => setAsking(flag)}
              />
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="audit-title" className="panel">
        <header className="panel-header">
          <h2 id="audit-title">Letzte Änderungen</h2>
        </header>
        <ol className="audit-list">
          {changes.map((flag) => (
            <li className="small num" key={flag.key}>
              {formatDateTime(flag.updatedAt)} · {flag.title}{" "}
              {flag.enabled ? "an" : "aus"} (Revision {flag.revision})
            </li>
          ))}
        </ol>
      </section>
      <SystemStatusPanel client={client} />
      <ConfirmDialog
        confirmLabel={asking?.enabled ? "Ausschalten" : "Einschalten"}
        description={
          asking
            ? asking.enabled
              ? `${asking.title} verschwindet für alle Mitglieder beim nächsten Seitenaufruf. ${asking.effect}`
              : `${asking.title} erscheint für alle berechtigten Mitglieder beim nächsten Seitenaufruf. ${asking.effect}`
            : ""
        }
        onConfirm={() => {
          if (asking) update.mutate(asking);
        }}
        onOpenChange={(open) => {
          if (!open && !update.isPending) setAsking(undefined);
        }}
        open={Boolean(asking)}
        pending={update.isPending}
        title={
          asking
            ? `${asking.title} ${asking.enabled ? "ausschalten" : "einschalten"}?`
            : ""
        }
      />
    </div>
  );
}
