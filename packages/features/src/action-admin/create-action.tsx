import {
  Add01Icon,
  ArrowLeft01Icon,
  CharityIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import {
  type ActionGoalRequest,
  type BeneficiaryDraftRequest,
  type CreateCharityActionRequest,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

type Capability = CreateCharityActionRequest["capabilities"][number];

interface BeneficiaryDraft extends BeneficiaryDraftRequest {
  readonly key: number;
}

const capabilities: ReadonlyArray<{
  readonly description: string;
  readonly label: string;
  readonly value: Capability;
}> = [
  {
    description: "Firmen, Kontakte und Aktivitäten zur Sponsorengewinnung.",
    label: "Akquise",
    value: "acquisition",
  },
  {
    description: "Aktionsangebote wie Krapfenboxen oder Sponsorings.",
    label: "Angebote",
    value: "offerings",
  },
  {
    description: "Zusagen und öffentliche Bestellungen erfassen.",
    label: "Bestellungen",
    value: "ordering",
  },
  {
    description: "Rechnungen erzeugen, versenden und nachverfolgen.",
    label: "Rechnungen",
    value: "invoicing",
  },
];

export interface CreateActionPageProps {
  readonly client: LeonAidApiClient;
}

export function CreateActionPage({ client }: CreateActionPageProps) {
  const [beneficiaries, setBeneficiaries] = useState<BeneficiaryDraft[]>([
    { key: 0, organizationName: "", publicDescription: "" },
  ]);
  const [created, setCreated] = useState<{ id: string; name: string }>();
  const [error, setError] = useState<string>();
  const mutation = useMutation({
    mutationFn: (draft: CreateCharityActionRequest) =>
      client.createCharityAction(draft),
    onSuccess(action) {
      setCreated({ id: action.id, name: action.name });
      setError(undefined);
    },
    onError(cause) {
      setCreated(undefined);
      setError(actionErrorMessage(cause).message);
    },
  });

  function updateBeneficiary(
    key: number,
    field: "organizationName" | "publicDescription",
    value: string,
  ) {
    setBeneficiaries((items) =>
      items.map((item) =>
        item.key === key ? { ...item, [field]: value } : item,
      ),
    );
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(undefined);
    setCreated(undefined);
    const values = new FormData(event.currentTarget);
    const currency = String(values.get("currency") ?? "").trim();
    const goal: ActionGoalRequest = {
      actualValue: String(values.get("actualValue") ?? "0"),
      currency: currency || null,
      goalValue: String(values.get("goalValue") ?? ""),
      unit: String(values.get("unit") ?? ""),
    };
    mutation.mutate({
      archiveSlug: String(values.get("archiveSlug") ?? ""),
      beneficiaries: beneficiaries.map(
        ({ organizationName, publicDescription }) => ({
          organizationName,
          publicDescription,
        }),
      ),
      capabilities: values.getAll("capability").map(String) as Capability[],
      carrierName: String(values.get("carrierName") ?? ""),
      endsOn: String(values.get("endsOn") ?? ""),
      goal,
      name: String(values.get("name") ?? ""),
      purpose: String(values.get("purpose") ?? ""),
      startsOn: String(values.get("startsOn") ?? ""),
    });
  }

  return (
    <div className="action-page action-page--form">
      <a className="action-back" href="/admin/actions">
        <HugeiconsIcon
          aria-hidden="true"
          icon={ArrowLeft01Icon}
          size={18}
          strokeWidth={1.8}
        />
        Alle Aktionen
      </a>
      <header className="action-page__header">
        <div>
          <p className="action-page__eyebrow">Neue Charity-Aktion</p>
          <h1>Neue Aktion anlegen</h1>
          <p>
            Lege die gemeinsamen Eckdaten fest. Bis zur Archivierung kannst du
            alle Angaben wieder bearbeiten.
          </p>
        </div>
      </header>

      <ol aria-label="Schritte" className="action-step-overview">
        <li>
          <span>1</span> Grunddaten
        </li>
        <li>
          <span>2</span> Funktionen &amp; Ziel
        </li>
        <li>
          <span>3</span> Begünstigte
        </li>
      </ol>

      <form className="action-form-stack" id="action-form" onSubmit={submit}>
        <fieldset className="action-section">
          <legend>
            <span>1</span>
            <div>
              <strong>Grunddaten und Zeitraum</strong>
              <small>
                Wofür findet die Aktion statt und wie lange läuft sie?
              </small>
            </div>
          </legend>
          <div className="action-form-grid">
            <label className="action-field action-field--wide">
              <span>Name der Aktion</span>
              <small id="action-name-help">
                Der öffentliche Titel mit Jahr, zum Beispiel „Krapfentaxi 2026“.
              </small>
              <input
                aria-describedby="action-name-help"
                data-testid="action-name"
                maxLength={200}
                name="name"
                placeholder="Krapfentaxi 2026"
                required
              />
            </label>
            <label className="action-field">
              <span>Träger</span>
              <small id="action-carrier-help">
                Verein oder Organisation, die diese Aktion durchführt.
              </small>
              <input
                aria-describedby="action-carrier-help"
                data-testid="action-carrier"
                maxLength={200}
                name="carrierName"
                placeholder="Lions Hilfswerk Musterstadt e. V."
                required
              />
            </label>
            <label className="action-field">
              <span>Archiv-Adresse</span>
              <small id="archive-slug-help">
                Kurzer URL-Teil ohne Leerzeichen, zum Beispiel
                „krapfentaxi-2026“.
              </small>
              <input
                aria-describedby="archive-slug-help"
                data-testid="action-slug"
                maxLength={160}
                name="archiveSlug"
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                placeholder="krapfentaxi-2026"
                required
              />
            </label>
            <label className="action-field action-field--wide">
              <span>Zweck</span>
              <small id="action-purpose-help">
                Wofür die Aktion Spenden oder Erlöse sammelt.
              </small>
              <textarea
                aria-describedby="action-purpose-help"
                data-testid="action-purpose"
                maxLength={2000}
                name="purpose"
                placeholder="Wir unterstützen lokale Projekte für Kinder und Jugendliche."
                required
                rows={4}
              />
            </label>
            <label className="action-field">
              <span>Beginn</span>
              <small id="action-start-help">
                Erster Tag des fachlichen Aktionszeitraums.
              </small>
              <input
                aria-describedby="action-start-help"
                data-testid="action-start"
                name="startsOn"
                required
                type="date"
              />
            </label>
            <label className="action-field">
              <span>Ende</span>
              <small id="action-end-help">
                Letzter Tag; danach kann die Aktion abgeschlossen werden.
              </small>
              <input
                aria-describedby="action-end-help"
                data-testid="action-end"
                name="endsOn"
                required
                type="date"
              />
            </label>
          </div>
        </fieldset>

        <fieldset className="action-section">
          <legend>
            <span>2</span>
            <div>
              <strong>Funktionen und Aktionsziel</strong>
              <small>Aktiviere nur, was diese Aktion wirklich benötigt.</small>
            </div>
          </legend>
          <div className="action-choice-grid">
            {capabilities.map((capability) => (
              <label className="action-choice" key={capability.value}>
                <input
                  name="capability"
                  type="checkbox"
                  value={capability.value}
                />
                <span>
                  <strong>{capability.label}</strong>
                  <small>{capability.description}</small>
                </span>
              </label>
            ))}
          </div>
          <div className="action-form-grid action-form-grid--spaced">
            <label className="action-field">
              <span>Ziel</span>
              <small id="action-goal-help">
                Messbarer Wert, den die Aktion erreichen soll.
              </small>
              <input
                aria-describedby="action-goal-help"
                data-testid="action-goal"
                inputMode="decimal"
                name="goalValue"
                placeholder="1000"
                required
              />
            </label>
            <label className="action-field">
              <span>Einheit</span>
              <small id="action-unit-help">
                Was gezählt wird, zum Beispiel Boxen, Bestellungen oder Euro.
              </small>
              <input
                aria-describedby="action-unit-help"
                data-testid="action-unit"
                maxLength={40}
                name="unit"
                placeholder="Boxen"
                required
              />
            </label>
            <label className="action-field">
              <span>Aktueller Stand</span>
              <small id="action-actual-help">
                Bereits erreichter Wert; eine neue Aktion startet meist bei 0.
              </small>
              <input
                aria-describedby="action-actual-help"
                data-testid="action-actual"
                defaultValue="0"
                inputMode="decimal"
                name="actualValue"
                required
              />
            </label>
            <label className="action-field">
              <span>Währung (optional)</span>
              <small id="action-currency-help">
                Nur bei Geldzielen: dreistelliger Code, zum Beispiel EUR.
              </small>
              <input
                aria-describedby="action-currency-help"
                data-testid="action-currency"
                maxLength={3}
                name="currency"
                pattern="[A-Z]{3}"
                placeholder="EUR"
              />
            </label>
          </div>
        </fieldset>

        <fieldset className="action-section">
          <legend>
            <span>3</span>
            <div>
              <strong>Begünstigte</strong>
              <small>
                Mindestens eine Organisation profitiert von der Aktion.
              </small>
            </div>
          </legend>
          <div className="action-beneficiary-list">
            {beneficiaries.map((beneficiary, index) => (
              <div className="action-beneficiary" key={beneficiary.key}>
                <label className="action-field">
                  <span>Name der Organisation</span>
                  <small id={`beneficiary-name-help-${beneficiary.key}`}>
                    Organisation, die von den Erlösen der Aktion profitiert.
                  </small>
                  <input
                    aria-describedby={`beneficiary-name-help-${beneficiary.key}`}
                    data-testid={`beneficiary-name-${index}`}
                    maxLength={200}
                    name={`beneficiaryName-${beneficiary.key}`}
                    onChange={(event) =>
                      updateBeneficiary(
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
                  <small id={`beneficiary-description-help-${beneficiary.key}`}>
                    Kurzer Text für die öffentliche Aktionsseite.
                  </small>
                  <textarea
                    aria-describedby={`beneficiary-description-help-${beneficiary.key}`}
                    data-testid={`beneficiary-description-${index}`}
                    maxLength={2000}
                    name={`beneficiaryDescription-${beneficiary.key}`}
                    onChange={(event) =>
                      updateBeneficiary(
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
                {beneficiaries.length > 1 ? (
                  <Button
                    aria-label={`Begünstigten ${index + 1} entfernen`}
                    onClick={() =>
                      setBeneficiaries((items) =>
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
          <Button
            data-testid="add-beneficiary"
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={Add01Icon}
                size={18}
                strokeWidth={1.8}
              />
            }
            onClick={() =>
              setBeneficiaries((items) => [
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
            Weiteren Begünstigten hinzufügen
          </Button>
        </fieldset>

        {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
        {created ? (
          <StatusMessage tone="success">
            <span
              data-action-id={created.id}
              data-state="success"
              id="action-status"
            >
              {created.name} wurde als Entwurf angelegt.{" "}
              <a href={`/admin/actions/${created.id}`}>
                Aktion jetzt verwalten
              </a>
            </span>
          </StatusMessage>
        ) : (
          <span
            aria-live="polite"
            data-state={error ? "error" : ""}
            id="action-status"
          >
            {error}
          </span>
        )}

        <div className="action-form-actions">
          <Button
            data-testid="action-submit"
            disabled={mutation.isPending}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={CharityIcon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {mutation.isPending
              ? "Aktion wird angelegt …"
              : "Aktion als Entwurf anlegen"}
          </Button>
        </div>
      </form>
    </div>
  );
}
