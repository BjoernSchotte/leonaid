import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import { says, type Address } from "../tasks/task-copy";
import "./access-members.css";

export type AccessChange =
  | { email: string; access: "viewer" | "editor" }
  | { userId: string; access: "viewer" | "editor" | null };

export interface AccessMember {
  readonly userId: string;
  readonly displayName: string;
  readonly access: "viewer" | "editor";
  readonly active: boolean;
}

export interface AccessMemberPage {
  readonly items: readonly AccessMember[];
  readonly nextOffset?: number | null;
  /** Revision of the access list; every change must name it. */
  readonly revision: number;
}

/**
 * One object kind whose explicit members the panel manages. Each module
 * supplies its own client calls, so this shared panel imports no module API.
 */
export interface AccessMemberSource {
  readonly queryKey: string;
  readonly label: string;
  readonly accessLabel: string;
  readonly subject: string;
  readonly list: (search: string, offset: number) => Promise<AccessMemberPage>;
  readonly change: (
    command: AccessChange,
    expectedRevision: number,
    idempotencyKey: string,
  ) => Promise<unknown>;
  /** Further query keys that depend on the member list. */
  readonly dependentQueryKeys: readonly (readonly unknown[])[];
}

export function AccessMembersPanel({
  objectId,
  source,
  actionScoped,
  address,
}: {
  objectId: string;
  source: AccessMemberSource;
  actionScoped: boolean;
  /** "Sie" in the back office, "du" in the app. */
  address: Address;
}) {
  const { label, accessLabel, subject } = source;
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [email, setEmail] = useState("");
  const [access, setAccess] = useState<"viewer" | "editor">("viewer");
  const cache = useQueryClient();
  const operation = useRef({ signature: "", key: crypto.randomUUID() });
  const members = useQuery({
    queryKey: [source.queryKey, objectId, search, offset],
    queryFn: () => source.list(search, offset),
    enabled: open,
    retry: false,
  });
  const change = useMutation({
    mutationFn: async (command: AccessChange) => {
      if (!members.data) throw new Error("Access revision unavailable");
      const expectedRevision = members.data.revision;
      const signature = JSON.stringify({ command, expectedRevision });
      if (signature !== operation.current.signature)
        operation.current = { signature, key: crypto.randomUUID() };
      return source.change(command, expectedRevision, operation.current.key);
    },
    onSuccess: async () => {
      setEmail("");
      await Promise.all([
        cache.invalidateQueries({ queryKey: [source.queryKey, objectId] }),
        ...source.dependentQueryKeys.map((queryKey) =>
          cache.invalidateQueries({ queryKey }),
        ),
      ]);
    },
  });
  return (
    <section className="access-members">
      <Button
        type="button"
        variant="secondary"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {label}
      </Button>
      {open && (
        <div>
          <h2>Zugriff auf {subject}</h2>
          <p>
            {actionScoped
              ? "Aktionsrollen gelten weiterhin. Das Entfernen eines zusätzlichen Zugriffs entzieht keine Aktionsmitgliedschaft."
              : "Der Eigentümer behält den Zugriff. Weitere Personen erhalten ausdrücklich Lese- oder Bearbeitungsrechte."}
          </p>
          {members.isPending && <p role="status">Zugriffe werden geladen …</p>}
          {members.error && (
            <StatusMessage tone="error">
              {members.error instanceof ApiError &&
              [403, 404].includes(members.error.status)
                ? "Nur Eigentümer oder Aktionsverwaltung können diese Zugriffe verwalten."
                : "Zugriffe konnten nicht geladen werden."}{" "}
              <Button
                variant="secondary"
                onClick={() => void members.refetch()}
              >
                Erneut laden
              </Button>
            </StatusMessage>
          )}
          {members.data && !members.error && (
            <fieldset disabled={change.isPending}>
              <label>
                {label} suchen
                <input
                  type="search"
                  maxLength={200}
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setOffset(0);
                  }}
                />
              </label>
              <ul className="access-results">
                {members.data.items.map((member) => (
                  <li key={member.userId}>
                    <h3>{member.displayName}</h3>
                    <p>
                      {member.access === "editor"
                        ? "Darf bearbeiten"
                        : "Darf lesen"}
                      {!member.active && " · Konto inaktiv"}
                    </p>
                    <div className="access-paging">
                      <Button
                        variant="secondary"
                        disabled={!member.active || members.isFetching}
                        onClick={() =>
                          change.mutate({
                            userId: member.userId,
                            access:
                              member.access === "editor" ? "viewer" : "editor",
                          })
                        }
                      >
                        {member.access === "editor"
                          ? "Nur Lesen erlauben"
                          : "Bearbeiten erlauben"}
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={members.isFetching}
                        onClick={() =>
                          change.mutate({ userId: member.userId, access: null })
                        }
                      >
                        {accessLabel} entfernen
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
              {members.data.items.length === 0 && (
                <p>Keine zusätzlichen Mitglieder für diese Suche.</p>
              )}
              <div className="access-paging">
                <Button
                  variant="secondary"
                  disabled={offset === 0 || members.isFetching}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Vorherige Mitglieder
                </Button>
                <Button
                  variant="secondary"
                  disabled={
                    members.data.nextOffset == null || members.isFetching
                  }
                  onClick={() => setOffset(members.data!.nextOffset!)}
                >
                  Weitere Mitglieder
                </Button>
              </div>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  change.mutate({ email: email.trim(), access });
                }}
              >
                <h3>Bestehendes Konto hinzufügen</h3>
                <label>
                  E-Mail-Adresse
                  <input
                    type="email"
                    required
                    maxLength={254}
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </label>
                <label>
                  {accessLabel}
                  <select
                    value={access}
                    onChange={(event) =>
                      setAccess(event.target.value as "viewer" | "editor")
                    }
                  >
                    <option value="viewer">Lesen</option>
                    <option value="editor">Bearbeiten</option>
                  </select>
                </label>
                <p>
                  Die Person benötigt bereits ein aktives LeonAid-Konto
                  {actionScoped ? " und Zugriff auf diese Aktion" : ""}.
                </p>
                <Button
                  type="submit"
                  disabled={!email.trim() || members.isFetching}
                >
                  Zugriff speichern
                </Button>
              </form>
            </fieldset>
          )}
          {change.error && (
            <StatusMessage tone="error">
              {change.error instanceof ApiError && change.error.status === 409
                ? says(
                    address,
                    "Die Zugriffsrechte wurden inzwischen geändert oder das Konto kann nicht hinzugefügt werden. Lade die Zugriffe neu und prüfe deine Eingabe.",
                    "Die Zugriffsrechte wurden inzwischen geändert oder das Konto kann nicht hinzugefügt werden. Laden Sie die Zugriffe neu und prüfen Sie Ihre Eingabe.",
                  )
                : says(
                    address,
                    "Die Änderung konnte nicht gespeichert werden. Prüfe deine Berechtigung und Verbindung.",
                    "Die Änderung konnte nicht gespeichert werden. Prüfen Sie Ihre Berechtigung und Verbindung.",
                  )}
              <Button
                variant="secondary"
                onClick={() => {
                  change.reset();
                  void members.refetch();
                }}
              >
                Zugriffe neu laden
              </Button>
            </StatusMessage>
          )}
          {change.isSuccess && <p role="status">Zugriff gespeichert.</p>}
        </div>
      )}
    </section>
  );
}
