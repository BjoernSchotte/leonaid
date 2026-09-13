import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import "./knowledge.css";

export function KnowledgePage({ client }: ModulePageContext) {
  const cache = useQueryClient();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [title, setTitle] = useState("");
  const [notice, setNotice] = useState("");
  const operation = useRef(crypto.randomUUID());
  const pages = useQuery({
    queryKey: ["knowledge-pages", search, offset],
    queryFn: () => client.listKnowledgePages({ search, offset }),
    retry: false,
  });
  const create = useMutation({
    mutationFn: () =>
      client.createKnowledgePage({
        title: title.trim(),
        idempotencyKey: operation.current,
      }),
    onSuccess: (page) => {
      setNotice(`„${page.title}“ wurde angelegt.`);
      setTitle("");
      setSearch("");
      setOffset(0);
      operation.current = crypto.randomUUID();
      void cache.invalidateQueries({ queryKey: ["knowledge-pages"] });
    },
  });
  return (
    <section
      className="knowledge-workspace"
      aria-labelledby="knowledge-heading"
    >
      <header>
        <h1 id="knowledge-heading">Wissen</h1>
        <p>Seiten für gemeinsame Abläufe, Notizen und Vorbereitung.</p>
      </header>
      <details className="knowledge-create">
        <summary>Neue Seite</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setNotice("");
            create.mutate();
          }}
        >
          <label>
            Seitentitel
            <input
              required
              maxLength={240}
              value={title}
              disabled={create.isPending}
              onChange={(event) => {
                setTitle(event.target.value);
                operation.current = crypto.randomUUID();
                create.reset();
              }}
            />
          </label>
          <p>Die neue Seite ist zunächst nur für dich sichtbar.</p>
          <Button type="submit" disabled={create.isPending || !title.trim()}>
            {create.isPending ? "Wird angelegt …" : "Seite anlegen"}
          </Button>
        </form>
      </details>
      {notice && <p role="status">{notice}</p>}
      {create.error && (
        <StatusMessage tone="error">
          <p>
            {create.error instanceof ApiError && create.error.status === 401
              ? "Bitte melde dich erneut an."
              : "Die Seite konnte nicht angelegt werden. Dein Titel bleibt erhalten; versuche es erneut."}
          </p>
        </StatusMessage>
      )}
      <label className="knowledge-search">
        Seiten suchen
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
      {pages.isPending && <p role="status">Seiten werden geladen …</p>}
      {pages.error && (
        <StatusMessage tone="error">
          <p>Die Seiten konnten nicht geladen werden.</p>
          <Button variant="secondary" onClick={() => void pages.refetch()}>
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      {!pages.error && pages.data && (
        <>
          {pages.data.items.length === 0 ? (
            <p>
              {search
                ? "Keine Seiten zu dieser Suche gefunden."
                : "Hier erscheinen die Seiten, auf die du Zugriff hast. Lege deine erste Seite an."}
            </p>
          ) : (
            <ul className="knowledge-results">
              {pages.data.items.map((page) => (
                <li key={page.id}>
                  <h2>{page.title}</h2>
                  <p>
                    {page.actionId ? "Aktionsseite" : "Eigenständige Seite"} ·
                    Version {page.revision}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {(offset > 0 || pages.data.nextOffset !== null) && (
            <nav className="knowledge-paging" aria-label="Ergebnisseiten">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Zurück
              </Button>
              <Button
                variant="secondary"
                disabled={pages.data.nextOffset === null}
                onClick={() => setOffset(pages.data!.nextOffset!)}
              >
                Weitere Seiten
              </Button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
