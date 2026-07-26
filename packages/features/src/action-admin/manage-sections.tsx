import {
  Add01Icon,
  Calendar03Icon,
  FloppyDiskIcon,
  Target01Icon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import type {
  ActionManagementResponse,
  CharityActionResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  ConfirmDialog,
  StatusMessage,
  type StatusTone,
} from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

type Capability = CharityActionResponse["capabilities"][number];
type ActionStatus = CharityActionResponse["status"];

interface Feedback {
  readonly conflict?: boolean;
  readonly message: string;
  readonly tone: StatusTone;
}

interface SharedSectionProps {
  readonly client: LeonAidApiClient;
  readonly disabled: boolean;
  readonly state: ActionManagementResponse;
  readonly updateAction: (action: CharityActionResponse) => void;
  readonly updateState: (state: ActionManagementResponse) => void;
}

function FeedbackMessage({ feedback }: { readonly feedback?: Feedback }) {
  if (!feedback) return null;
  return (
    <StatusMessage tone={feedback.tone}>
      <span>{feedback.message}</span>
      {feedback.conflict ? (
        <>
          {" "}
          <a
            href={`${window.location.pathname}${window.location.search}`}
            rel="noreferrer"
            target="_blank"
          >
            Aktuellen Stand in neuem Tab öffnen
          </a>
        </>
      ) : null}
    </StatusMessage>
  );
}

function success(message: string): Feedback {
  return { message, tone: "success" };
}

function failure(error: unknown): Feedback {
  const details = actionErrorMessage(error);
  return { ...details, tone: "error" };
}

export function DetailsSection({
  client,
  disabled,
  state,
  updateAction,
}: SharedSectionProps) {
  const action = state.action;
  const [draft, setDraft] = useState(() => ({
    carrierName: action.carrierName,
    endsOn: action.endsOn,
    name: action.name,
    purpose: action.purpose,
    startsOn: action.startsOn,
  }));
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: () =>
      client.setCharityActionDetails(action.id, {
        ...draft,
        revision: action.revision,
      }),
    onSuccess(updated) {
      updateAction(updated);
      setFeedback(success("Grunddaten und Zeitraum wurden gespeichert."));
    },
    onError(error) {
      setFeedback(failure(error));
    },
  });

  return (
    <section
      aria-labelledby="details-heading"
      className="action-edit-section"
      id="details"
    >
      <header>
        <div>
          <h2 id="details-heading">Grunddaten und Zeitraum</h2>
          <p>Name, Zweck, Träger und Laufzeit der Aktion.</p>
        </div>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFeedback(undefined);
          mutation.mutate();
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <div className="action-form-grid">
            <label className="action-field action-field--wide">
              <span>Name der Aktion</span>
              <small id="manage-name-help">
                Der öffentliche Titel mit Jahr, zum Beispiel „Krapfentaxi 2026“.
              </small>
              <input
                aria-describedby="manage-name-help"
                data-testid="manage-name"
                maxLength={200}
                onChange={(event) =>
                  setDraft({ ...draft, name: event.currentTarget.value })
                }
                required
                value={draft.name}
              />
            </label>
            <label className="action-field">
              <span>Träger</span>
              <small id="manage-carrier-help">
                Verein oder Organisation, die diese Aktion durchführt.
              </small>
              <input
                aria-describedby="manage-carrier-help"
                data-testid="manage-carrier"
                maxLength={200}
                onChange={(event) =>
                  setDraft({ ...draft, carrierName: event.currentTarget.value })
                }
                required
                value={draft.carrierName}
              />
            </label>
            <div className="action-field">
              <span>Archiv-Adresse</span>
              <small id="manage-archive-slug-help">
                Dauerhafte Adresse dieser Ausgabe; sie kann nicht geändert oder
                erneut vergeben werden.
              </small>
              <output
                aria-describedby="manage-archive-slug-help"
                data-testid="manage-archive-slug"
              >
                /archive/{action.archiveSlug}
              </output>
            </div>
            <label className="action-field action-field--wide">
              <span>Zweck</span>
              <small id="manage-purpose-help">
                Wofür die Aktion Spenden oder Erlöse sammelt.
              </small>
              <textarea
                aria-describedby="manage-purpose-help"
                data-testid="manage-purpose"
                maxLength={2000}
                onChange={(event) =>
                  setDraft({ ...draft, purpose: event.currentTarget.value })
                }
                required
                rows={4}
                value={draft.purpose}
              />
            </label>
            <label className="action-field">
              <span>Beginn</span>
              <small id="manage-start-help">
                Erster Tag des fachlichen Aktionszeitraums.
              </small>
              <input
                aria-describedby="manage-start-help"
                data-testid="manage-start"
                onChange={(event) =>
                  setDraft({ ...draft, startsOn: event.currentTarget.value })
                }
                required
                type="date"
                value={draft.startsOn}
              />
            </label>
            <label className="action-field">
              <span>Ende</span>
              <small id="manage-end-help">
                Letzter Tag; danach kann die Aktion abgeschlossen werden.
              </small>
              <input
                aria-describedby="manage-end-help"
                data-testid="manage-end"
                onChange={(event) =>
                  setDraft({ ...draft, endsOn: event.currentTarget.value })
                }
                required
                type="date"
                value={draft.endsOn}
              />
            </label>
          </div>
          <Button
            data-testid="save-details"
            disabled={disabled || mutation.isPending}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={FloppyDiskIcon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {mutation.isPending ? "Wird gespeichert …" : "Grunddaten speichern"}
          </Button>
        </fieldset>
      </form>
      <FeedbackMessage feedback={feedback} />
    </section>
  );
}

export function GoalSection({
  client,
  disabled,
  state,
  updateAction,
}: SharedSectionProps) {
  const action = state.action;
  const [draft, setDraft] = useState(() => ({
    actualValue: action.goal.actualValue,
    currency: action.goal.currency ?? "",
    goalValue: action.goal.goalValue ?? "",
    unit: action.goal.unit ?? "",
  }));
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: () =>
      client.setCharityActionGoal(action.id, {
        actualValue: draft.actualValue,
        currency: draft.currency || null,
        goalValue: draft.goalValue || null,
        revision: action.revision,
        unit: draft.unit || null,
      }),
    onSuccess(updated) {
      updateAction(updated);
      setFeedback(success("Aktionsziel und Fortschritt wurden gespeichert."));
    },
    onError(error) {
      setFeedback(failure(error));
    },
  });

  return (
    <section
      aria-labelledby="goal-heading"
      className="action-edit-section"
      id="goal"
    >
      <header>
        <div>
          <h2 id="goal-heading">Ziel und Fortschritt</h2>
          <p>Der aktuelle Stand zeigt allen Beteiligten den Fortschritt.</p>
        </div>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFeedback(undefined);
          mutation.mutate();
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <div className="action-form-grid">
            <label className="action-field">
              <span>Ziel</span>
              <small id="manage-goal-help">
                Messbarer Wert, den die Aktion erreichen soll.
              </small>
              <input
                aria-describedby="manage-goal-help"
                data-testid="manage-goal"
                inputMode="decimal"
                onChange={(event) =>
                  setDraft({ ...draft, goalValue: event.currentTarget.value })
                }
                value={draft.goalValue}
              />
            </label>
            <label className="action-field">
              <span>Einheit</span>
              <small id="manage-unit-help">
                Was gezählt wird, zum Beispiel Boxen, Bestellungen oder Euro.
              </small>
              <input
                aria-describedby="manage-unit-help"
                data-testid="manage-unit"
                maxLength={40}
                onChange={(event) =>
                  setDraft({ ...draft, unit: event.currentTarget.value })
                }
                value={draft.unit}
              />
            </label>
            <label className="action-field">
              <span>Aktueller Stand</span>
              <small id="manage-actual-help">
                Bereits erreichter Wert; er ist für Beteiligte sichtbar.
              </small>
              <input
                aria-describedby="manage-actual-help"
                data-testid="manage-actual"
                inputMode="decimal"
                onChange={(event) =>
                  setDraft({ ...draft, actualValue: event.currentTarget.value })
                }
                required
                value={draft.actualValue}
              />
            </label>
            <label className="action-field">
              <span>Währung (optional)</span>
              <small id="manage-currency-help">
                Nur bei Geldzielen: dreistelliger Code, zum Beispiel EUR.
              </small>
              <input
                aria-describedby="manage-currency-help"
                data-testid="manage-currency"
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
            </label>
          </div>
          <Button
            data-testid="save-goal"
            disabled={disabled || mutation.isPending}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={Target01Icon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {mutation.isPending ? "Wird gespeichert …" : "Ziel speichern"}
          </Button>
        </fieldset>
      </form>
      <FeedbackMessage feedback={feedback} />
    </section>
  );
}

interface BeneficiaryDraft {
  readonly key: number;
  readonly organizationName: string;
  readonly publicDescription: string;
}

export function BeneficiariesSection({
  client,
  disabled,
  state,
  updateAction,
}: SharedSectionProps) {
  const action = state.action;
  const [draft, setDraft] = useState<BeneficiaryDraft[]>(() =>
    action.beneficiaries.map((item, index) => ({
      key: index,
      organizationName: item.organizationName,
      publicDescription: item.publicDescription,
    })),
  );
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: () =>
      client.setCharityActionBeneficiaries(action.id, {
        beneficiaries: draft.map(({ organizationName, publicDescription }) => ({
          organizationName,
          publicDescription,
        })),
        revision: action.revision,
      }),
    onSuccess(updated) {
      updateAction(updated);
      setFeedback(success("Die Begünstigten wurden gespeichert."));
    },
    onError(error) {
      setFeedback(failure(error));
    },
  });

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
    <section
      aria-labelledby="beneficiaries-heading"
      className="action-edit-section"
      id="beneficiaries"
    >
      <header>
        <div>
          <h2 id="beneficiaries-heading">Begünstigte</h2>
          <p>Eine Aktion unterstützt eine oder mehrere Organisationen.</p>
        </div>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFeedback(undefined);
          mutation.mutate();
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <div className="action-beneficiary-list">
            {draft.map((beneficiary, index) => (
              <div className="action-beneficiary" key={beneficiary.key}>
                <label className="action-field">
                  <span>Name der Organisation</span>
                  <small id={`manage-beneficiary-name-help-${beneficiary.key}`}>
                    Organisation, die von den Erlösen der Aktion profitiert.
                  </small>
                  <input
                    aria-describedby={`manage-beneficiary-name-help-${beneficiary.key}`}
                    data-testid={`manage-beneficiary-name-${index}`}
                    maxLength={200}
                    onChange={(event) =>
                      change(
                        beneficiary.key,
                        "organizationName",
                        event.currentTarget.value,
                      )
                    }
                    required
                    value={beneficiary.organizationName}
                  />
                </label>
                <label className="action-field action-field--grow">
                  <span>Öffentliche Beschreibung</span>
                  <small
                    id={`manage-beneficiary-description-help-${beneficiary.key}`}
                  >
                    Kurzer Text für die öffentliche Aktionsseite.
                  </small>
                  <textarea
                    aria-describedby={`manage-beneficiary-description-help-${beneficiary.key}`}
                    data-testid={`manage-beneficiary-description-${index}`}
                    maxLength={2000}
                    onChange={(event) =>
                      change(
                        beneficiary.key,
                        "publicDescription",
                        event.currentTarget.value,
                      )
                    }
                    required
                    rows={3}
                    value={beneficiary.publicDescription}
                  />
                </label>
                {draft.length > 1 ? (
                  <Button
                    aria-label={`Begünstigten ${index + 1} entfernen`}
                    onClick={() =>
                      setDraft((items) =>
                        items.filter((item) => item.key !== beneficiary.key),
                      )
                    }
                    variant="ghost"
                  >
                    Entfernen
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
          <div className="action-inline-actions">
            <Button
              icon={
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={Add01Icon}
                  size={18}
                  strokeWidth={1.8}
                />
              }
              onClick={() =>
                setDraft((items) => [
                  ...items,
                  {
                    key: Math.max(...items.map((item) => item.key)) + 1,
                    organizationName: "",
                    publicDescription: "",
                  },
                ])
              }
              variant="secondary"
            >
              Begünstigten hinzufügen
            </Button>
            <Button
              data-testid="save-beneficiaries"
              disabled={disabled || mutation.isPending}
              icon={
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={FloppyDiskIcon}
                  size={18}
                  strokeWidth={1.8}
                />
              }
              type="submit"
            >
              {mutation.isPending
                ? "Wird gespeichert …"
                : "Begünstigte speichern"}
            </Button>
          </div>
        </fieldset>
      </form>
      <FeedbackMessage feedback={feedback} />
    </section>
  );
}

const capabilityOptions: ReadonlyArray<{
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
];

export function CapabilitiesSection({
  client,
  disabled,
  state,
  updateAction,
}: SharedSectionProps) {
  const action = state.action;
  const [selected, setSelected] = useState<Capability[]>(() => [
    ...action.capabilities,
  ]);
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: () =>
      client.setCharityActionCapabilities(action.id, {
        capabilities: selected,
        revision: action.revision,
      }),
    onSuccess(updated) {
      updateAction(updated);
      setFeedback(success("Die Funktionen der Aktion wurden gespeichert."));
    },
    onError(error) {
      setFeedback(failure(error));
    },
  });

  return (
    <section
      aria-labelledby="capabilities-heading"
      className="action-edit-section"
      id="capabilities"
    >
      <header>
        <div>
          <h2 id="capabilities-heading">Funktionen</h2>
          <p>Wähle nur die Bereiche, die diese Aktion wirklich braucht.</p>
        </div>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFeedback(undefined);
          mutation.mutate();
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <div className="action-choice-grid">
            {capabilityOptions.map((option) => (
              <label className="action-choice" key={option.value}>
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
                  <small>{option.description}</small>
                </span>
              </label>
            ))}
          </div>
          <p className="action-form-help">
            Bestellungen benötigen mindestens ein Angebot. LeonAid prüft diese
            Abhängigkeit beim Speichern.
          </p>
          <Button
            data-testid="save-capabilities"
            disabled={disabled || mutation.isPending}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={FloppyDiskIcon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {mutation.isPending ? "Wird gespeichert …" : "Funktionen speichern"}
          </Button>
        </fieldset>
      </form>
      <FeedbackMessage feedback={feedback} />
    </section>
  );
}

export function AdministratorsSection({
  client,
  disabled,
  state,
  updateState,
}: SharedSectionProps) {
  const action = state.action;
  const [selected, setSelected] = useState<string[]>(() =>
    state.administratorOptions
      .filter((option) => option.isResponsible)
      .map((option) => option.userId),
  );
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: () =>
      client.setCharityActionResponsibleAdministrators(action.id, {
        revision: action.revision,
        userIds: selected,
      }),
    onSuccess(updated) {
      updateState(updated);
      setFeedback(success("Die verantwortlichen Admins wurden gespeichert."));
    },
    onError(error) {
      setFeedback(failure(error));
    },
  });

  return (
    <section
      aria-labelledby="administrators-heading"
      className="action-edit-section"
      id="administrators"
    >
      <header>
        <div>
          <h2 id="administrators-heading">Verantwortliche Admins</h2>
          <p>
            Mindestens ein Mitglied muss die Aktion weiter verwalten können.
          </p>
        </div>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFeedback(undefined);
          if (selected.length === 0) {
            setFeedback({
              message:
                "Wähle mindestens einen verantwortlichen Charity-Admin aus.",
              tone: "error",
            });
            return;
          }
          mutation.mutate();
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <div className="action-admin-list">
            {state.administratorOptions.map((option) => (
              <label
                className="action-admin-option"
                data-available={option.isAvailable}
                key={option.userId}
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
                <span
                  className="action-admin-option__avatar"
                  aria-hidden="true"
                >
                  {option.displayName
                    .split(" ")
                    .slice(0, 2)
                    .map((part) => part[0])
                    .join("")}
                </span>
                <span>
                  <strong>{option.displayName}</strong>
                  <small>{option.email}</small>
                </span>
                {!option.isAvailable ? (
                  <em>
                    {option.isResponsible ? "Nicht mehr aktiv" : "Gesperrt"}
                  </em>
                ) : null}
              </label>
            ))}
          </div>
          <Button
            data-testid="save-administrators"
            disabled={disabled || mutation.isPending}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={UserGroupIcon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {mutation.isPending
              ? "Wird gespeichert …"
              : "Verantwortliche speichern"}
          </Button>
        </fieldset>
      </form>
      <FeedbackMessage feedback={feedback} />
    </section>
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

export function PublicationSection({
  client,
  disabled,
  state,
  updateState,
}: SharedSectionProps) {
  const action = state.action;
  const [draft, setDraft] = useState(() => ({
    alias: state.publicAlias ?? "",
    endsAt: localDateTime(action.publicationEndsAt),
    startsAt: localDateTime(action.publicationStartsAt),
  }));
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: () =>
      client.setCharityActionPublication(action.id, {
        publicAlias: draft.alias || null,
        publicationEndsAt: draft.endsAt ? isoDateTime(draft.endsAt) : null,
        publicationStartsAt: draft.startsAt
          ? isoDateTime(draft.startsAt)
          : null,
        revision: action.revision,
      }),
    onSuccess(updated) {
      updateState(updated);
      setFeedback(
        success("Die Einstellungen der öffentlichen Seite wurden gespeichert."),
      );
    },
    onError(error) {
      setFeedback(failure(error));
    },
  });
  const partialWindow = Boolean(draft.startsAt) !== Boolean(draft.endsAt);

  return (
    <section
      aria-labelledby="publication-heading"
      className="action-edit-section"
      id="publication"
    >
      <header>
        <div>
          <h2 id="publication-heading">Öffentliche Seite</h2>
          <p>
            Die Kurzadresse zeigt im gewählten Zeitraum auf diese Aktion. Die
            Archiv-Adresse bleibt dauerhaft erreichbar.
          </p>
        </div>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFeedback(undefined);
          if (partialWindow || (draft.alias && !draft.startsAt)) {
            setFeedback({
              message:
                "Trage „Online ab“ und „Online bis“ gemeinsam ein. Eine Kurzadresse benötigt einen vollständigen Zeitraum.",
              tone: "error",
            });
            return;
          }
          mutation.mutate();
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <div className="action-form-grid">
            <label className="action-field">
              <span>Online ab</span>
              <small id="publication-start-help">
                Ab diesem Zeitpunkt ist die Aktion öffentlich erreichbar.
              </small>
              <input
                aria-describedby="publication-start-help"
                data-testid="publication-start"
                onChange={(event) =>
                  setDraft({ ...draft, startsAt: event.currentTarget.value })
                }
                type="datetime-local"
                value={draft.startsAt}
              />
            </label>
            <label className="action-field">
              <span>Online bis</span>
              <small id="publication-end-help">
                Danach bleibt nur noch die Archiv-Adresse erreichbar.
              </small>
              <input
                aria-describedby="publication-end-help"
                data-testid="publication-end"
                onChange={(event) =>
                  setDraft({ ...draft, endsAt: event.currentTarget.value })
                }
                type="datetime-local"
                value={draft.endsAt}
              />
            </label>
            <label className="action-field action-field--wide">
              <span>Kurzadresse</span>
              <small id="publication-alias-help">
                Leicht merkbarer URL-Teil, zum Beispiel „krapfentaxi“.
              </small>
              <div className="action-prefixed-input">
                <span aria-hidden="true">/</span>
                <input
                  aria-describedby="publication-alias-help"
                  data-testid="publication-alias"
                  maxLength={160}
                  onChange={(event) =>
                    setDraft({ ...draft, alias: event.currentTarget.value })
                  }
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  value={draft.alias}
                />
              </div>
            </label>
          </div>
          <Button
            data-testid="save-publication"
            disabled={disabled || mutation.isPending}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={Calendar03Icon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {mutation.isPending
              ? "Wird gespeichert …"
              : "Öffentliche Seite speichern"}
          </Button>
        </fieldset>
      </form>
      <FeedbackMessage feedback={feedback} />
    </section>
  );
}

const statusLabels: Record<ActionStatus, string> = {
  active: "Aktiv",
  archived: "Archiviert",
  completed: "Abgeschlossen",
  draft: "Entwurf",
  scheduled: "Geplant",
};

const transitionCopy: Record<
  ActionStatus,
  {
    readonly confirm: string;
    readonly description: string;
    readonly tone: "danger" | "primary";
  }
> = {
  active: {
    confirm: "Aktion aktivieren",
    description:
      "Die Aktion wechselt in den laufenden Betrieb. Danach kann sie nur noch abgeschlossen, nicht mehr in den Entwurf zurückgesetzt werden.",
    tone: "primary",
  },
  archived: {
    confirm: "Unwiderruflich archivieren",
    description:
      "Die Aktion wird dauerhaft schreibgeschützt und ihre Kurzadresse für eine andere Aktion freigegeben. Dieser Schritt kann nicht rückgängig gemacht werden.",
    tone: "danger",
  },
  completed: {
    confirm: "Aktion abschließen",
    description:
      "Die operative Phase endet. Die Aktion kann danach nicht erneut aktiviert, sondern nur noch archiviert werden.",
    tone: "danger",
  },
  draft: {
    confirm: "In Entwurf zurücksetzen",
    description:
      "Die Planung wird aufgehoben. Du kannst Grunddaten weiter bearbeiten und die Aktion später erneut planen.",
    tone: "primary",
  },
  scheduled: {
    confirm: "Aktion einplanen",
    description:
      "Die Aktion wird als geplant markiert. Bis zur Aktivierung kann sie noch in den Entwurf zurückgesetzt werden.",
    tone: "primary",
  },
};

export function LifecycleSection({
  client,
  state,
  updateAction,
}: SharedSectionProps) {
  const action = state.action;
  const [target, setTarget] = useState<ActionStatus>();
  const [feedback, setFeedback] = useState<Feedback>();
  const mutation = useMutation({
    mutationFn: (next: ActionStatus) =>
      client.transitionCharityAction(action.id, {
        revision: action.revision,
        targetStatus: next,
      }),
    onSuccess(updated) {
      updateAction(updated);
      setFeedback(
        success(`Die Aktion ist jetzt „${statusLabels[updated.status]}“.`),
      );
      setTarget(undefined);
    },
    onError(error) {
      setFeedback(failure(error));
      setTarget(undefined);
    },
  });
  const confirmation = target ? transitionCopy[target] : undefined;

  return (
    <section
      aria-labelledby="lifecycle-heading"
      className="action-edit-section action-edit-section--lifecycle"
      id="lifecycle"
    >
      <header>
        <div>
          <h2 id="lifecycle-heading">Status der Aktion</h2>
          <p>
            Aktuell:{" "}
            <strong data-testid="action-status-label">
              {statusLabels[action.status]}
            </strong>
          </p>
        </div>
      </header>
      {state.allowedTransitions.length === 0 ? (
        <StatusMessage>
          Diese Aktion ist archiviert. Grunddaten und Konfiguration bleiben
          nachvollziehbar, können aber nicht mehr geändert werden.
        </StatusMessage>
      ) : (
        <div className="action-transition-list">
          {state.allowedTransitions.map((next) => (
            <Button
              data-testid={`transition-${next}`}
              disabled={mutation.isPending}
              key={next}
              onClick={() => setTarget(next)}
              variant={
                next === "completed" || next === "archived"
                  ? "danger"
                  : "secondary"
              }
            >
              {transitionCopy[next].confirm}
            </Button>
          ))}
        </div>
      )}
      <FeedbackMessage feedback={feedback} />
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
    </section>
  );
}
