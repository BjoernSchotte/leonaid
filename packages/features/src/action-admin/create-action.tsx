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
            Starte mit dem neutralen Aktionskern. Alle Angaben lassen sich vor
            der Archivierung wieder bearbeiten.
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
              <input
                data-testid="action-name"
                maxLength={200}
                name="name"
                required
              />
            </label>
            <label className="action-field">
              <span>Träger</span>
              <input
                data-testid="action-carrier"
                maxLength={200}
                name="carrierName"
                required
              />
            </label>
            <label className="action-field">
              <span>Archiv-Slug</span>
              <input
                aria-describedby="archive-slug-help"
                data-testid="action-slug"
                maxLength={160}
                name="archiveSlug"
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                required
              />
              <small id="archive-slug-help">
                Dauerhafte URL: /archive/dein-slug
              </small>
            </label>
            <label className="action-field action-field--wide">
              <span>Zweck</span>
              <textarea
                data-testid="action-purpose"
                maxLength={2000}
                name="purpose"
                required
                rows={4}
              />
            </label>
            <label className="action-field">
              <span>Beginn</span>
              <input
                data-testid="action-start"
                name="startsOn"
                required
                type="date"
              />
            </label>
            <label className="action-field">
              <span>Ende</span>
              <input
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
              <span>Zielwert</span>
              <input
                data-testid="action-goal"
                inputMode="decimal"
                name="goalValue"
                required
              />
            </label>
            <label className="action-field">
              <span>Einheit</span>
              <input
                data-testid="action-unit"
                maxLength={40}
                name="unit"
                required
              />
            </label>
            <label className="action-field">
              <span>Ist-Wert</span>
              <input
                data-testid="action-actual"
                defaultValue="0"
                inputMode="decimal"
                name="actualValue"
                required
              />
            </label>
            <label className="action-field">
              <span>Währung (optional)</span>
              <input
                data-testid="action-currency"
                maxLength={3}
                name="currency"
                pattern="[A-Z]{3}"
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
                  <input
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
                  <textarea
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
