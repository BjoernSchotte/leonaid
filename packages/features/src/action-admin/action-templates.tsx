import { useMutation, useQuery } from "@tanstack/react-query";
import { Copy, Package } from "lucide-react";
import { useId, useState } from "react";

import type {
  CharityActionConfigurationResponse,
  CharityActionResponse,
  ConfiguredOfferingResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  NextStep,
  SkeletonRows,
  StatusMessage,
  type Tone,
} from "@leonaid/ui";

import { shortDate } from "../shared/dates";
import { actionErrorMessage, type ActionErrorMessage } from "./errors";

export function useActionConfiguration(
  client: LeonAidApiClient,
  actionId: string,
) {
  return useQuery({
    queryKey: ["action-configuration", actionId],
    queryFn: () => client.getCharityActionConfiguration(actionId),
    retry: false,
    staleTime: 30_000,
  });
}

type ConfigurationQuery = ReturnType<typeof useActionConfiguration>;

function ConfigurationState({ query }: { readonly query: ConfigurationQuery }) {
  if (query.isPending) return <SkeletonRows rows={3} />;
  return (
    <ErrorState
      onRetry={() => void query.refetch()}
      title="Die Konfiguration konnte nicht geladen werden"
    >
      Der Server hat nicht geantwortet. Prüfen Sie die Verbindung und versuchen
      Sie es erneut.
    </ErrorState>
  );
}

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** "Krapfentaxi 2026" → "Krapfentaxi 2027"; dates one year later. */
function nextEdition(action: CharityActionResponse) {
  const shift = (value: string) =>
    `${Number(value.slice(0, 4)) + 1}${value.slice(4)}`;
  const name = /\b(\d{4})\b/.test(action.name)
    ? action.name.replace(/\b(\d{4})\b/, (year) => String(Number(year) + 1))
    : `${action.name} (Kopie)`;
  const slug = name
    .toLocaleLowerCase("de-DE")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return {
    name,
    startsOn: shift(action.startsOn),
    endsOn: shift(action.endsOn),
    archiveSlug: slug,
  };
}

function CopyModal({
  action,
  client,
  onClose,
  open,
}: {
  readonly action: CharityActionResponse;
  readonly client: LeonAidApiClient;
  readonly onClose: () => void;
  readonly open: boolean;
}) {
  const formId = useId();
  const [draft, setDraft] = useState(() => nextEdition(action));
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<ActionErrorMessage>();
  const copy = useMutation({
    mutationFn: () => client.copyCharityAction(action.id, draft),
    onSuccess: (created) => {
      window.location.assign(`/admin/actions/${created.action.id}`);
    },
    onError: (cause) => setError(actionErrorMessage(cause)),
  });
  const nameError = draft.name.trim() ? "" : "Bitte einen Namen eingeben.";
  const slugError = SLUG.test(draft.archiveSlug)
    ? ""
    : "Nur Kleinbuchstaben, Ziffern und Bindestriche.";
  const dateError =
    draft.startsOn && draft.endsOn && draft.startsOn <= draft.endsOn
      ? ""
      : "Das Ende darf nicht vor dem Beginn liegen.";

  return (
    <Modal
      description={`Angebote, Bestellformular, Funktionen und Texte aus ${action.name} werden als neuer Entwurf übernommen. Bestellungen, Rechnungen und Aliase nicht.`}
      footer={
        <>
          <Button disabled={copy.isPending} onClick={onClose} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="copy-action-submit"
            form={formId}
            icon={Copy}
            loading={copy.isPending}
            type="submit"
            variant="primary"
          >
            Als Entwurf anlegen
          </Button>
        </>
      }
      onClose={() => {
        if (!copy.isPending) onClose();
      }}
      open={open}
      title="Für die nächste Ausgabe kopieren"
    >
      <form
        className="form-grid"
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(true);
          if (nameError || slugError || dateError) return;
          setError(undefined);
          copy.mutate();
        }}
      >
        <Field
          error={submitted ? nameError : undefined}
          label="Name der neuen Aktion"
          required
        >
          <Input
            data-testid="copy-action-name"
            maxLength={200}
            onChange={(event) =>
              setDraft({ ...draft, name: event.currentTarget.value })
            }
            value={draft.name}
          />
        </Field>
        <div className="form-row">
          <Field label="Beginn" required>
            <Input
              onChange={(event) =>
                setDraft({ ...draft, startsOn: event.currentTarget.value })
              }
              type="date"
              value={draft.startsOn}
            />
          </Field>
          <Field
            error={submitted ? dateError : undefined}
            label="Ende"
            required
          >
            <Input
              onChange={(event) =>
                setDraft({ ...draft, endsOn: event.currentTarget.value })
              }
              type="date"
              value={draft.endsOn}
            />
          </Field>
        </div>
        <Field
          error={submitted ? slugError : undefined}
          hint="Dauerhafte Adresse der neuen Ausgabe unter /archive/…; sie lässt sich später nicht ändern."
          label="Archiv-Adresse"
          required
        >
          <Input
            className="mono"
            data-testid="copy-action-slug"
            maxLength={120}
            onChange={(event) =>
              setDraft({ ...draft, archiveSlug: event.currentTarget.value })
            }
            value={draft.archiveSlug}
          />
        </Field>
        {error ? (
          <StatusMessage tone="error">
            <span>{error.message}</span>
          </StatusMessage>
        ) : null}
      </form>
    </Modal>
  );
}

/**
 * Vorlagen (prototype Campaigns.tsx Templates): the template this action
 * came from, the club's templates, and copying the action for its next
 * edition (POST /actions/{id}/copies; the server authorizes it).
 */
export function TemplatesTab({
  action,
  client,
  configuration,
  disabled,
}: {
  readonly action: CharityActionResponse;
  readonly client: LeonAidApiClient;
  readonly configuration: ConfigurationQuery;
  readonly disabled: boolean;
}) {
  const [copying, setCopying] = useState(false);
  const templates = useQuery({
    queryKey: ["action-templates"],
    queryFn: () => client.listActionTemplates(),
    retry: false,
    staleTime: 60_000,
  });
  if (!configuration.isSuccess)
    return <ConfigurationState query={configuration} />;
  const snapshot = configuration.data.template;

  return (
    <div className="stack">
      {!disabled ? (
        <NextStep
          action={
            <Button
              data-testid="copy-action"
              icon={Copy}
              onClick={() => setCopying(true)}
              variant="primary"
            >
              Für die nächste Ausgabe kopieren
            </Button>
          }
          consequence={`Angebote, Bestellformular und Texte aus ${action.name} als neuen Entwurf übernehmen. Bestellungen und Rechnungen werden nicht übernommen.`}
          data-testid="templates-next-step"
        />
      ) : null}
      <section aria-labelledby="template-used" className="stack">
        <h2 className="tab-h2" id="template-used">
          Vorlage dieser Aktion
        </h2>
        <ul className="template-list">
          <li className="template-row" data-testid="template-snapshot">
            <div>
              <p className="template-name">
                {snapshot.displayName}{" "}
                <Badge tone="neutral">Version {snapshot.version}</Badge>
              </p>
              <p className="small muted">
                {snapshot.copiedFromActionId
                  ? "Aus einer früheren Aktion kopiert; Änderungen an der Vorlage wirken nicht rückwirkend."
                  : "Beim Anlegen übernommen; Änderungen an der Vorlage wirken nicht rückwirkend."}
              </p>
            </div>
            {snapshot.copiedFromActionId ? (
              <a
                className="small"
                href={`/admin/actions/${snapshot.copiedFromActionId}`}
              >
                Ursprüngliche Aktion öffnen
              </a>
            ) : null}
          </li>
        </ul>
      </section>
      <section aria-labelledby="template-catalog" className="stack">
        <h2 className="tab-h2" id="template-catalog">
          Vorlagen im Club
        </h2>
        {templates.isPending ? (
          <SkeletonRows rows={2} />
        ) : templates.isError ? (
          <p className="small subtle">
            Die Vorlagen konnten nicht geladen werden.
          </p>
        ) : (
          <ul className="template-list" data-testid="template-catalog">
            {templates.data.items.map((template) => (
              <li
                className="template-row"
                key={`${template.key}:${template.version}`}
              >
                <div>
                  <p className="template-name">
                    {template.displayName}{" "}
                    <Badge tone="neutral">Version {template.version}</Badge>
                    {template.key === snapshot.key ? (
                      <Badge tone="zone">Diese Aktion</Badge>
                    ) : null}
                  </p>
                  <p className="small muted">{template.description}</p>
                </div>
                <span className="small subtle">
                  {template.offeringCount}{" "}
                  {template.offeringCount === 1 ? "Angebot" : "Angebote"}
                  {template.hasOrderForm ? " · Bestellformular" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {copying ? (
        <CopyModal
          action={action}
          client={client}
          onClose={() => setCopying(false)}
          open
        />
      ) : null}
    </div>
  );
}

const offeringStatus: Readonly<
  Record<ConfiguredOfferingResponse["status"], { label: string; tone: Tone }>
> = {
  active: { label: "Wird angeboten", tone: "ok" },
  draft: { label: "Entwurf", tone: "neutral" },
  inactive: { label: "Ausgeblendet", tone: "neutral" },
};

const unitLabels: Readonly<
  Record<ConfiguredOfferingResponse["unit"], [string, string]>
> = {
  box: ["Box", "Boxen"],
  piece: ["Stück", "Stück"],
  package: ["Paket", "Pakete"],
  sponsoring: ["Sponsoring", "Sponsorings"],
};

function money(minor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", { currency, style: "currency" }).format(
    minor / 100,
  );
}

function availability(offering: ConfiguredOfferingResponse) {
  if (!offering.availableFrom && !offering.availableUntil) return "Immer";
  return [
    offering.availableFrom ? `ab ${shortDate(offering.availableFrom)}` : "",
    offering.availableUntil ? `bis ${shortDate(offering.availableUntil)}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

/** Angebote (prototype Campaigns.tsx Offers), read from the configuration. */
export function OffersTab({
  configuration,
}: {
  readonly configuration: ConfigurationQuery;
}) {
  if (!configuration.isSuccess)
    return <ConfigurationState query={configuration} />;
  const offerings: CharityActionConfigurationResponse["offerings"] =
    configuration.data.offerings;
  if (offerings.length === 0) {
    return (
      <EmptyState
        description="Angebote kommen aus der Vorlage der Aktion. Ohne Angebot gibt es kein Bestellformular."
        icon={Package}
        title="Keine Angebote"
      />
    );
  }
  return (
    <div
      aria-label="Angebote"
      className="table-wrap"
      role="region"
      tabIndex={0}
    >
      <table className="table" data-testid="offerings-table">
        <caption className="sr-only">Angebote</caption>
        <thead>
          <tr>
            <th scope="col">Angebot</th>
            <th className="right" scope="col">
              Stück
            </th>
            <th className="right" scope="col">
              Preis
            </th>
            <th scope="col">Verfügbar</th>
            <th scope="col">Im Formular</th>
          </tr>
        </thead>
        <tbody>
          {offerings.map((offering) => (
            <tr data-testid={`offering-${offering.code}`} key={offering.id}>
              <td>
                {offering.name}{" "}
                <span className="mono subtle small">{offering.code}</span>
              </td>
              <td className="right num">{offering.piecesPerUnit ?? "–"}</td>
              <td className="right num">
                {money(offering.unitPriceMinor, offering.currency)}
                <span className="subtle">
                  {" "}
                  / {unitLabels[offering.unit][0]}
                </span>
              </td>
              <td className="small">{availability(offering)}</td>
              <td>
                <Badge tone={offeringStatus[offering.status].tone}>
                  {offeringStatus[offering.status].label}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small subtle table-note">
        Angebote kommen aus der Vorlage und lassen sich hier nicht ändern.
        Preise bestehender Bestellungen ändern sich nicht.
      </p>
    </div>
  );
}
