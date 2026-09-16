import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Button } from "@leonaid/ui";
import type { ModulePageContext, UiModule } from "../modules";
import "./module-search.css";

function SearchSection({
  module,
  query,
  surface,
  ...context
}: ModulePageContext & {
  module: UiModule;
  query: string;
  surface: "web" | "pwa";
}) {
  const result = useQuery({
    queryKey: [
      "module-search",
      context.identity.userId,
      surface,
      module.id,
      query,
    ],
    queryFn: ({ signal }) =>
      module.search!.find(context, query, surface, signal),
    retry: false,
    gcTime: 0,
  });
  return (
    <section aria-label={module.search!.label}>
      <h2>{module.search!.label}</h2>
      {result.isFetching ? (
        <p role="status">Wird gesucht …</p>
      ) : result.isError ? (
        <p role="status">Suche derzeit nicht möglich. Bitte erneut suchen.</p>
      ) : result.data?.length ? (
        <ul>
          {result.data.map((item) => (
            <li key={`${item.type}:${item.id}`}>
              <a href={item.href}>{item.title}</a>
              <small>{item.context}</small>
            </li>
          ))}
        </ul>
      ) : (
        <p>Keine zugänglichen Treffer.</p>
      )}
    </section>
  );
}

export function ModuleSearch({
  modules,
  surface,
  ...context
}: ModulePageContext & {
  modules: readonly UiModule[];
  surface: "web" | "pwa";
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [open, setOpen] = useState(false);
  const searchable = modules.filter(
    (module) =>
      module.search &&
      module.surfaces.includes(surface) &&
      context.identity.navigation.some(
        (item) => item.key === module.id && item.surface === surface,
      ),
  );
  if (!searchable.length) return null;
  return (
    <details
      className="module-search"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <HugeiconsIcon icon={Search01Icon} size={18} aria-hidden="true" />{" "}
        Aufgaben, Wissen und Materialien suchen
      </summary>
      {open && (
        <div>
          <form
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              setQuery(text.trim());
              setAttempt((value) => value + 1);
            }}
          >
            <label htmlFor={id}>Titel suchen</label>
            <div className="module-search__input">
              <input
                id={id}
                type="search"
                maxLength={200}
                required
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
              <Button
                type="submit"
                disabled={!text.trim()}
                icon={
                  <HugeiconsIcon
                    icon={Search01Icon}
                    size={18}
                    aria-hidden="true"
                  />
                }
              >
                Suchen
              </Button>
            </div>
          </form>
          <p>
            Bis zu zehn Treffer je Bereich. Es werden nur Inhalte angezeigt, auf
            die du Zugriff hast.
          </p>
          {query && (
            <div className="module-search__results" key={attempt}>
              {searchable.map((module) => (
                <SearchSection
                  key={module.id}
                  module={module}
                  query={query}
                  surface={surface}
                  {...context}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </details>
  );
}
