import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
  Settings02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  type FeatureFlagAdminResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import {
  FEATURE_FLAGS,
  useLeonAidBooleanFlag,
} from "../feature-flags/openfeature-provider";
import { OperationsAdminPanel } from "./operations-admin";

export interface FeatureFlagAdminPageProps {
  readonly client: LeonAidApiClient;
}

function formatUpdatedAt(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function FlagCard({
  flag,
  pending,
  onToggle,
}: {
  readonly flag: FeatureFlagAdminResponse;
  readonly pending: boolean;
  readonly onToggle: (flag: FeatureFlagAdminResponse) => void;
}) {
  return (
    <article className="feature-flag-card" data-flag-key={flag.key}>
      <div className="feature-flag-card__copy">
        <div className="feature-flag-card__title">
          <span
            aria-hidden="true"
            className={`feature-flag-card__indicator ${
              flag.enabled ? "is-enabled" : ""
            }`}
          />
          <div>
            <p className="feature-flag-card__key">{flag.key}</p>
            <h2>{flag.title}</h2>
          </div>
        </div>
        <p>{flag.description}</p>
        <div className="feature-flag-card__meta">
          <span>
            <HugeiconsIcon
              aria-hidden="true"
              icon={InformationCircleIcon}
              size={16}
              strokeWidth={1.8}
            />
            {flag.effect}
          </span>
          <small>
            Version {flag.revision} · zuletzt aktualisiert{" "}
            {formatUpdatedAt(flag.updatedAt)}
          </small>
        </div>
      </div>
      <div className="feature-flag-card__control">
        <span className={flag.enabled ? "is-enabled" : ""}>
          {pending ? "Wird gespeichert …" : flag.enabled ? "Aktiv" : "Inaktiv"}
        </span>
        <button
          aria-checked={flag.enabled}
          aria-label={`${flag.title} ${
            flag.enabled ? "deaktivieren" : "aktivieren"
          }`}
          className="feature-switch"
          data-testid={`feature-switch-${flag.key}`}
          disabled={pending}
          onClick={() => onToggle(flag)}
          role="switch"
          type="button"
        >
          <span />
        </button>
      </div>
    </article>
  );
}

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
      className="feature-system-status"
      data-testid="feature-system-status"
    >
      <div className="feature-system-status__icon" aria-hidden="true">
        <HugeiconsIcon
          icon={CheckmarkCircle02Icon}
          size={24}
          strokeWidth={1.8}
        />
      </div>
      <div>
        <p className="feature-system-status__eyebrow">
          Serverseitiger Nachweis
        </p>
        <h2 id="feature-system-status-title">OpenFeature-Systemstatus</h2>
        {status.isPending ? (
          <p>Der geschützte Backend-Endpunkt wird geprüft …</p>
        ) : status.isError ? (
          <p>
            Der Diagnose-Endpunkt ist trotz sichtbarem Browser-Flag nicht
            verfügbar.
          </p>
        ) : (
          <>
            <p>
              Betriebsbereit · ausgewertet durch{" "}
              <strong>{status.data.evaluatedBy}</strong>
            </p>
            <small>Provider: {status.data.provider}</small>
          </>
        )}
      </div>
    </section>
  );
}

export function FeatureFlagAdminPage({ client }: FeatureFlagAdminPageProps) {
  const queryClient = useQueryClient();
  const flags = useQuery({
    queryFn: () => client.listFeatureFlags(),
    queryKey: ["feature-flags", "admin"],
  });
  const update = useMutation({
    mutationFn: (flag: FeatureFlagAdminResponse) =>
      client.updateFeatureFlag(flag.key, {
        enabled: !flag.enabled,
        expectedRevision: flag.revision,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["feature-flags", "admin"] }),
        queryClient.invalidateQueries({ queryKey: ["feature-flags", "web"] }),
        queryClient.invalidateQueries({
          queryKey: ["feature-flag-system-status"],
        }),
      ]);
    },
  });

  const error = update.error ? actionErrorMessage(update.error) : null;

  if (flags.isPending) {
    return (
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Feature-Flags werden geladen</h1>
        <p>LeonAid ruft den installationsweiten Schaltzustand ab.</p>
      </div>
    );
  }

  if (flags.isError) {
    const forbidden =
      flags.error instanceof ApiError && flags.error.status === 403;
    return (
      <main className="ui-main">
        <StatusMessage tone="error">
          <h1>
            {forbidden
              ? "Nur für System-Admins"
              : "Feature-Flags nicht erreichbar"}
          </h1>
          <p>
            {forbidden
              ? "Dieser Bereich steuert installationsweite Funktionen."
              : "Die Schaltzustände konnten gerade nicht geladen werden."}
          </p>
          {!forbidden && (
            <Button onClick={() => void flags.refetch()} variant="secondary">
              Erneut versuchen
            </Button>
          )}
        </StatusMessage>
      </main>
    );
  }

  return (
    <div className="feature-admin-page">
      <header className="feature-admin-header">
        <div className="feature-admin-header__icon" aria-hidden="true">
          <HugeiconsIcon icon={Settings02Icon} size={24} strokeWidth={1.8} />
        </div>
        <div>
          <p className="feature-admin-header__eyebrow">
            System · kontrollierter Rollout
          </p>
          <h1>System & Betrieb</h1>
          <p>
            Prüfe Abhängigkeiten und Jobs live. Darunter steuerst du
            vorbereitete Funktionen ohne Redeploy.
          </p>
        </div>
        <a
          className="ui-button ui-button--secondary feature-admin-header__catalog"
          href="/admin/system/ui"
        >
          UI-Basis
        </a>
      </header>

      <aside className="feature-admin-guardrail">
        <HugeiconsIcon
          aria-hidden="true"
          icon={Alert02Icon}
          size={20}
          strokeWidth={1.8}
        />
        <p>
          Feature-Flags steuern Sichtbarkeit und Rollout – niemals
          Berechtigungen. Schreibzugriffe bleiben immer serverseitig geschützt.
        </p>
      </aside>

      {error && (
        <StatusMessage tone="error">
          <p>{error.message}</p>
        </StatusMessage>
      )}

      <OperationsAdminPanel client={client} />

      <div className="feature-admin-section-heading" id="feature-flags">
        <p className="feature-admin-header__eyebrow">Kontrollierter Rollout</p>
        <h2>Feature-Flags</h2>
        <p>
          Änderungen gelten installationsweit, werden versioniert und im
          Audit-Log dokumentiert.
        </p>
      </div>

      <section
        aria-label="Installationsweite Feature-Flags"
        className="feature-flag-list"
      >
        {flags.data.flags.map((flag) => (
          <FlagCard
            flag={flag}
            key={flag.key}
            onToggle={(selected) => update.mutate(selected)}
            pending={update.isPending && update.variables?.key === flag.key}
          />
        ))}
      </section>

      <SystemStatusPanel client={client} />
    </div>
  );
}
