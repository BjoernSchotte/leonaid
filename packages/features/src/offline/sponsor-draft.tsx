/*
 * A new sponsor without network (specs/pwa-offline-queue §10.4, D10): the
 * acquirer saves a draft on the device; the CRM match step runs online.
 * The street stays off the device (§8.2, privacy notice); a contact for
 * the draft can be captured at once and waits for the draft.
 */
import { Check, Save } from "lucide-react";
import { useState, type FormEvent } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  LeonAidApiClient,
  SponsorDraftRequest,
} from "@leonaid/api-client";
import { Button, Field, Icon, Input, StatusMessage } from "@leonaid/ui";

import { ContactSheet } from "../acquisition/contact-sheet";
import type { SponsorDraftEntry } from "./queue";
import { useOfflineRuntime } from "./runtime";

/** The contact sheet's view of a draft that has no assignment yet. */
export function draftWorkItem(
  entry: SponsorDraftEntry,
): AcquisitionActivityWorkItemResponse {
  return {
    assignedAcquirers: [],
    assignmentId: entry.assignmentId,
    city: entry.request.city ?? null,
    contactName:
      [entry.request.givenName, entry.request.familyName]
        .filter(Boolean)
        .join(" ") || null,
    dueAt: null,
    email: entry.request.email ?? null,
    nextAction: null,
    partyDisplayName: entry.party.displayName,
    partyId: entry.party.id,
    partyKind: entry.party.kind,
    phone: null,
    postalCode: null,
    priority: 0,
    revision: 0,
    status: "open",
    suppressedChannels: [],
    urgency: "none",
  };
}

export function draftDisplayName(
  mode: "company" | "person",
  draft: SponsorDraftRequest,
): string {
  return mode === "company"
    ? (draft.companyName ?? "").trim()
    : [draft.givenName, draft.familyName].filter(Boolean).join(" ").trim();
}

export function OfflineSponsorDraft({
  actionId,
  client,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
}) {
  const { queue } = useOfflineRuntime();
  const [mode, setMode] = useState<"company" | "person">("company");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SponsorDraftEntry | null>(null);
  const [contactOpen, setContactOpen] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!queue) return;
    const values = new FormData(event.currentTarget);
    const optional = (name: string) => {
      const value = String(values.get(name) ?? "").trim();
      return value || null;
    };
    const draft: SponsorDraftRequest =
      mode === "company"
        ? {
            city: optional("city"),
            companyName: optional("companyName"),
            email: optional("email"),
            familyName: optional("familyName"),
            givenName: optional("givenName"),
            postalCode: optional("postalCode"),
          }
        : {
            companyName: null,
            email: optional("email"),
            familyName: optional("familyName"),
            givenName: optional("givenName"),
          };
    if (mode === "company" && !draft.companyName) {
      setError("Bitte den Firmennamen angeben.");
      return;
    }
    if (mode === "person" && (!draft.givenName || !draft.familyName)) {
      setError("Bitte Vor- und Nachnamen angeben.");
      return;
    }
    setError(null);
    setSaved(await queue.saveDraft({ actionId, mode, request: draft }));
  }

  if (saved) {
    return (
      <div className="pwa-card" data-testid="sponsor-draft-saved">
        <span aria-hidden="true" className="pwa-done-icon">
          <Icon icon={Check} size={20} />
        </span>
        <h2 className="pwa-h2">Entwurf gespeichert</h2>
        <p>
          {saved.party.displayName} liegt als Entwurf auf diesem Gerät. Sobald
          du online bist, prüfst du ihn in der Warteschlange gegen das CRM.
        </p>
        <Button
          className="pwa-wide"
          data-testid="sponsor-draft-contact"
          onClick={() => setContactOpen(true)}
          size="lg"
          variant="primary"
        >
          Kontakt erfassen
        </Button>
        <Button
          className="pwa-wide"
          onClick={() => setSaved(null)}
          size="lg"
          variant="secondary"
        >
          Weiteren Sponsor erfassen
        </Button>
        <ContactSheet
          actionId={actionId}
          client={client}
          dependsOn={saved.entryId}
          item={draftWorkItem(saved)}
          onClose={() => setContactOpen(false)}
          open={contactOpen}
        />
      </div>
    );
  }

  return (
    <form
      className="stack"
      id="sponsor-draft-form"
      noValidate
      onSubmit={submit}
    >
      <StatusMessage tone="info">
        Du bist offline. Speichere den Sponsor als Entwurf; die Prüfung im CRM
        machst du, sobald du wieder online bist.
      </StatusMessage>
      <fieldset className="pwa-fieldset stack">
        <legend className="sr-only">Sponsor-Daten</legend>
        <div aria-label="Art des Sponsors" className="pwa-segment" role="group">
          <button
            aria-pressed={mode === "company"}
            onClick={() => setMode("company")}
            type="button"
          >
            Firma
          </button>
          <button
            aria-pressed={mode === "person"}
            onClick={() => setMode("person")}
            type="button"
          >
            Privatperson
          </button>
        </div>
        {mode === "company" ? (
          <Field label="Firmenname">
            <Input
              autoComplete="organization"
              data-testid="sponsor-draft-company"
              id="sponsor-draft-company"
              maxLength={300}
              name="companyName"
              required
            />
          </Field>
        ) : null}
        <Field
          label={mode === "company" ? "Vorname der Ansprechperson" : "Vorname"}
          optional={mode === "company"}
        >
          <Input
            autoComplete="given-name"
            id="sponsor-draft-given-name"
            maxLength={200}
            name="givenName"
          />
        </Field>
        <Field
          label={
            mode === "company" ? "Nachname der Ansprechperson" : "Nachname"
          }
          optional={mode === "company"}
        >
          <Input
            autoComplete="family-name"
            id="sponsor-draft-family-name"
            maxLength={200}
            name="familyName"
          />
        </Field>
        <Field label="E-Mail" optional>
          <Input
            autoComplete="email"
            id="sponsor-draft-email"
            maxLength={320}
            name="email"
            type="email"
          />
        </Field>
        {mode === "company" ? (
          <div className="pwa-two">
            <Field label="PLZ" optional>
              <Input
                autoComplete="postal-code"
                id="sponsor-draft-postal-code"
                maxLength={40}
                name="postalCode"
              />
            </Field>
            <Field label="Ort" optional>
              <Input
                autoComplete="address-level2"
                id="sponsor-draft-city"
                maxLength={200}
                name="city"
              />
            </Field>
          </div>
        ) : null}
        <p className="small muted">
          Die Straße ergänzt du bei der Prüfung; sie wird nicht auf dem Gerät
          gespeichert.
        </p>
      </fieldset>
      {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
      <Button
        className="pwa-wide"
        data-testid="sponsor-draft-save"
        icon={Save}
        size="lg"
        type="submit"
        variant="primary"
      >
        Als Entwurf speichern
      </Button>
    </form>
  );
}
