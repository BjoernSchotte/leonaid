import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  FloppyDiskIcon,
  RefreshIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  type Case,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export function CaseEditor({
  client,
  initialCase,
}: {
  client: LeonAidApiClient;
  initialCase: Case;
}) {
  const cache = useQueryClient();
  const [base, setBase] = useState(initialCase);
  const [status, setStatus] = useState(base.status);
  const [assignee, setAssignee] = useState(base.assigneeUserId ?? "");
  const [note, setNote] = useState(base.closureNote ?? "");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState("");
  const operation = useRef(crypto.randomUUID());
  const permissions = useQuery({
    queryKey: ["inbox-permissions", base.id],
    queryFn: () => client.getInboxCasePermissions(base.id),
    retry: false,
  });
  const manage = permissions.data?.canManage === true && !permissions.error;
  const candidates = useQuery({
    queryKey: ["inbox-assignees", base.id, search, offset],
    queryFn: () =>
      client.listInboxAssignees(base.id, { search, offset, limit: 25 }),
    enabled: manage,
    retry: false,
  });
  const dirty =
    status !== base.status ||
    assignee !== (base.assigneeUserId ?? "") ||
    (status === "closed" && note !== (base.closureNote ?? ""));
  const accept = (value: Case) => {
    setBase(value);
    setStatus(value.status);
    setAssignee(value.assigneeUserId ?? "");
    setNote(value.closureNote ?? "");
    operation.current = crypto.randomUUID();
    cache.setQueryData(["inbox-case", value.id], value);
    void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
    void cache.invalidateQueries({ queryKey: ["inbox-permissions", value.id] });
  };
  const save = useMutation({
    mutationFn: () =>
      client.updateInboxCase(base.id, {
        idempotencyKey: operation.current,
        expectedRevision: base.revision,
        status,
        assigneeUserId: manage ? assignee || null : base.assigneeUserId,
        closureNote: status === "closed" ? note.trim() : null,
      }),
    onSuccess: (value) => {
      accept(value);
      setNotice("Bearbeitung gespeichert.");
    },
  });
  const reload = useMutation({
    mutationFn: () => client.getInboxCase(base.id),
    onSuccess: (value) => {
      accept(value);
      save.reset();
      setNotice("Aktueller Stand geladen.");
    },
  });
  const changed = () => {
    operation.current = crypto.randomUUID();
    setNotice("");
    save.reset();
  };
  const busy = save.isPending || reload.isPending;
  useEffect(() => {
    if (dirty || busy || initialCase.revision === base.revision) return;
    setBase(initialCase);
    setStatus(initialCase.status);
    setAssignee(initialCase.assigneeUserId ?? "");
    setNote(initialCase.closureNote ?? "");
    operation.current = crypto.randomUUID();
  }, [initialCase, base.revision, dirty, busy]);
  return (
    <section aria-labelledby="inbox-edit-heading">
      <h2 id="inbox-edit-heading">Bearbeitung</h2>
      <form
        className="inbox-form"
        onSubmit={(event) => {
          event.preventDefault();
          setNotice("");
          save.mutate();
        }}
      >
        <label>
          Status
          <select
            value={status}
            disabled={busy}
            onChange={(event) => {
              setStatus(event.target.value as Case["status"]);
              changed();
            }}
          >
            <option value="new">Neu</option>
            <option value="in_progress">In Bearbeitung</option>
            <option value="closed">Abgeschlossen</option>
          </select>
        </label>
        {manage && (
          <fieldset disabled={busy}>
            <legend>Zuständigkeit</legend>
            <label>
              Person suchen
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
            <label>
              Zuständige Person
              <select
                value={assignee}
                onChange={(event) => {
                  setAssignee(event.target.value);
                  changed();
                }}
              >
                <option value="">Nicht zugewiesen</option>
                {assignee &&
                  !candidates.data?.items.some(
                    (person) => person.userId === assignee,
                  ) && (
                    <option value={assignee}>
                      Ausgewählte Person beibehalten
                    </option>
                  )}
                {!candidates.error &&
                  candidates.data?.items.map((person) => (
                    <option key={person.userId} value={person.userId}>
                      {person.displayName}
                    </option>
                  ))}
              </select>
            </label>
            {candidates.isPending && (
              <p role="status">Personen werden geladen …</p>
            )}
            {candidates.error && (
              <StatusMessage tone="error">
                <p>Personen konnten nicht geladen werden.</p>
                <Button
                  icon={
                    <HugeiconsIcon
                      icon={RefreshIcon}
                      size={16}
                      strokeWidth={1.7}
                      aria-hidden="true"
                    />
                  }
                  variant="secondary"
                  type="button"
                  onClick={() => void candidates.refetch()}
                >
                  Personen erneut laden
                </Button>
              </StatusMessage>
            )}
            <div className="inbox-paging">
              <Button
                icon={
                  <HugeiconsIcon
                    icon={ArrowLeft01Icon}
                    size={16}
                    strokeWidth={1.7}
                    aria-hidden="true"
                  />
                }
                variant="secondary"
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                Vorherige Personen
              </Button>
              <Button
                icon={
                  <HugeiconsIcon
                    icon={ArrowRight01Icon}
                    size={16}
                    strokeWidth={1.7}
                    aria-hidden="true"
                  />
                }
                variant="secondary"
                type="button"
                disabled={
                  candidates.data?.nextOffset == null || !!candidates.error
                }
                onClick={() => setOffset(candidates.data?.nextOffset ?? offset)}
              >
                Weitere Personen
              </Button>
            </div>
          </fieldset>
        )}
        {status === "closed" && (
          <label>
            Abschlussnotiz
            <textarea
              required
              maxLength={4000}
              rows={4}
              value={note}
              disabled={busy}
              onChange={(event) => {
                setNote(event.target.value);
                changed();
              }}
            />
          </label>
        )}
        {status === "closed" && (
          <p>
            Der Abschluss dokumentiert die Bearbeitung. Er ist keine
            Förderzusage oder Auszahlung.
          </p>
        )}
        {permissions.error && (
          <StatusMessage tone="error">
            <p>
              Die aktuellen Verwaltungsrechte konnten nicht geladen werden. Die
              Zuständigkeit bleibt unverändert.
            </p>
            <Button
              variant="secondary"
              type="button"
              onClick={() => void permissions.refetch()}
            >
              Rechte erneut prüfen
            </Button>
          </StatusMessage>
        )}
        <div className="inbox-paging">
          <Button
            icon={
              <HugeiconsIcon
                icon={FloppyDiskIcon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="primary"
            type="submit"
            disabled={busy || !dirty || (status === "closed" && !note.trim())}
          >
            {save.isPending ? "Wird gespeichert …" : "Bearbeitung speichern"}
          </Button>
          <Button
            icon={
              <HugeiconsIcon
                icon={RefreshIcon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="secondary"
            type="button"
            disabled={busy}
            onClick={() => {
              if (
                !dirty ||
                window.confirm(
                  "Deinen ungespeicherten Entwurf verwerfen und den aktuellen Fallstand laden?",
                )
              )
                reload.mutate();
            }}
          >
            Aktuellen Stand laden
          </Button>
        </div>
        {save.error && (
          <StatusMessage tone="error">
            <p>
              {save.error instanceof ApiError && save.error.status === 409
                ? "Der Fall wurde inzwischen geändert. Dein Entwurf bleibt erhalten. Lade den aktuellen Stand und übernimm deine Änderung erneut."
                : "Die Bearbeitung konnte nicht gespeichert werden. Dein Entwurf bleibt erhalten. Prüfe deinen Zugriff und versuche es erneut."}
            </p>
          </StatusMessage>
        )}
        {reload.error && (
          <StatusMessage tone="error">
            <p>
              Der aktuelle Fallstand konnte nicht geladen werden. Dein Entwurf
              bleibt erhalten.
            </p>
          </StatusMessage>
        )}
        {notice && <p role="status">{notice}</p>}
      </form>
    </section>
  );
}
