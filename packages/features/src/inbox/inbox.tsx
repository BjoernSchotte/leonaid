import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  RefreshIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, type Case } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import "./inbox.css";
import {
  ActionContextSearch,
  useActionContexts,
} from "../shared/action-contexts";
import { CaseEditor } from "./case-editor";
import { InboxComments } from "./comments";
import { InboxContact } from "./contact";
import { InboxMaterials } from "./materials";
import { InboxTasks } from "./tasks";

export const caseStatus: Record<Case["status"], string> = {
  new: "Neu",
  in_progress: "In Bearbeitung",
  closed: "Abgeschlossen",
};
export const contactStatus: Record<Case["contactStatus"], string> = {
  pending: "Kontaktzuordnung ausstehend",
  linked: "Kontakt zugeordnet",
  needs_review: "Kontaktzuordnung benötigt Klärung",
  failed: "Kontaktzuordnung fehlgeschlagen",
};
const date = (value: string) => new Date(value).toLocaleString("de-DE");

function LoadError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <StatusMessage tone="error">
      <p>
        {error instanceof ApiError && error.status === 401
          ? "Bitte melde dich erneut an."
          : error instanceof ApiError && error.status === 404
            ? "Dieser Eingang ist nicht mehr verfügbar oder du hast keinen Zugriff."
            : "Die Eingänge konnten nicht geladen werden. Bitte versuche es erneut."}
      </p>
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
        onClick={retry}
      >
        Erneut laden
      </Button>
    </StatusMessage>
  );
}

export function InboxPage({
  client,
  basePath,
  caseId,
}: ModulePageContext & { basePath: string; caseId?: string }) {
  if (caseId)
    return <InboxCase client={client} basePath={basePath} caseId={caseId} />;
  return <InboxList client={client} basePath={basePath} />;
}

function InboxList({
  client,
  basePath,
}: Pick<ModulePageContext, "client"> & { basePath: string }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<Case["status"] | "">("");
  const [forMe, setForMe] = useState(false);
  const [actionFilter, setActionFilter] = useState("");
  const contexts = useActionContexts(client);
  const [offset, setOffset] = useState(0);
  const cases = useQuery({
    queryKey: ["inbox-cases", search, status, forMe, offset, actionFilter],
    queryFn: () =>
      client.listInboxCases({
        search,
        actionId: actionFilter || undefined,
        status: status || undefined,
        forMe,
        offset,
        limit: 25,
      }),
    retry: false,
  });
  return (
    <section className="inbox-workspace" aria-labelledby="inbox-heading">
      <header>
        <h1 id="inbox-heading">Eingänge</h1>
        <p>
          Kontakt- und Hilfsanfragen im Blick behalten und gemeinsam bearbeiten.
        </p>
      </header>
      <div className="inbox-form">
        <ActionContextSearch contexts={contexts} />
      </div>
      <div className="inbox-filters">
        <label>
          Betreff suchen
          <input
            type="search"
            maxLength={200}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Bearbeitungsstatus
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as Case["status"] | "");
              setOffset(0);
            }}
          >
            <option value="">Alle Status</option>
            {Object.entries(caseStatus).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Aktion
          <select
            value={actionFilter}
            onChange={(event) => {
              setActionFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Alle zugänglichen Eingänge</option>
            {actionFilter &&
              !contexts.knownActions.some(([id]) => id === actionFilter) && (
                <option value={actionFilter}>
                  Ausgewählte Aktion beibehalten
                </option>
              )}
            {contexts.knownActions.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="inbox-check">
          <input
            type="checkbox"
            checked={forMe}
            onChange={(e) => {
              setForMe(e.target.checked);
              setOffset(0);
            }}
          />
          Mir zugewiesen
        </label>
      </div>
      {cases.isPending && <p role="status">Eingänge werden geladen …</p>}
      {cases.error && (
        <LoadError error={cases.error} retry={() => void cases.refetch()} />
      )}
      {!cases.error && cases.data && (
        <>
          {cases.data.items.length === 0 ? (
            <p>
              Keine zugänglichen Eingänge für diese Auswahl. Ändere die Suche
              oder den Filter.
            </p>
          ) : (
            <ul className="inbox-results">
              {cases.data.items.map((item) => (
                <li key={item.id}>
                  <h2>
                    <a href={`${basePath}/${item.id}`}>{item.subject}</a>
                  </h2>
                  <p>
                    {caseStatus[item.status]} · {date(item.receivedAt)}
                  </p>
                  <p>
                    {item.givenName} {item.familyName} ·{" "}
                    {contactStatus[item.contactStatus]}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <nav className="inbox-paging" aria-label="Ergebnisseiten">
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
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              Zurück
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
              disabled={cases.data.nextOffset == null}
              onClick={() => setOffset(cases.data.nextOffset ?? offset)}
            >
              Weitere Eingänge
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}

function InboxCase({
  client,
  basePath,
  caseId,
}: Pick<ModulePageContext, "client"> & { basePath: string; caseId: string }) {
  const current = useQuery({
    queryKey: ["inbox-case", caseId],
    queryFn: () => client.getInboxCase(caseId),
    retry: false,
  });
  const item = current.data;
  return (
    <section className="inbox-workspace" aria-label="Eingang">
      <a href={basePath}>Alle Eingänge</a>
      {current.isPending && <p role="status">Eingang wird geladen …</p>}
      {current.error && (
        <LoadError error={current.error} retry={() => void current.refetch()} />
      )}
      {!current.error && item && (
        <>
          <header>
            <h1 id="inbox-case-heading">{item.subject}</h1>
            <p>
              {caseStatus[item.status]} · Eingegangen am {date(item.receivedAt)}
            </p>
          </header>
          <section aria-labelledby="inbox-message-heading">
            <h2 id="inbox-message-heading">Nachricht</h2>
            <p>
              {item.givenName} {item.familyName}
            </p>
            <p>{[item.email, item.phone].filter(Boolean).join(" · ")}</p>
            <p className="inbox-message">{item.message}</p>
            <p>Referenz: {item.publicReference}</p>
          </section>
          <section aria-labelledby="inbox-contact-heading">
            <h2 id="inbox-contact-heading">Kontaktzuordnung</h2>
            <p role="status">{contactStatus[item.contactStatus]}</p>
            {item.contactStatus !== "linked" && (
              <p>
                Der Eingang bleibt unabhängig von der Kontaktzuordnung
                bearbeitbar.
              </p>
            )}
            <InboxContact
              key={`contact-${item.id}`}
              client={client}
              item={item}
            />
          </section>
          <CaseEditor key={item.id} client={client} initialCase={item} />
          <InboxTasks
            key={`tasks-${item.id}`}
            client={client}
            item={item}
            taskBasePath={basePath.replace(/\/inbox$/, "/tasks")}
          />
          <InboxMaterials
            key={`materials-${item.id}`}
            client={client}
            item={item}
          />
          <InboxComments
            key={`comments-${item.id}`}
            client={client}
            caseId={item.id}
          />
          {item.closureNote && (
            <section>
              <h2>Abschlussnotiz</h2>
              <p className="inbox-message">{item.closureNote}</p>
            </section>
          )}
        </>
      )}
    </section>
  );
}
