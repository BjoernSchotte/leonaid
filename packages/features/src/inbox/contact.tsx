import { Search01Icon, Tick02Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  ApiError,
  type Case,
  type ContactCandidate,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export function InboxContact({
  client,
  item,
}: {
  client: LeonAidApiClient;
  item: Case;
}) {
  const cache = useQueryClient();
  const [givenName, setGivenName] = useState(item.givenName);
  const [familyName, setFamilyName] = useState(item.familyName);
  const [selected, setSelected] = useState<ContactCandidate | null>(null);
  const [revision, setRevision] = useState(item.contactRevision);
  const [note, setNote] = useState("");
  const operation = useRef(crypto.randomUUID());
  const permissions = useQuery({
    queryKey: ["inbox-permissions", item.id],
    queryFn: () => client.getInboxCasePermissions(item.id),
    retry: false,
  });
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
      cache.setQueryData(["inbox-case", item.id], value);
      void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
      setSelected(null);
      setNote("");
      operation.current = crypto.randomUUID();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setSelected(null);
        search.reset();
        void cache.invalidateQueries({ queryKey: ["inbox-case", item.id] });
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
  if (
    !permissions.data?.canManage ||
    permissions.error ||
    !["needs_review", "failed"].includes(item.contactStatus)
  )
    return null;
  const changedSearch = () => {
    setSelected(null);
    search.reset();
    confirm.reset();
    operation.current = crypto.randomUUID();
  };
  return (
    <div className="inbox-contact-resolution">
      <p>
        Prüfe einen bestehenden Twenty-Kontakt und bestätige die Zuordnung
        bewusst. Die Kontaktdaten in Twenty werden dabei nicht verändert.
      </p>
      <form
        className="inbox-form"
        onSubmit={(event) => {
          event.preventDefault();
          setSelected(null);
          setRevision(item.contactRevision);
          operation.current = crypto.randomUUID();
          confirm.reset();
          search.mutate();
        }}
      >
        <fieldset disabled={search.isPending || confirm.isPending}>
          <legend>Bestehenden Kontakt suchen</legend>
          <label>
            Vorname
            <input
              required
              maxLength={200}
              value={givenName}
              onChange={(event) => {
                setGivenName(event.target.value);
                changedSearch();
              }}
            />
          </label>
          <label>
            Nachname
            <input
              required
              maxLength={200}
              value={familyName}
              onChange={(event) => {
                setFamilyName(event.target.value);
                changedSearch();
              }}
            />
          </label>
          <Button
            icon={
              <HugeiconsIcon
                icon={Search01Icon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="primary"
            type="submit"
            disabled={!givenName.trim() || !familyName.trim()}
          >
            {search.isPending ? "Wird gesucht …" : "In Twenty suchen"}
          </Button>
        </fieldset>
      </form>
      {search.error && (
        <StatusMessage tone="error">
          <p>
            Twenty-Kontakte konnten nicht geladen werden. Prüfe deinen Zugriff
            oder versuche es später erneut.
          </p>
        </StatusMessage>
      )}
      {search.isSuccess && !search.isPending && (
        <>
          {search.data.truncated && (
            <p>Es gibt mehr als 50 Treffer. Grenze die Namen weiter ein.</p>
          )}
          {search.data.items.length === 0 ? (
            <p>
              Kein passender Kontakt gefunden. Prüfe die Schreibweise oder kläre
              den Kontakt in Twenty.
            </p>
          ) : (
            <fieldset
              className="inbox-contact-options"
              disabled={confirm.isPending}
            >
              <legend>Kontakt anhand der Daten auswählen</legend>
              {search.data.items.map((person) => (
                <label key={person.personId}>
                  <input
                    type="radio"
                    name={`inbox-contact-${item.id}`}
                    checked={selected?.personId === person.personId}
                    onChange={() => {
                      setSelected(person);
                      operation.current = crypto.randomUUID();
                      confirm.reset();
                    }}
                  />
                  <span>
                    <strong>
                      {person.givenName} {person.familyName}
                    </strong>
                    <span>{person.email ?? "Keine E-Mail-Adresse"}</span>
                    <span>{person.phone ?? "Keine Telefonnummer"}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          )}
        </>
      )}
      {selected && (
        <form
          className="inbox-form"
          onSubmit={(event) => {
            event.preventDefault();
            confirm.mutate();
          }}
        >
          <p>
            Ausgewählt:{" "}
            <strong>
              {selected.givenName} {selected.familyName}
            </strong>
            . Vergleiche die Kontaktangaben mit dem Eingang.
          </p>
          <label>
            Begründung der Zuordnung
            <textarea
              required
              maxLength={2000}
              rows={3}
              disabled={confirm.isPending}
              value={note}
              onChange={(event) => {
                setNote(event.target.value);
                operation.current = crypto.randomUUID();
                confirm.reset();
              }}
            />
          </label>
          <Button
            icon={
              <HugeiconsIcon
                icon={Tick02Icon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="primary"
            type="submit"
            disabled={confirm.isPending || !note.trim()}
          >
            {confirm.isPending
              ? "Wird zugeordnet …"
              : "Kontaktzuordnung bestätigen"}
          </Button>
        </form>
      )}
      {confirm.error && (
        <StatusMessage tone="error">
          <p>
            {confirm.error instanceof ApiError && confirm.error.status === 409
              ? "Der Kontakt, die Zuordnung oder der Auftrag wurde inzwischen geändert. Suche erneut und prüfe die aktuellen Daten. Deine Begründung bleibt erhalten."
              : "Die Zuordnung konnte nicht bestätigt werden. Prüfe deinen Zugriff oder versuche es später erneut. Deine Begründung bleibt erhalten."}
          </p>
        </StatusMessage>
      )}
    </div>
  );
}
