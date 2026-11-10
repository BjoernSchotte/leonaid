import { useMutation } from "@tanstack/react-query";
import { Plus, Save } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type {
  ActionManagementResponse,
  CharityActionResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  Button,
  ConfirmDialog,
  Field,
  Input,
  NextStep,
  StatusMessage,
  Textarea,
  useLeaveGuard,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage, type ActionErrorMessage } from "./errors";
import { isRevisionConflict } from "./use-action-error";

export type Capability = CharityActionResponse["capabilities"][number];
export type ActionStatus = CharityActionResponse["status"];

export interface SharedSectionProps {
  readonly client: LeonAidApiClient;
  readonly disabled: boolean;
  readonly state: ActionManagementResponse;
  readonly updateAction: (action: CharityActionResponse) => void;
  readonly updateState: (state: ActionManagementResponse) => void;
  /**
   * The revision to send for a draft begun at `base`: later revisions this
   * page saved itself count as known, any other change keeps `base`, so the
   * server answers with a conflict instead of a silent overwrite.
   */
  readonly revisionFor: (base: number) => number;
  /** A form reports unsaved input (for the page's discard question). */
  readonly onDirty?: (form: string, dirty: boolean) => void;
}

export const statusLabels: Readonly<Record<ActionStatus, string>> = {
  active: "Aktiv",
  archived: "Archiviert",
  completed: "Abgeschlossen",
  draft: "Entwurf",
  scheduled: "Geplant",
};

/**
 * Error under a form. After a stale revision the person can load the
 * current state into the form (their input is replaced) or compare it in
 * a new tab first.
 */
function SectionError({
  error,
  onReload,
}: {
  readonly error?: ActionErrorMessage;
  readonly onReload?: () => void;
}) {
  if (!error) return null;
  const conflict = isRevisionConflict(error) || error.conflict;
  return (
    <StatusMessage tone="error">
      <span>{error.message}</span>
      {conflict ? (
        <span className="section-error-actions">
          {onReload ? (
            <Button
              data-testid="section-reload"
              onClick={onReload}
              size="sm"
              variant="secondary"
            >
              Aktuellen Stand laden
            </Button>
          ) : null}
          <a
            href={`${window.location.pathname}${window.location.search}${window.location.hash}`}
            rel="noreferrer"
            target="_blank"
          >
            Aktuellen Stand in neuem Tab öffnen
          </a>
        </span>
      ) : null}
    </StatusMessage>
  );
}

/**
 * A form's draft with the revision it was begun from. The draft is dirty
 * while it differs from what was last loaded or saved; that guards the
 * page against leaving and is reported to it.
 */
export function useSectionDraft<T>(
  form: string,
  fromAction: () => T,
  props: Pick<SharedSectionProps, "state" | "revisionFor" | "onDirty">,
) {
  const [draft, setDraft] = useState<T>(fromAction);
  const [baseline, setBaseline] = useState<T>(fromAction);
  const [base, setBase] = useState(props.state.action.revision);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  useLeaveGuard(dirty);
  const onDirty = props.onDirty;
  useEffect(() => {
    onDirty?.(form, dirty);
    return () => onDirty?.(form, false);
  }, [dirty, form, onDirty]);
  return {
    draft,
    setDraft,
    dirty,
    /** The revision to send with this draft. */
    revision: props.revisionFor(base),
    /** After a save: the saved draft is the new baseline. */
    saved(next: T, revision: number) {
      setBaseline(next);
      setBase(revision);
    },
    /** Load the current state into the form. */
    reset() {
      const fresh = fromAction();
      setDraft(fresh);
      setBaseline(fresh);
      setBase(props.state.action.revision);
    },
  };
}

/** A titled form block of the edit mode (prototype .tab-h2 heading). */
function EditSection({
  children,
  description,
  id,
  title,
}: {
  readonly children: ReactNode;
  readonly description: ReactNode;
  readonly id: string;
  readonly title: string;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="edit-section" id={id}>
      <h2 className="tab-h2" id={`${id}-heading`}>
        {title}
      </h2>
      <p className="small muted edit-section-intro">{description}</p>
      {children}
    </section>
  );
}

/** One save mutation per section: toast on success, inline error. */
function useSectionSave<T>(
  run: () => Promise<T>,
  onSaved: (result: T) => void,
  message: string,
) {
  const toast = useOptionalToast();
  const [error, setError] = useState<ActionErrorMessage>();
  const mutation = useMutation({
    mutationFn: run,
    onSuccess(result) {
      setError(undefined);
      onSaved(result);
      toast?.show({ title: message, tone: "success" });
    },
    onError(cause) {
      // Redirects to /fresh-login when the server asks for it.
      setError(actionErrorMessage(cause));
    },
  });
  return { error, mutation, setError };
}

function SaveButton({
  disabled,
  label,
  pending,
  testId,
}: {
  readonly disabled: boolean;
  readonly label: string;
  readonly pending: boolean;
  readonly testId: string;
}) {
  return (
    <Button
      data-testid={testId}
      disabled={disabled}
      icon={Save}
      loading={pending}
      type="submit"
      variant="secondary"
    >
      {label}
    </Button>
  );
}

export function DetailsSection(props: SharedSectionProps) {
  const { client, disabled, state, updateAction } = props;
  const action = state.action;
  const form = useSectionDraft(
    "details",
    () => ({
      carrierName: state.action.carrierName,
      endsOn: state.action.endsOn,
      name: state.action.name,
      purpose: state.action.purpose,
      startsOn: state.action.startsOn,
    }),
    props,
  );
  const { draft, setDraft } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setCharityActionDetails(action.id, {
        ...draft,
        revision: form.revision,
      }),
    (updated) => {
      form.saved(draft, updated.revision);
      updateAction(updated);
    },
    "Grunddaten und Zeitraum wurden gespeichert.",
  );

  return (
    <EditSection
      description="Name, Zweck, Träger und Laufzeit der Aktion."
      id="details"
      title="Grunddaten und Zeitraum"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Grunddaten und Zeitraum</legend>
          <Field
            hint="Der öffentliche Titel mit Jahr, zum Beispiel „Krapfentaxi 2026“."
            label="Name der Aktion"
            required
          >
            <Input
              data-testid="manage-name"
              id="manage-name"
              maxLength={200}
              onChange={(event) =>
                setDraft({ ...draft, name: event.currentTarget.value })
              }
              value={draft.name}
            />
          </Field>
          <div className="form-row">
            <Field
              hint="Verein oder Organisation, die diese Aktion durchführt."
              label="Träger"
              required
            >
              <Input
                data-testid="manage-carrier"
                id="manage-carrier"
                maxLength={200}
                onChange={(event) =>
                  setDraft({ ...draft, carrierName: event.currentTarget.value })
                }
                value={draft.carrierName}
              />
            </Field>
            <Field
              hint="Dauerhafte Adresse dieser Ausgabe; sie kann nicht geändert oder erneut vergeben werden."
              label="Archiv-Adresse"
            >
              <output
                className="input is-readonly mono"
                data-testid="manage-archive-slug"
                id="manage-archive-slug"
              >
                /archive/{action.archiveSlug}
              </output>
            </Field>
          </div>
          <Field
            hint="Wofür die Aktion Spenden oder Erlöse sammelt."
            label="Zweck"
            required
          >
            <Textarea
              data-testid="manage-purpose"
              id="manage-purpose"
              maxLength={2000}
              onChange={(event) =>
                setDraft({ ...draft, purpose: event.currentTarget.value })
              }
              rows={4}
              value={draft.purpose}
            />
          </Field>
          <div className="form-row">
            <Field
              hint="Erster Tag des fachlichen Aktionszeitraums."
              label="Beginn"
              required
            >
              <Input
                data-testid="manage-start"
                id="manage-start"
                onChange={(event) =>
                  setDraft({ ...draft, startsOn: event.currentTarget.value })
                }
                type="date"
                value={draft.startsOn}
              />
            </Field>
            <Field
              hint="Letzter Tag; danach kann die Aktion abgeschlossen werden."
              label="Ende"
              required
            >
              <Input
                data-testid="manage-end"
                id="manage-end"
                onChange={(event) =>
                  setDraft({ ...draft, endsOn: event.currentTarget.value })
                }
                type="date"
                value={draft.endsOn}
              />
            </Field>
          </div>
          <div className="form-actions">
            <SaveButton
              disabled={disabled || mutation.isPending}
              label="Grunddaten speichern"
              pending={mutation.isPending}
              testId="save-details"
            />
          </div>
        </fieldset>
      </form>
      <SectionError
        error={error}
        onReload={() => {
          setError(undefined);
          form.reset();
        }}
      />
    </EditSection>
  );
}

export function GoalSection(props: SharedSectionProps) {
  const { client, disabled, state, updateAction } = props;
  const action = state.action;
  const form = useSectionDraft(
    "goal",
    () => ({
      actualValue: state.action.goal.actualValue,
      currency: state.action.goal.currency ?? "",
      goalValue: state.action.goal.goalValue ?? "",
      unit: state.action.goal.unit ?? "",
    }),
    props,
  );
  const { draft, setDraft } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setCharityActionGoal(action.id, {
        actualValue: draft.actualValue,
        currency: draft.currency || null,
        goalValue: draft.goalValue || null,
        revision: form.revision,
        unit: draft.unit || null,
      }),
    (updated) => {
      form.saved(draft, updated.revision);
      updateAction(updated);
    },
    "Aktionsziel und Fortschritt wurden gespeichert.",
  );

  return (
    <EditSection
      description="Der aktuelle Stand zeigt allen Beteiligten den Fortschritt."
      id="goal"
      title="Ziel und Fortschritt"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Ziel und Fortschritt</legend>
          <div className="form-row">
            <Field
              hint="Messbarer Wert, den die Aktion erreichen soll."
              label="Ziel"
            >
              <Input
                data-testid="manage-goal"
                id="manage-goal"
                inputMode="decimal"
                onChange={(event) =>
                  setDraft({ ...draft, goalValue: event.currentTarget.value })
                }
                value={draft.goalValue}
              />
            </Field>
            <Field
              hint="Was gezählt wird, zum Beispiel Boxen, Bestellungen oder Euro."
              label="Einheit"
            >
              <Input
                data-testid="manage-unit"
                id="manage-unit"
                maxLength={40}
                onChange={(event) =>
                  setDraft({ ...draft, unit: event.currentTarget.value })
                }
                value={draft.unit}
              />
            </Field>
          </div>
          <div className="form-row">
            <Field
              hint="Bereits erreichter Wert; er ist für Beteiligte sichtbar."
              label="Aktueller Stand"
              required
            >
              <Input
                data-testid="manage-actual"
                id="manage-actual"
                inputMode="decimal"
                onChange={(event) =>
                  setDraft({ ...draft, actualValue: event.currentTarget.value })
                }
                value={draft.actualValue}
              />
            </Field>
            <Field
              hint="Nur bei Geldzielen: dreistelliger Code, zum Beispiel EUR."
              label="Währung"
              optional
            >
              <Input
                data-testid="manage-currency"
                id="manage-currency"
                maxLength={3}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    currency: event.currentTarget.value.toUpperCase(),
                  })
                }
                pattern="[A-Z]{3}"
                value={draft.currency}
              />
            </Field>
          </div>
          <div className="form-actions">
            <SaveButton
              disabled={disabled || mutation.isPending}
              label="Ziel speichern"
              pending={mutation.isPending}
              testId="save-goal"
            />
          </div>
        </fieldset>
      </form>
      <SectionError
        error={error}
        onReload={() => {
          setError(undefined);
          form.reset();
        }}
      />
    </EditSection>
  );
}

interface BeneficiaryDraft {
  readonly key: number;
  readonly organizationName: string;
  readonly publicDescription: string;
}

export function BeneficiariesSection(props: SharedSectionProps) {
  const { client, disabled, state, updateAction } = props;
  const action = state.action;
  const form = useSectionDraft<BeneficiaryDraft[]>(
    "beneficiaries",
    () =>
      state.action.beneficiaries.map((item, index) => ({
        key: index,
        organizationName: item.organizationName,
        publicDescription: item.publicDescription,
      })),
    props,
  );
  const { draft, setDraft } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setCharityActionBeneficiaries(action.id, {
        beneficiaries: draft.map(({ organizationName, publicDescription }) => ({
          organizationName,
          publicDescription,
        })),
        revision: form.revision,
      }),
    (updated) => {
      form.saved(draft, updated.revision);
      updateAction(updated);
    },
    "Die Begünstigten wurden gespeichert.",
  );

  function change(
    key: number,
    field: "organizationName" | "publicDescription",
    value: string,
  ) {
    setDraft((items) =>
      items.map((item) =>
        item.key === key ? { ...item, [field]: value } : item,
      ),
    );
  }

  return (
    <EditSection
      description="Eine Aktion unterstützt eine oder mehrere Organisationen."
      id="beneficiaries"
      title="Begünstigte"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Begünstigte</legend>
          {draft.map((beneficiary, index) => (
            <div className="beneficiary-row" key={beneficiary.key}>
              <Field
                hint="Organisation, die von den Erlösen der Aktion profitiert."
                label="Name der Organisation"
                required
              >
                <Input
                  data-testid={`manage-beneficiary-name-${index}`}
                  id={`manage-beneficiary-name-${beneficiary.key}`}
                  maxLength={200}
                  onChange={(event) =>
                    change(
                      beneficiary.key,
                      "organizationName",
                      event.currentTarget.value,
                    )
                  }
                  value={beneficiary.organizationName}
                />
              </Field>
              <Field
                hint="Kurzer Text für die öffentliche Aktionsseite."
                label="Öffentliche Beschreibung"
                required
              >
                <Textarea
                  data-testid={`manage-beneficiary-description-${index}`}
                  id={`manage-beneficiary-description-${beneficiary.key}`}
                  maxLength={2000}
                  onChange={(event) =>
                    change(
                      beneficiary.key,
                      "publicDescription",
                      event.currentTarget.value,
                    )
                  }
                  rows={3}
                  value={beneficiary.publicDescription}
                />
              </Field>
              {draft.length > 1 ? (
                <Button
                  aria-label={`Begünstigten ${index + 1} entfernen`}
                  onClick={() =>
                    setDraft((items) =>
                      items.filter((item) => item.key !== beneficiary.key),
                    )
                  }
                  size="sm"
                  variant="ghost"
                >
                  Entfernen
                </Button>
              ) : null}
            </div>
          ))}
          <div className="form-actions">
            <Button
              icon={Plus}
              onClick={() =>
                setDraft((items) => [
                  ...items,
                  {
                    key: Math.max(-1, ...items.map((item) => item.key)) + 1,
                    organizationName: "",
                    publicDescription: "",
                  },
                ])
              }
              variant="ghost"
            >
              Begünstigten hinzufügen
            </Button>
            <SaveButton
              disabled={disabled || mutation.isPending}
              label="Begünstigte speichern"
              pending={mutation.isPending}
              testId="save-beneficiaries"
            />
          </div>
        </fieldset>
      </form>
      <SectionError
        error={error}
        onReload={() => {
          setError(undefined);
          form.reset();
        }}
      />
    </EditSection>
  );
}

export const capabilityOptions: ReadonlyArray<{
  readonly description: string;
  readonly label: string;
  readonly value: Capability;
}> = [
  {
    description: "Firmen, Kontakte, Zuordnungen und Aktivitäten.",
    label: "Akquise",
    value: "acquisition",
  },
  {
    description: "Produkte, Pakete oder Sponsorings der Aktion.",
    label: "Angebote",
    value: "offerings",
  },
  {
    description: "Manuelle Zusagen und öffentliche Bestellungen.",
    label: "Bestellungen",
    value: "ordering",
  },
  {
    description: "Rechnungsstellung und Dokumente.",
    label: "Rechnungen",
    value: "invoicing",
  },
  {
    description:
      "Liefertage, Lieferadressen und Ausfahrer. Benötigt Bestellungen.",
    label: "Auslieferung",
    value: "delivery",
  },
  {
    description:
      "Die Aktion nimmt Spenden mit eigenen Dokumenten entgegen (Spendenzusage; die Zuwendungsbestätigung folgt), getrennt von Rechnungen. Benötigt den Teil „Spenden“ in „Organisation & Recht“.",
    label: "Spenden",
    value: "donations",
  },
];

export function CapabilitiesSection(props: SharedSectionProps) {
  const { client, disabled, state, updateAction } = props;
  const action = state.action;
  const form = useSectionDraft<Capability[]>(
    "capabilities",
    () => [...state.action.capabilities],
    props,
  );
  const { draft: selected, setDraft: setSelected } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setCharityActionCapabilities(action.id, {
        capabilities: selected,
        revision: form.revision,
      }),
    (updated) => {
      form.saved(selected, updated.revision);
      updateAction(updated);
    },
    "Die Funktionen der Aktion wurden gespeichert.",
  );

  return (
    <EditSection
      description="Wählen Sie nur die Bereiche, die diese Aktion wirklich braucht. Bestellungen benötigen mindestens ein Angebot; LeonAid prüft das beim Speichern."
      id="capabilities"
      title="Funktionen"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Funktionen</legend>
          <ul className="choice-list">
            {capabilityOptions.map((option) => (
              <li key={option.value}>
                <label className="choice">
                  <input
                    checked={selected.includes(option.value)}
                    onChange={(event) =>
                      setSelected((items) =>
                        event.currentTarget.checked
                          ? [...items, option.value]
                          : items.filter((item) => item !== option.value),
                      )
                    }
                    type="checkbox"
                    value={option.value}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    <span className="small muted">{option.description}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="form-actions">
            <SaveButton
              disabled={disabled || mutation.isPending}
              label="Funktionen speichern"
              pending={mutation.isPending}
              testId="save-capabilities"
            />
          </div>
        </fieldset>
      </form>
      <SectionError
        error={error}
        onReload={() => {
          setError(undefined);
          form.reset();
        }}
      />
    </EditSection>
  );
}

export function AdministratorsSection(props: SharedSectionProps) {
  const { client, disabled, state, updateState } = props;
  const action = state.action;
  const form = useSectionDraft<string[]>(
    "administrators",
    () =>
      state.administratorOptions
        .filter((option) => option.isResponsible)
        .map((option) => option.userId),
    props,
  );
  const { draft: selected, setDraft: setSelected } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setCharityActionResponsibleAdministrators(action.id, {
        revision: form.revision,
        userIds: selected,
      }),
    (updated) => {
      form.saved(selected, updated.action.revision);
      updateState(updated);
    },
    "Die verantwortlichen Admins wurden gespeichert.",
  );

  return (
    <EditSection
      description="Mindestens ein aktives Mitglied muss die Aktion weiter verwalten können."
      id="administrators"
      title="Verantwortliche Admins"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (selected.length === 0) {
            setError({
              code: null,
              conflict: false,
              message:
                "Wählen Sie mindestens einen verantwortlichen Charity-Admin aus.",
              requestId: null,
            });
            return;
          }
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Verantwortliche Admins</legend>
          <ul className="choice-list">
            {state.administratorOptions.map((option) => (
              <li key={option.userId}>
                <label
                  className="choice choice-person"
                  data-available={option.isAvailable}
                >
                  <input
                    checked={selected.includes(option.userId)}
                    data-testid={`administrator-${option.userId}`}
                    disabled={!option.isAvailable && !option.isResponsible}
                    onChange={(event) =>
                      setSelected((items) =>
                        event.currentTarget.checked
                          ? [...items, option.userId]
                          : items.filter((item) => item !== option.userId),
                      )
                    }
                    type="checkbox"
                  />
                  <Avatar name={option.displayName} />
                  <span>
                    <strong>{option.displayName}</strong>
                    <span className="small muted">{option.email}</span>
                  </span>
                  {!option.isAvailable ? (
                    <Badge tone="warn">
                      {option.isResponsible ? "Nicht mehr aktiv" : "Gesperrt"}
                    </Badge>
                  ) : null}
                </label>
              </li>
            ))}
          </ul>
          <div className="form-actions">
            <SaveButton
              disabled={disabled || mutation.isPending}
              label="Verantwortliche speichern"
              pending={mutation.isPending}
              testId="save-administrators"
            />
          </div>
        </fieldset>
      </form>
      <SectionError
        error={error}
        onReload={() => {
          setError(undefined);
          form.reset();
        }}
      />
    </EditSection>
  );
}

function localDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function isoDateTime(value: string): string {
  return new Date(value).toISOString();
}

export function PublicationSection(props: SharedSectionProps) {
  const { client, disabled, state, updateState } = props;
  const action = state.action;
  const form = useSectionDraft(
    "publication",
    () => ({
      alias: state.publicAlias ?? "",
      endsAt: localDateTime(state.action.publicationEndsAt),
      startsAt: localDateTime(state.action.publicationStartsAt),
    }),
    props,
  );
  const { draft, setDraft } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setCharityActionPublication(action.id, {
        publicAlias: draft.alias || null,
        publicationEndsAt: draft.endsAt ? isoDateTime(draft.endsAt) : null,
        publicationStartsAt: draft.startsAt
          ? isoDateTime(draft.startsAt)
          : null,
        revision: form.revision,
      }),
    (updated) => {
      form.saved(draft, updated.action.revision);
      updateState(updated);
    },
    "Die Einstellungen der öffentlichen Seite wurden gespeichert.",
  );
  const partialWindow = Boolean(draft.startsAt) !== Boolean(draft.endsAt);

  return (
    <EditSection
      description="Der aktive Alias zeigt im gewählten Zeitraum auf diese Aktion. Die Archiv-Adresse bleibt dauerhaft erreichbar."
      id="publication"
      title="Öffentliche Seite"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (partialWindow || (draft.alias && !draft.startsAt)) {
            setError({
              code: null,
              conflict: false,
              message:
                "Tragen Sie „Online ab“ und „Online bis“ gemeinsam ein. Ein aktiver Alias braucht einen vollständigen Zeitraum.",
              requestId: null,
            });
            return;
          }
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Öffentliche Seite</legend>
          <div className="form-row">
            <Field
              hint="Ab diesem Zeitpunkt ist die Aktion öffentlich erreichbar."
              label="Online ab"
            >
              <Input
                data-testid="publication-start"
                id="publication-start"
                onChange={(event) =>
                  setDraft({ ...draft, startsAt: event.currentTarget.value })
                }
                type="datetime-local"
                value={draft.startsAt}
              />
            </Field>
            <Field
              hint="Danach bleibt nur noch die Archiv-Adresse erreichbar."
              label="Online bis"
            >
              <Input
                data-testid="publication-end"
                id="publication-end"
                onChange={(event) =>
                  setDraft({ ...draft, endsAt: event.currentTarget.value })
                }
                type="datetime-local"
                value={draft.endsAt}
              />
            </Field>
          </div>
          <Field
            hint="Leicht merkbarer Teil der Adresse, zum Beispiel „krapfentaxi“."
            label="Aktiver Alias"
          >
            <Input
              className="mono"
              data-testid="publication-alias"
              id="publication-alias"
              maxLength={160}
              onChange={(event) =>
                setDraft({ ...draft, alias: event.currentTarget.value })
              }
              pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
              placeholder="krapfentaxi"
              value={draft.alias}
            />
          </Field>
          <div className="form-actions">
            <SaveButton
              disabled={disabled || mutation.isPending}
              label="Öffentliche Seite speichern"
              pending={mutation.isPending}
              testId="save-publication"
            />
          </div>
        </fieldset>
      </form>
      <SectionError
        error={error}
        onReload={() => {
          setError(undefined);
          form.reset();
        }}
      />
    </EditSection>
  );
}

const transitionCopy: Readonly<
  Record<
    ActionStatus,
    {
      readonly confirm: string;
      readonly next: string;
      readonly description: string;
      readonly tone: "danger" | "primary";
    }
  >
> = {
  active: {
    confirm: "Aktion aktivieren",
    next: "Aktion aktivieren.",
    description:
      "Die Aktion wechselt in den laufenden Betrieb. Danach kann sie nur noch abgeschlossen, nicht mehr in den Entwurf zurückgesetzt werden.",
    tone: "primary",
  },
  archived: {
    confirm: "Unwiderruflich archivieren",
    next: "Aktion archivieren.",
    description:
      "Die Aktion wird dauerhaft schreibgeschützt und ihr aktiver Alias für eine andere Aktion freigegeben. Dieser Schritt kann nicht rückgängig gemacht werden.",
    tone: "danger",
  },
  completed: {
    confirm: "Aktion abschließen",
    next: "Aktion abschließen.",
    description:
      "Die operative Phase endet. Die Aktion kann danach nicht erneut aktiviert, sondern nur noch archiviert werden.",
    tone: "danger",
  },
  draft: {
    confirm: "In Entwurf zurücksetzen",
    next: "Zurück in den Entwurf.",
    description:
      "Die Planung wird aufgehoben. Sie können Grunddaten weiter bearbeiten und die Aktion später erneut planen.",
    tone: "primary",
  },
  scheduled: {
    confirm: "Aktion einplanen",
    next: "Aktion einplanen.",
    description:
      "Die Aktion wird als geplant markiert. Bis zur Aktivierung kann sie noch in den Entwurf zurückgesetzt werden.",
    tone: "primary",
  },
};

/** The lifecycle order; the first allowed later status is the next step. */
const forward: readonly ActionStatus[] = [
  "draft",
  "scheduled",
  "active",
  "completed",
  "archived",
];

/**
 * The status change as the "Nächster Schritt" block (DESIGN.md Patterns):
 * the next status in the lifecycle is the one primary action, the other
 * allowed transitions are ghost alternatives. Each needs a confirmation;
 * the server decides with the revision.
 */
export function LifecycleNextStep({
  client,
  state,
  updateAction,
}: SharedSectionProps) {
  const action = state.action;
  const toast = useOptionalToast();
  const [target, setTarget] = useState<ActionStatus>();
  const [error, setError] = useState<ActionErrorMessage>();
  const mutation = useMutation({
    mutationFn: (next: ActionStatus) =>
      client.transitionCharityAction(action.id, {
        revision: action.revision,
        targetStatus: next,
      }),
    onSuccess(updated) {
      updateAction(updated);
      setError(undefined);
      setTarget(undefined);
      toast?.show({
        title: `Die Aktion ist jetzt „${statusLabels[updated.status]}“.`,
        tone: "success",
      });
    },
    onError(cause) {
      setError(actionErrorMessage(cause));
      setTarget(undefined);
    },
  });
  const allowed = state.allowedTransitions;
  if (allowed.length === 0) return null;
  const position = forward.indexOf(action.status);
  const primary =
    allowed
      .filter((next) => forward.indexOf(next) > position)
      .sort((a, b) => forward.indexOf(a) - forward.indexOf(b))[0] ??
    allowed[0]!;
  const others = allowed.filter((next) => next !== primary);
  const confirmation = target ? transitionCopy[target] : undefined;

  return (
    <>
      <NextStep
        action={
          <Button
            data-testid={`transition-${primary}`}
            disabled={mutation.isPending}
            onClick={() => setTarget(primary)}
            variant="primary"
          >
            {transitionCopy[primary].confirm}
          </Button>
        }
        alternatives={others.map((next) => (
          <Button
            data-testid={`transition-${next}`}
            disabled={mutation.isPending}
            key={next}
            onClick={() => setTarget(next)}
            variant="ghost"
          >
            {transitionCopy[next].confirm}
          </Button>
        ))}
        consequence={`${transitionCopy[primary].next} ${transitionCopy[primary].description}`}
        data-testid="action-next-step"
      />
      <SectionError error={error} />
      {confirmation && target ? (
        <ConfirmDialog
          confirmLabel={confirmation.confirm}
          description={confirmation.description}
          onConfirm={() => mutation.mutate(target)}
          onOpenChange={(open) => {
            if (!open && !mutation.isPending) setTarget(undefined);
          }}
          open
          pending={mutation.isPending}
          title={`${statusLabels[action.status]} → ${statusLabels[target]}`}
          tone={confirmation.tone}
        />
      ) : null}
    </>
  );
}
