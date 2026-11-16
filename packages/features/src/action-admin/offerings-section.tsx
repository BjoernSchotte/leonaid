import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";

import type {
  CharityActionConfigurationResponse,
  ConfiguredOfferingResponse,
  OfferingDraftRequest,
} from "@leonaid/api-client";
import { Button, Field, Input, Select, Switch, Textarea } from "@leonaid/ui";

import {
  EditSection,
  SaveButton,
  SectionError,
  useSectionDraft,
  useSectionSave,
  type SharedSectionProps,
} from "./manage-sections";

type Unit = ConfiguredOfferingResponse["unit"];

interface OfferingRow {
  readonly id: string | null;
  readonly code: string;
  readonly name: string;
  readonly unit: Unit;
  readonly pieces: string;
  readonly price: string;
  /** Euro of the price that goes to the beneficiaries; empty: not stated. */
  readonly share: string;
  readonly active: boolean;
  /** `datetime-local` in the browser's time zone; empty: no deadline. */
  readonly until: string;
  /** Kept as stored; a new deadline opens the period now. */
  readonly availableFrom: string | null;
}

const unitLabels: Readonly<Record<Unit, string>> = {
  box: "Box",
  package: "Paket",
  piece: "Stück",
  sponsoring: "Sponsoring",
};

function euro(minor: number) {
  return (minor / 100).toFixed(2).replace(".", ",");
}

/** "20", "20,5" or "20,50" in euro; null when it is no amount. */
export function priceMinor(text: string): number | null {
  const value = text.trim().replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  return Math.round(Number(value) * 100);
}

function localInput(iso: string | null | undefined) {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function slug(text: string) {
  return (
    text
      .toLowerCase()
      .replace(/ä/g, "ae")
      .replace(/ö/g, "oe")
      .replace(/ü/g, "ue")
      .replace(/ß/g, "ss")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "angebot"
  );
}

function rowsFrom(
  offerings: readonly ConfiguredOfferingResponse[],
): OfferingRow[] {
  return offerings.map((offering) => ({
    id: offering.id,
    code: offering.code,
    name: offering.name,
    unit: offering.unit,
    pieces: offering.piecesPerUnit ? String(offering.piecesPerUnit) : "",
    price: euro(offering.unitPriceMinor),
    share:
      offering.donationShareMinor === null ||
      offering.donationShareMinor === undefined
        ? ""
        : euro(offering.donationShareMinor),
    active: offering.status === "active",
    until: localInput(offering.availableUntil),
    availableFrom: offering.availableFrom ?? null,
  }));
}

/** What is wrong with a row, for the form; null when it can be saved. */
function rowProblem(row: OfferingRow): string | null {
  if (!row.name.trim()) return "Bitte einen Namen angeben.";
  if (priceMinor(row.price) === null)
    return "Bitte einen Preis in Euro angeben, zum Beispiel 20,00.";
  if (row.share.trim()) {
    const share = priceMinor(row.share);
    if (share === null) return "Bitte den Spendenanteil in Euro angeben.";
    if (share > (priceMinor(row.price) ?? 0))
      return "Der Spendenanteil ist höchstens so hoch wie der Preis.";
  }
  if (row.unit === "box" && !/^\d{1,5}$/.test(row.pieces.trim()))
    return "Eine Box braucht die Stückzahl.";
  if (row.pieces.trim() && !/^\d{1,5}$/.test(row.pieces.trim()))
    return "Die Stückzahl ist eine ganze Zahl.";
  if (row.until && Number.isNaN(Date.parse(row.until)))
    return "Bitte einen gültigen Bestellschluss angeben.";
  return null;
}

function request(rows: readonly OfferingRow[]): OfferingDraftRequest[] {
  const codes = new Set<string>();
  return rows.map((row) => {
    let code = row.code || slug(`${row.name} ${row.pieces}`);
    for (let suffix = 2; codes.has(code); suffix += 1)
      code = `${slug(`${row.name} ${row.pieces}`)}-${suffix}`;
    codes.add(code);
    const until = row.until ? new Date(row.until).toISOString() : null;
    const from = until
      ? (row.availableFrom ?? new Date(Date.now() - 60_000).toISOString())
      : null;
    return {
      ...(row.id ? { id: row.id } : {}),
      active: row.active,
      availableFrom: from,
      availableUntil: until,
      code,
      currency: "EUR",
      name: row.name.trim(),
      piecesPerUnit: row.pieces.trim() ? Number(row.pieces.trim()) : null,
      unit: row.unit,
      unitPriceMinor: priceMinor(row.price) ?? 0,
      donationShareMinor: row.share.trim() ? priceMinor(row.share) : null,
    };
  });
}

/**
 * "Angebote" in the edit mode (E-068): sizes, prices and the order
 * deadline. Existing orders keep the price and size they were taken with.
 */
export function OfferingsSection(
  props: SharedSectionProps & {
    readonly configuration: CharityActionConfigurationResponse;
  },
) {
  const { client, configuration, disabled, state, updateAction } = props;
  const form = useSectionDraft(
    "offerings",
    () => rowsFrom(configuration.offerings),
    props,
  );
  const { draft, setDraft } = form;
  const problems = draft.map(rowProblem);
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.replaceActionOfferings(state.action.id, {
        expectedRevision: form.revision,
        offerings: request(draft),
      }),
    (result) => {
      const rows = rowsFrom(result.offerings);
      setDraft(rows);
      form.saved(rows, result.action.revision);
      updateAction(result.action);
    },
    "Die Angebote wurden gespeichert.",
  );
  const update = (index: number, change: Partial<OfferingRow>) =>
    setDraft(
      draft.map((row, position) =>
        position === index ? { ...row, ...change } : row,
      ),
    );

  return (
    <EditSection
      description="Größen, Preise und Bestellschluss. Bestehende Bestellungen behalten Preis und Größe, mit denen sie aufgegeben wurden."
      id="offerings"
      title="Angebote"
    >
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (problems.some(Boolean)) return;
          mutation.mutate();
        }}
      >
        <fieldset
          className="form-grid"
          disabled={disabled || mutation.isPending}
        >
          <legend className="sr-only">Angebote</legend>
          {draft.map((row, index) => (
            <div
              className="offering-row stack"
              data-testid={`offering-row-${index}`}
              key={row.id ?? `new-${index}`}
            >
              <div className="form-row">
                <Field error={problems[index] ?? undefined} label="Name">
                  <Input
                    data-testid={`offering-name-${index}`}
                    maxLength={200}
                    onChange={(event) =>
                      update(index, { name: event.currentTarget.value })
                    }
                    value={row.name}
                  />
                </Field>
                <Field label="Einheit">
                  <Select
                    onChange={(event) =>
                      update(index, {
                        unit: event.currentTarget.value as Unit,
                      })
                    }
                    value={row.unit}
                  >
                    {(Object.keys(unitLabels) as Unit[]).map((unit) => (
                      <option key={unit} value={unit}>
                        {unitLabels[unit]}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <div className="form-row">
                <Field hint="Stück pro Einheit" label="Stück" optional>
                  <Input
                    data-testid={`offering-pieces-${index}`}
                    inputMode="numeric"
                    onChange={(event) =>
                      update(index, { pieces: event.currentTarget.value })
                    }
                    value={row.pieces}
                  />
                </Field>
                <Field hint="Je Einheit, in Euro" label="Preis">
                  <Input
                    data-testid={`offering-price-${index}`}
                    inputMode="decimal"
                    onChange={(event) =>
                      update(index, { price: event.currentTarget.value })
                    }
                    value={row.price}
                  />
                </Field>
                <Field
                  hint="Je Einheit; die Seite nennt ihn beim Preis."
                  label="Spendenanteil"
                  optional
                >
                  <Input
                    data-testid={`offering-share-${index}`}
                    inputMode="decimal"
                    onChange={(event) =>
                      update(index, { share: event.currentTarget.value })
                    }
                    value={row.share}
                  />
                </Field>
                <Field
                  hint="Danach bietet das Formular es nicht mehr an. Ortszeit."
                  label="Bestellschluss"
                  optional
                >
                  <Input
                    data-testid={`offering-until-${index}`}
                    onChange={(event) =>
                      update(index, { until: event.currentTarget.value })
                    }
                    type="datetime-local"
                    value={row.until}
                  />
                </Field>
              </div>
              <div className="tab-head">
                <label className="buyer-mail-switch-text">
                  <Switch
                    checked={row.active}
                    data-testid={`offering-active-${index}`}
                    onChange={(event) =>
                      update(index, { active: event.currentTarget.checked })
                    }
                  />{" "}
                  Im Bestellformular anbieten
                </label>
                <Button
                  data-testid={`offering-remove-${index}`}
                  icon={Trash2}
                  onClick={() =>
                    setDraft(draft.filter((_, position) => position !== index))
                  }
                  size="sm"
                  variant="ghost"
                >
                  Entfernen
                </Button>
              </div>
            </div>
          ))}
          <div className="form-actions">
            <Button
              data-testid="offering-add"
              icon={Plus}
              onClick={() =>
                setDraft([
                  ...draft,
                  {
                    id: null,
                    code: "",
                    name: "",
                    unit: "box",
                    pieces: "",
                    price: "",
                    share: "",
                    active: true,
                    until: draft.find((row) => row.until)?.until ?? "",
                    availableFrom: null,
                  },
                ])
              }
              variant="secondary"
            >
              Angebot hinzufügen
            </Button>
            <SaveButton
              disabled={disabled || mutation.isPending || !form.dirty}
              label="Angebote speichern"
              pending={mutation.isPending}
              testId="save-offerings"
            />
          </div>
          <p className="small subtle">
            Ein Angebot mit Bestellungen lässt sich nicht entfernen; schalten
            Sie es stattdessen aus.
          </p>
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

interface OptionsDraft {
  readonly newsletter: string;
  readonly photos: string;
  readonly withdrawal: string;
}

/**
 * "Zusätze im Bestellformular" (E-068): two optional checkboxes and the
 * notice on the right of withdrawal. Empty fields show nothing.
 */
export function OrderFormOptionsSection(
  props: SharedSectionProps & {
    readonly orderForm: NonNullable<
      CharityActionConfigurationResponse["orderForm"]
    >;
  },
) {
  const { client, disabled, orderForm, state } = props;
  const cache = useQueryClient();
  const form = useSectionDraft<OptionsDraft>(
    "order-form-options",
    () => ({
      newsletter: orderForm.newsletterConsentText ?? "",
      photos: orderForm.photoConsentText ?? "",
      withdrawal: orderForm.withdrawalNotice ?? "",
    }),
    props,
  );
  const { draft, setDraft } = form;
  const { error, mutation, setError } = useSectionSave(
    () =>
      client.setOrderFormOptions(state.action.id, {
        newsletterConsentText: draft.newsletter.trim() || null,
        photoConsentText: draft.photos.trim() || null,
        withdrawalNotice: draft.withdrawal.trim() || null,
      }),
    (result) => {
      cache.setQueryData(["action-configuration", state.action.id], result);
      form.saved(draft, form.revision);
    },
    "Die Zusätze im Bestellformular wurden gespeichert.",
  );
  const tooShort = (text: string) =>
    text.trim() && text.trim().length < 10
      ? "Mindestens 10 Zeichen, oder leer lassen."
      : undefined;

  return (
    <EditSection
      description="Freiwillige Einwilligungen und ein Hinweis über dem Bestellknopf. Leere Felder erscheinen nicht im Formular. Jede Bestellung hält fest, welchem Wortlaut zugestimmt wurde."
      id="order-form-options"
      title="Zusätze im Bestellformular"
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
          <legend className="sr-only">Zusätze im Bestellformular</legend>
          <Field
            error={tooShort(draft.newsletter)}
            hint="Häkchen für Informationen zu weiteren Aktivitäten. Wird als Einwilligung gespeichert und lässt sich über den Datenschutz widerrufen."
            label="Newsletter-Einwilligung"
            optional
          >
            <Textarea
              data-testid="order-option-newsletter"
              maxLength={600}
              onChange={(event) =>
                setDraft({ ...draft, newsletter: event.currentTarget.value })
              }
              rows={2}
              value={draft.newsletter}
            />
          </Field>
          <Field
            error={tooShort(draft.photos)}
            hint="Häkchen für Fotos bei der Lieferung. Die Fahrer sehen auf ihrer Tour, ob es gesetzt ist."
            label="Foto-Einwilligung"
            optional
          >
            <Textarea
              data-testid="order-option-photos"
              maxLength={600}
              onChange={(event) =>
                setDraft({ ...draft, photos: event.currentTarget.value })
              }
              rows={2}
              value={draft.photos}
            />
          </Field>
          <Field
            error={tooShort(draft.withdrawal)}
            hint="Steht über dem Bestellknopf. Rechtlich prüfen lassen."
            label="Hinweis zum Widerrufsrecht"
            optional
          >
            <Textarea
              data-testid="order-option-withdrawal"
              maxLength={1000}
              onChange={(event) =>
                setDraft({ ...draft, withdrawal: event.currentTarget.value })
              }
              rows={3}
              value={draft.withdrawal}
            />
          </Field>
          <div className="form-actions">
            <SaveButton
              disabled={
                disabled ||
                mutation.isPending ||
                !form.dirty ||
                Boolean(
                  tooShort(draft.newsletter) ||
                    tooShort(draft.photos) ||
                    tooShort(draft.withdrawal),
                )
              }
              label="Zusätze speichern"
              pending={mutation.isPending}
              testId="save-order-form-options"
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
