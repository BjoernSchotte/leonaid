import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2, Search } from "lucide-react";
import { useRef, useState } from "react";

import {
  ApiError,
  type Case,
  type ContactCandidate,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  Field,
  Input,
  StatusLabel,
  StatusMessage,
  Textarea,
  useLeaveGuard,
} from "@leonaid/ui";

import { acceptCases, contactStateLabels, type Address } from "./inbox-model";

/** The case's contact state; the short form is the row chip. */
export function ContactStateLabel({
  state,
  short = false,
}: {
  readonly state: Case["contactStatus"];
  readonly short?: boolean;
}) {
  const label = contactStateLabels[state];
  return (
    <span className="inbox-contact-state" title={label.full}>
      <StatusLabel status={short ? label.short : label.full} />
    </span>
  );
}

function stateHint(item: Case, manage: boolean): string {
  switch (item.contactStatus) {
    case "linked":
      return "Mit einem Kontakt in Twenty verknüpft. Die Kontaktdaten in Twenty bleiben unverändert.";
    case "pending":
      return "Die Zuordnung läuft noch. Die Anfrage bleibt unabhängig davon bearbeitbar.";
    case "needs_review":
      return manage
        ? "Mehrere mögliche Kontakte gefunden. Bitte den richtigen auswählen."
        : "Mehrere mögliche Kontakte gefunden. Die Fallverwaltung wählt den richtigen aus.";
    case "failed":
      return manage
        ? "Die automatische Zuordnung ist fehlgeschlagen: kein eindeutiger Treffer in Twenty."
        : "Die automatische Zuordnung ist fehlgeschlagen. Die Fallverwaltung klärt den Kontakt.";
  }
}

/**
 * "Kontakt in Twenty": the matching state and, for the case management, the
 * deliberate confirmation of an existing Twenty person.
 */
export function InboxContact({
  address,
  client,
  item,
  manage,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly item: Case;
  /** Server permission `canManage` of this case. */
  readonly manage: boolean;
}) {
  const resolvable =
    manage &&
    (item.contactStatus === "needs_review" || item.contactStatus === "failed");
  return (
    <>
      <ContactStateLabel state={item.contactStatus} />
      <div className="case-gap stack">
        <p className="small muted">{stateHint(item, manage)}</p>
        {resolvable ? (
          <ContactMatch address={address} client={client} item={item} />
        ) : null}
      </div>
    </>
  );
}

function ContactMatch({
  address,
  client,
  item,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly item: Case;
}) {
  const cache = useQueryClient();
  const [givenName, setGivenName] = useState(item.givenName);
  const [familyName, setFamilyName] = useState(item.familyName);
  const [selected, setSelected] = useState<ContactCandidate | null>(null);
  const [revision, setRevision] = useState(item.contactRevision);
  const [note, setNote] = useState("");
  const operation = useRef(crypto.randomUUID());
  const sie = address === "Sie";
  useLeaveGuard(note.trim().length > 0);
  const search = useMutation({
    mutationFn: () =>
      client.listInboxContactCandidates(item.id, {
        givenName: givenName.trim(),
        familyName: familyName.trim(),
      }),
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("Kontakt auswählen");
      return client.confirmInboxContact(item.id, {
        personId: selected.personId,
        fingerprint: selected.fingerprint,
        expectedContactRevision: revision,
        note: note.trim(),
        idempotencyKey: operation.current,
      });
    },
    onSuccess: (value) => {
      acceptCases(cache, [value]);
      setSelected(null);
      setNote("");
      operation.current = crypto.randomUUID();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setSelected(null);
        search.reset();
        void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
      }
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
        setSelected(null);
        search.reset();
        void cache.invalidateQueries({
          queryKey: ["inbox-permissions", item.id],
        });
      }
    },
  });
  const changedSearch = () => {
    setSelected(null);
    search.reset();
    confirm.reset();
    operation.current = crypto.randomUUID();
  };
  const busy = search.isPending || confirm.isPending;
  return (
    <div className="stack" data-testid="inbox-contact-match">
      <form
        className="match-search"
        onSubmit={(event) => {
          event.preventDefault();
          setSelected(null);
          setRevision(item.contactRevision);
          operation.current = crypto.randomUUID();
          confirm.reset();
          search.mutate();
        }}
      >
        <Field id={`match-given-${item.id}`} label="Vorname">
          <Input
            disabled={busy}
            maxLength={200}
            onChange={(event) => {
              setGivenName(event.target.value);
              changedSearch();
            }}
            required
            value={givenName}
          />
        </Field>
        <Field id={`match-family-${item.id}`} label="Nachname">
          <Input
            disabled={busy}
            maxLength={200}
            onChange={(event) => {
              setFamilyName(event.target.value);
              changedSearch();
            }}
            required
            value={familyName}
          />
        </Field>
        <Button
          disabled={busy || !givenName.trim() || !familyName.trim()}
          icon={Search}
          loading={search.isPending}
          size="sm"
          type="submit"
          variant="secondary"
        >
          In Twenty suchen
        </Button>
      </form>
      {search.error ? (
        <StatusMessage tone="error">
          {sie
            ? "Twenty-Kontakte konnten nicht geladen werden. Prüfen Sie Ihren Zugriff oder versuchen Sie es später erneut."
            : "Twenty-Kontakte konnten nicht geladen werden. Prüfe deinen Zugriff oder versuche es später erneut."}
        </StatusMessage>
      ) : null}
      {search.isSuccess && !search.isPending ? (
        <>
          {search.data.truncated ? (
            <p className="small subtle">
              Es gibt mehr als 50 Treffer.{" "}
              {sie
                ? "Grenzen Sie die Namen weiter ein."
                : "Grenze die Namen weiter ein."}
            </p>
          ) : null}
          {search.data.items.length === 0 ? (
            <p className="small subtle">
              {sie
                ? "Kein Kontakt gefunden. Prüfen Sie die Schreibweise oder klären Sie den Kontakt in Twenty."
                : "Kein Kontakt gefunden. Prüfe die Schreibweise oder kläre den Kontakt in Twenty."}
            </p>
          ) : (
            <fieldset className="match-fieldset" disabled={confirm.isPending}>
              <legend className="sr-only">
                Kontakt anhand der Daten auswählen
              </legend>
              <ul aria-label="Treffer" className="match-results">
                {search.data.items.map((person) => (
                  <li key={person.personId}>
                    <label className="match-option">
                      <input
                        checked={selected?.personId === person.personId}
                        name={`inbox-contact-${item.id}`}
                        onChange={() => {
                          setSelected(person);
                          operation.current = crypto.randomUUID();
                          confirm.reset();
                        }}
                        type="radio"
                      />
                      <span>
                        <strong>
                          {person.givenName} {person.familyName}
                        </strong>
                        <span className="subtle small">
                          {person.email ?? "Keine E-Mail-Adresse"} ·{" "}
                          {person.phone ?? "Keine Telefonnummer"}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </fieldset>
          )}
        </>
      ) : null}
      {selected ? (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            confirm.mutate();
          }}
        >
          <Field
            hint={`Ausgewählt: ${selected.givenName} ${selected.familyName}. Die Kontaktdaten in Twenty werden nicht verändert.`}
            id={`match-note-${item.id}`}
            label="Begründung der Zuordnung"
          >
            <Textarea
              disabled={confirm.isPending}
              maxLength={2000}
              onChange={(event) => {
                setNote(event.target.value);
                operation.current = crypto.randomUUID();
                confirm.reset();
              }}
              required
              rows={3}
              value={note}
            />
          </Field>
          <div className="cluster">
            <Button
              disabled={confirm.isPending || !note.trim()}
              icon={Link2}
              loading={confirm.isPending}
              size="sm"
              type="submit"
              variant="primary"
            >
              Zuordnung bestätigen
            </Button>
          </div>
        </form>
      ) : null}
      {confirm.error ? (
        <StatusMessage tone="error">
          {confirm.error instanceof ApiError && confirm.error.status === 409
            ? `Der Kontakt, die Zuordnung oder der Auftrag wurde inzwischen geändert. ${
                sie
                  ? "Suchen Sie erneut und prüfen Sie"
                  : "Suche erneut und prüfe"
              } die aktuellen Daten. Die Begründung bleibt erhalten.`
            : `Die Zuordnung konnte nicht bestätigt werden. ${
                sie
                  ? "Prüfen Sie Ihren Zugriff oder versuchen Sie es später erneut."
                  : "Prüfe deinen Zugriff oder versuche es später erneut."
              } Die Begründung bleibt erhalten.`}
        </StatusMessage>
      ) : null}
    </div>
  );
}
