import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
} from "@tanstack/react-query";
import { BookOpen, Plus, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@leonaid/api-client";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Modal,
  StatusMessage,
} from "@leonaid/ui";

import { consumeCreateRequest } from "../command-palette/create-request";
import { useContextCommands } from "../command-palette/store";
import type { ModulePageContext } from "../modules";
import {
  ActionContextSearch,
  useActionContexts,
} from "../shared/action-contexts";
import { useDebouncedValue } from "../shared/use-debounced-value";
import "./knowledge.css";

type Address = "Sie" | "du";
const says = (address: Address, du: string, sie: string) =>
  address === "du" ? du : sie;

export function knowledgeAddress(
  basePath: string,
  surface?: "web" | "pwa",
): Address {
  return (surface ?? (basePath.startsWith("/app") ? "pwa" : "web")) === "pwa"
    ? "du"
    : "Sie";
}

function CreatePageDialog({
  address,
  basePath,
  client,
  onClose,
  open,
}: {
  readonly address: Address;
  readonly basePath: string;
  readonly client: ModulePageContext["client"];
  readonly onClose: () => void;
  readonly open: boolean;
}) {
  const contexts = useActionContexts(client);
  const { managedActions } = contexts;
  const [title, setTitle] = useState("");
  const [actionId, setActionId] = useState("");
  const [touched, setTouched] = useState(false);
  const operation = useRef(crypto.randomUUID());
  const create = useMutation({
    mutationFn: () =>
      client.createKnowledgePage({
        title: title.trim(),
        actionId: actionId || null,
        idempotencyKey: operation.current,
      }),
    // A new page is empty: open it for writing.
    onSuccess: (page) => window.location.assign(`${basePath}/${page.id}?edit`),
  });
  const close = () => {
    setTitle("");
    setActionId("");
    setTouched(false);
    create.reset();
    onClose();
  };
  return (
    <Modal
      footer={
        <>
          <Button onClick={close} variant="ghost">
            Abbrechen
          </Button>
          <Button
            disabled={!title.trim()}
            form="knowledge-create-form"
            icon={Plus}
            loading={create.isPending}
            type="submit"
            variant="primary"
          >
            {create.isPending ? "Wird angelegt …" : "Seite anlegen"}
          </Button>
        </>
      }
      onClose={close}
      open={open}
      title="Neue Seite"
    >
      <form
        className="knowledge-create"
        id="knowledge-create-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setTouched(true);
          if (title.trim()) create.mutate();
        }}
      >
        {create.error ? (
          <StatusMessage tone="error">
            {create.error instanceof ApiError && create.error.status === 401
              ? says(
                  address,
                  "Bitte melde dich erneut an.",
                  "Bitte melden Sie sich erneut an.",
                )
              : says(
                  address,
                  "Die Seite konnte nicht angelegt werden. Dein Titel bleibt erhalten; versuche es erneut.",
                  "Die Seite konnte nicht angelegt werden. Ihr Titel bleibt erhalten; versuchen Sie es erneut.",
                )}
          </StatusMessage>
        ) : null}
        <Field
          error={
            touched && !title.trim() ? "Bitte einen Titel angeben." : undefined
          }
          label="Seitentitel"
          required
        >
          <input
            maxLength={240}
            onChange={(event) => {
              setTitle(event.target.value);
              operation.current = crypto.randomUUID();
              create.reset();
            }}
            value={title}
          />
        </Field>
        <Field
          hint={
            actionId
              ? "Aktuelle Mitglieder dieser Aktion können die Seite lesen. Die Aktionsverwaltung kann sie bearbeiten und zusätzliche Bearbeitungsrechte vergeben."
              : says(
                  address,
                  "Die neue Seite ist zunächst nur für dich sichtbar.",
                  "Die neue Seite ist zunächst nur für Sie sichtbar.",
                )
          }
          label="Kontext der neuen Seite"
        >
          <select
            onChange={(event) => {
              setActionId(event.target.value);
              operation.current = crypto.randomUUID();
              create.reset();
            }}
            value={actionId}
          >
            <option value="">Eigenständig</option>
            {actionId && !managedActions.some(([id]) => id === actionId) && (
              <option value={actionId}>Ausgewählte Aktion beibehalten</option>
            )}
            {managedActions.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <ActionContextSearch contexts={contexts} />
      </form>
    </Modal>
  );
}

/** "Wissen": the pages the person may read (prototype pages/Knowledge). */
export function KnowledgePage({
  basePath,
  client,
  surface,
}: ModulePageContext & { basePath: string; surface?: "web" | "pwa" }) {
  const address = knowledgeAddress(basePath, surface);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const contexts = useActionContexts(client);
  const { knownActions } = contexts;
  // "Wissensseite anlegen" from the palette, here or on another page.
  useEffect(() => {
    if (consumeCreateRequest("knowledge-page")) setCreating(true);
  }, []);
  useContextCommands([
    {
      id: "create:knowledge-page",
      label: "Wissensseite anlegen",
      group: "Wissen",
      icon: Plus,
      keywords: ["neu", "Seite"],
      run: () => setCreating(true),
    },
  ]);
  // Typing waits for a pause; the previous result stays while the next
  // loads, so the list does not flash "loading" on every keystroke.
  const query = useDebouncedValue(search);
  const pages = useInfiniteQuery({
    queryKey: ["knowledge-pages", query, actionFilter],
    queryFn: ({ pageParam }) =>
      client.listKnowledgePages({
        search: query,
        offset: pageParam,
        actionId: actionFilter || undefined,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.nextOffset ?? undefined,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const items = pages.data?.pages.flatMap((page) => page.items) ?? [];
  const actionName = (id: string | null) =>
    id
      ? (knownActions.find(([known]) => known === id)?.[1] ?? "Charity-Aktion")
      : null;
  const filtered = !!search || !!actionFilter;
  return (
    <div className="knowledge-list-page" data-zone="knowledge">
      <header className="page-header">
        <div className="page-heading">
          <h1>Wissen</h1>
          {pages.data ? (
            <span className="page-count num">
              {items.length}
              {pages.hasNextPage ? "+" : ""}{" "}
              {items.length === 1 ? "Seite" : "Seiten"}
            </span>
          ) : null}
        </div>
        <div className="page-actions">
          <Button
            icon={Plus}
            onClick={() => setCreating(true)}
            variant="primary"
          >
            Seite anlegen
          </Button>
        </div>
      </header>
      <div className="knowledge-tools">
        <label className="search">
          <Search aria-hidden="true" size={15} />
          <span className="sr-only">Seiten suchen</span>
          <input
            maxLength={200}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Wissen durchsuchen"
            type="search"
            value={search}
          />
        </label>
        {knownActions.length > 0 || actionFilter ? (
          <label className="select-inline">
            <span className="sr-only">Seiten nach Aktion filtern</span>
            <select
              onChange={(event) => setActionFilter(event.target.value)}
              value={actionFilter}
            >
              <option value="">Alle zugänglichen Seiten</option>
              {actionFilter &&
                !knownActions.some(([id]) => id === actionFilter) && (
                  <option value={actionFilter}>
                    Ausgewählte Aktion beibehalten
                  </option>
                )}
              {knownActions.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      {pages.isError ? (
        <StatusMessage tone="error">
          <p>Die Seiten konnten nicht geladen werden.</p>
          <Button
            onClick={() => void pages.refetch()}
            size="sm"
            variant="secondary"
          >
            Erneut laden
          </Button>
        </StatusMessage>
      ) : pages.isPending ? (
        <p className="small subtle" role="status">
          Seiten werden geladen …
        </p>
      ) : items.length === 0 ? (
        <EmptyState
          action={
            filtered ? undefined : (
              <Button
                icon={Plus}
                onClick={() => setCreating(true)}
                variant="primary"
              >
                Seite anlegen
              </Button>
            )
          }
          description={
            filtered
              ? says(
                  address,
                  "Ändere die Suche oder den Aktionsfilter.",
                  "Ändern Sie die Suche oder den Aktionsfilter.",
                )
              : says(
                  address,
                  "Hier erscheinen die Seiten, auf die du Zugriff hast: Abläufe, Notizen und Vorbereitung.",
                  "Hier erscheinen die Seiten, auf die Sie Zugriff haben: Abläufe, Notizen und Vorbereitung.",
                )
          }
          headingLevel={2}
          icon={BookOpen}
          title={filtered ? "Keine passenden Seiten" : "Noch keine Seiten"}
        />
      ) : (
        <ul className="kb-list">
          {items.map((page) => {
            const action = actionName(page.actionId);
            return (
              <li key={page.id}>
                <a className="kb-row" href={`${basePath}/${page.id}`}>
                  <span className="kb-title">{page.title}</span>
                  <span className="kb-meta small subtle">
                    <Badge tone={action ? "zone" : "neutral"}>
                      {action ?? "Eigenständig"}
                    </Badge>
                    Fassung {page.revision}
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      )}
      {pages.hasNextPage ? (
        <Button
          className="knowledge-more"
          loading={pages.isFetchingNextPage}
          onClick={() => void pages.fetchNextPage()}
          variant="secondary"
        >
          Weitere Seiten
        </Button>
      ) : null}
      <CreatePageDialog
        address={address}
        basePath={basePath}
        client={client}
        onClose={() => setCreating(false)}
        open={creating}
      />
    </div>
  );
}
