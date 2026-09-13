import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

type Change =
  | { email: string; access: "viewer" | "editor" }
  | { userId: string; access: "viewer" | "editor" | null };

export function ListMembersPanel({
  client,
  listId,
  actionScoped,
}: {
  client: LeonAidApiClient;
  listId: string;
  actionScoped: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [email, setEmail] = useState("");
  const [access, setAccess] = useState<"viewer" | "editor">("viewer");
  const cache = useQueryClient();
  const operation = useRef({ signature: "", key: crypto.randomUUID() });
  const members = useQuery({
    queryKey: ["task-members", listId, search, offset],
    queryFn: () => client.listTaskListMembers(listId, { search, offset }),
    enabled: open,
    retry: false,
  });
  const change = useMutation({
    mutationFn: (command: Change) => {
      if (!members.data) throw new Error("List revision unavailable");
      const expectedRevision = members.data.revision;
      const signature = JSON.stringify({ command, expectedRevision });
      if (signature !== operation.current.signature)
        operation.current = { signature, key: crypto.randomUUID() };
      const common = {
        expectedRevision,
        idempotencyKey: operation.current.key,
      };
      return "email" in command
        ? client.setTaskListMemberByEmail(listId, { ...common, ...command })
        : client.setTaskListMember(listId, { ...common, ...command });
    },
    onSuccess: async () => {
      setEmail("");
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["task-members", listId] }),
        cache.invalidateQueries({ queryKey: ["task-assignees", listId] }),
        cache.invalidateQueries({ queryKey: ["task-list", listId] }),
      ]);
    },
  });
  return (
    <section className="task-members">
      <Button
        type="button"
        variant="secondary"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Listenmitglieder
      </Button>
      {open && (
        <div>
          <h2>Zugriff auf diese Liste</h2>
          <p>
            {actionScoped
              ? "Aktionsrollen gelten weiterhin. Das Entfernen eines zusätzlichen Listenzugriffs entzieht keine Aktionsmitgliedschaft."
              : "Der Eigentümer behält den Zugriff. Weitere Personen erhalten ausdrücklich Lese- oder Bearbeitungsrechte."}
          </p>
          {members.isPending && <p role="status">Zugriffe werden geladen …</p>}
          {members.error && (
            <StatusMessage tone="error">
              {members.error instanceof ApiError &&
              [403, 404].includes(members.error.status)
                ? "Nur die Listen- oder Aktionsverwaltung kann diese Zugriffe verwalten."
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
                Listenmitglieder suchen
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
              <ul className="tasks-results">
                {members.data.items.map((member) => (
                  <li key={member.userId}>
                    <h3>{member.displayName}</h3>
                    <p>
                      {member.access === "editor"
                        ? "Darf bearbeiten"
                        : "Darf lesen"}
                      {!member.active && " · Konto inaktiv"}
                    </p>
                    <div className="tasks-paging">
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
                        Listenzugriff entfernen
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
              {members.data.items.length === 0 && (
                <p>Keine zusätzlichen Listenmitglieder für diese Suche.</p>
              )}
              <div className="tasks-paging">
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
                  Listenzugriff
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
                ? "Die Listenrechte wurden inzwischen geändert oder das Konto kann nicht hinzugefügt werden. Lade die Zugriffe neu und prüfe deine Eingabe."
                : "Die Änderung konnte nicht gespeichert werden. Prüfe deine Berechtigung und Verbindung."}
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
          {change.isSuccess && <p role="status">Listenzugriff gespeichert.</p>}
        </div>
      )}
    </section>
  );
}
