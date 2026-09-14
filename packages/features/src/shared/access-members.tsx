import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import "./access-members.css";

type Change =
  | { email: string; access: "viewer" | "editor" }
  | { userId: string; access: "viewer" | "editor" | null };

export function AccessMembersPanel({
  client,
  objectId,
  kind,
  actionScoped,
}: {
  client: LeonAidApiClient;
  objectId: string;
  kind: "task-list" | "knowledge-page" | "material";
  actionScoped: boolean;
}) {
  const page = kind === "knowledge-page";
  const material = kind === "material";
  const label = material
    ? "Materialfreigaben"
    : page
      ? "Seitenfreigaben"
      : "Listenmitglieder";
  const accessLabel = material
    ? "Materialzugriff"
    : page
      ? "Seitenzugriff"
      : "Listenzugriff";
  const subject = material
    ? "dieses Material"
    : page
      ? "diese Seite"
      : "diese Liste";
  const membersKey = material
    ? "material-members"
    : page
      ? "knowledge-members"
      : "task-members";
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [email, setEmail] = useState("");
  const [access, setAccess] = useState<"viewer" | "editor">("viewer");
  const cache = useQueryClient();
  const operation = useRef({ signature: "", key: crypto.randomUUID() });
  const members = useQuery({
    queryKey: [membersKey, objectId, search, offset],
    queryFn: async () => {
      if (material) {
        const result = await client.listMaterialMembers(objectId, {
          search,
          offset,
        });
        return { ...result, revision: result.accessRevision };
      }
      if (!page)
        return client.listTaskListMembers(objectId, { search, offset });
      const result = await client.listKnowledgePageMembers(objectId, {
        search,
        offset,
      });
      return { ...result, revision: result.accessRevision };
    },
    enabled: open,
    retry: false,
  });
  const change = useMutation({
    mutationFn: async (command: Change) => {
      if (!members.data) throw new Error("List revision unavailable");
      const expectedRevision = members.data.revision;
      const signature = JSON.stringify({ command, expectedRevision });
      if (signature !== operation.current.signature)
        operation.current = { signature, key: crypto.randomUUID() };
      const common = {
        expectedRevision,
        idempotencyKey: operation.current.key,
      };
      if (material) {
        const materialCommand = {
          expectedAccessRevision: expectedRevision,
          idempotencyKey: operation.current.key,
          ...command,
        };
        return "email" in materialCommand
          ? client.setMaterialMemberByEmail(objectId, materialCommand)
          : client.setMaterialMember(objectId, materialCommand);
      }
      if (page) {
        const pageCommand = {
          expectedAccessRevision: expectedRevision,
          idempotencyKey: operation.current.key,
        };
        return "email" in command
          ? client.setKnowledgePageMemberByEmail(objectId, {
              ...pageCommand,
              ...command,
            })
          : client.setKnowledgePageMember(objectId, {
              ...pageCommand,
              ...command,
            });
      }
      return "email" in command
        ? client.setTaskListMemberByEmail(objectId, { ...common, ...command })
        : client.setTaskListMember(objectId, { ...common, ...command });
    },
    onSuccess: async () => {
      setEmail("");
      await Promise.all([
        cache.invalidateQueries({ queryKey: [membersKey, objectId] }),
        cache.invalidateQueries({
          queryKey: [
            material
              ? "material-permissions"
              : page
                ? "knowledge-permissions"
                : "task-assignees",
            objectId,
          ],
        }),
        cache.invalidateQueries({
          queryKey: [
            material ? "material" : page ? "knowledge-page" : "task-list",
            objectId,
          ],
        }),
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
                ? "Die Zugriffsrechte wurden inzwischen geändert oder das Konto kann nicht hinzugefügt werden. Lade die Zugriffe neu und prüfe deine Eingabe."
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
          {change.isSuccess && <p role="status">Zugriff gespeichert.</p>}
        </div>
      )}
    </section>
  );
}
