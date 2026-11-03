import type { NavigationItemResponse } from "@leonaid/api-client";
import {
  HOTKEY_PASSTHROUGH_ATTRIBUTE,
  Kbd,
  useHotkeys,
  useShortcutHelp,
} from "@leonaid/ui";
import { Command, defaultFilter } from "cmdk";
import {
  ArrowRight,
  BookOpen,
  CornerDownLeft,
  Flag,
  Inbox,
  Keyboard,
  ListChecks,
  Package,
  ReceiptEuro,
  Search,
  ShoppingBasket,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { ModulePageContext, ModuleSurface, UiModule } from "../modules";
import { navigationZones, zoneForNavKey } from "../navigation/zones";
import {
  createEntries,
  enabledSearchModules,
  isSearchQuery,
  normaliseQuery,
  surfaceNavigation,
  type PaletteHitType,
  type PaletteSearchHit,
} from "./sources";
import {
  useCommandPalette,
  useRegisteredContextCommands,
  type PaletteCommand,
} from "./store";
import {
  usePaletteSearch,
  type PaletteSearchState,
} from "./use-palette-search";
import "./command-palette.css";

export interface CommandPaletteProps {
  readonly context: ModulePageContext;
  /** Every module the shell registers; the palette keeps the enabled ones. */
  readonly modules: readonly UiModule[];
  readonly surface: ModuleSurface;
  /**
   * The navigation the shell shows, when it rewrites hrefs (for example the
   * campaign editor link). Defaults to `context.identity.navigation`.
   */
  readonly navigation?: readonly NavigationItemResponse[];
  /** Shell commands (for example the theme toggle), shown under their group. */
  readonly commands?: readonly PaletteCommand[];
}

const HIT_ICONS: Readonly<Record<PaletteHitType, LucideIcon>> = {
  action: Flag,
  order: ShoppingBasket,
  invoice: ReceiptEuro,
  sponsor: User,
  member: Users,
  task: ListChecks,
  "knowledge-page": BookOpen,
  material: Package,
  "inbox-case": Inbox,
};

const COPY = {
  web: {
    empty: (query: string) =>
      `Keine Treffer für „${query}“. Versuchen Sie eine Rechnungsnummer, einen Namen oder einen Bereich.`,
    error: "Die Suche ist gerade nicht erreichbar. Versuchen Sie es erneut.",
  },
  pwa: {
    empty: (query: string) =>
      `Keine Treffer für „${query}“. Versuche eine Rechnungsnummer, einen Namen oder einen Bereich.`,
    error: "Die Suche ist gerade nicht erreichbar. Versuche es erneut.",
  },
} as const;

const SETTINGS_GROUP = "Einstellungen";

/**
 * Local sources (commands, navigation) filtered with cmdk's own scoring and
 * sorted best match first; the empty query keeps the given order. Search
 * hits are never passed through here: the server already matched them.
 */
function rank<T>(
  items: readonly T[],
  query: string,
  value: (item: T) => string,
  keywords?: (item: T) => readonly string[] | undefined,
): T[] {
  if (!query) return [...items];
  return items
    .map((item, index) => ({
      item,
      index,
      score: defaultFilter(value(item), query, [...(keywords?.(item) ?? [])]),
    }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.item);
}

const zoneOrder = new Map(
  navigationZones.map((zone, index) => [zone.navKey, index]),
);

/** The approved zone order (prototype "g" map); unknown keys keep server order at the end. */
function byZoneOrder(
  items: readonly NavigationItemResponse[],
): NavigationItemResponse[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        (zoneOrder.get(a.item.key) ?? Infinity) -
          (zoneOrder.get(b.item.key) ?? Infinity) || a.index - b.index,
    )
    .map((entry) => entry.item);
}

const commandText = (command: PaletteCommand) =>
  `${command.label} ${command.group}`;
const commandKeywords = (command: PaletteCommand) => command.keywords;

function groupCommands(commands: readonly PaletteCommand[]) {
  const groups = new Map<string, PaletteCommand[]>();
  for (const command of commands) {
    const items = groups.get(command.group);
    if (items) items.push(command);
    else groups.set(command.group, [command]);
  }
  return [...groups.entries()];
}

function CommandItem({
  command,
  onRun,
}: {
  command: PaletteCommand;
  onRun: (action: () => void) => void;
}) {
  const Icon = command.icon ?? ArrowRight;
  return (
    <Command.Item
      className="palette-item"
      onSelect={() => onRun(command.run)}
      value={`command:${command.id}`}
    >
      <Icon aria-hidden="true" size={16} />
      <span className="palette-label">{command.label}</span>
      {command.keys ? <Kbd keys={command.keys} subtle /> : null}
    </Command.Item>
  );
}

function SearchStatus({
  state,
  surface,
  onRetry,
}: {
  state: PaletteSearchState;
  surface: ModuleSurface;
  onRetry: () => void;
}) {
  let content: ReactNode = null;
  if (state.status === "loading") {
    content = <span className="palette-status-text">Wird gesucht …</span>;
  } else if (state.status === "error") {
    content = (
      <>
        <span className="palette-status-text is-danger">
          {COPY[surface].error}
        </span>
        <button className="palette-retry" onClick={onRetry} type="button">
          Erneut versuchen
        </button>
      </>
    );
  } else if (state.status === "done" && state.outcome.failed.length) {
    content = (
      <span className="palette-status-text">
        Nicht durchsucht: {state.outcome.failed.join(", ")}.
      </span>
    );
  }
  return (
    <div
      aria-live="polite"
      className="palette-status"
      data-state={state.status}
      hidden={content === null}
      role="status"
    >
      {content}
    </div>
  );
}

/**
 * ⌘K / Strg+K palette (and "/" outside lists). A native <dialog> (focus
 * trap, Esc, inert background) wraps cmdk's inline Command: Command.Dialog
 * would inject a scroll-lock <style> that the strict CSP blocks.
 *
 * Sources: page commands, navigation ("Gehe zu", only what the server lists
 * for this account), search results (core endpoint plus enabled module
 * providers) and shell commands. Search results are never filtered or
 * extended client-side: they are exactly what the server returned.
 */
export function CommandPalette({
  context,
  modules,
  surface,
  navigation,
  commands = [],
}: CommandPaletteProps) {
  const { open, setOpen, toggle } = useCommandPalette();
  const help = useShortcutHelp();
  const pageCommands = useRegisteredContextCommands();
  const ref = useRef<HTMLDialogElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const { state, retry } = usePaletteSearch(
    context,
    modules,
    surface,
    query,
    open,
  );

  useHotkeys([
    {
      keys: "mod+k",
      label: "Befehlspalette öffnen",
      group: "Allgemein",
      inDialog: true,
      allowInInput: true,
      run: toggle,
    },
    {
      keys: "/",
      label: "Suchen",
      group: "Allgemein",
      run: () => setOpen(true),
    },
  ]);

  // Layout effect: the dialog opens before paint. The input has no
  // autoFocus, so the element captured here is still the opener.
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      returnFocus.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setQuery("");
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      dialog.querySelector<HTMLInputElement>(".palette-input")?.focus();
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      const target = returnFocus.current;
      returnFocus.current = null;
      if (target?.isConnected) target.focus();
    }
  }, [open]);

  // Closing from an unmount (route change) must not leave the store open.
  useEffect(() => () => setOpen(false), [setOpen]);

  const text = normaliseQuery(query);
  const items = surfaceNavigation(
    navigation ?? context.identity.navigation,
    surface,
  );
  const searchModules = enabledSearchModules(
    modules,
    context.identity.navigation,
    surface,
  );

  const visiblePageGroups = useMemo(
    () => groupCommands(rank(pageCommands, text, commandText, commandKeywords)),
    [pageCommands, text],
  );
  // The server decides which areas exist; names, icons, hints and keys come
  // from the approved zone map, as in the rail.
  const visibleNavigation = rank(
    byZoneOrder(items).map((item) => {
      const zone = zoneForNavKey(item.key);
      return { item, zone, label: zone?.label ?? item.label };
    }),
    text,
    ({ label }) => `Gehe zu ${label}`,
    ({ item, zone }) => (zone ? [item.label, zone.hint] : undefined),
  );
  const pageCommandIds = new Set(pageCommands.map((command) => command.id));
  // A page that offers the same create in place wins over the link.
  const visibleCreates = rank(
    createEntries(modules, context.identity.navigation, surface).filter(
      (entry) => !pageCommandIds.has(entry.id),
    ),
    text,
    (entry) => `${entry.label} Anlegen`,
    () => ["neu", "erstellen"],
  );
  const settingsCommands: PaletteCommand[] = [
    ...commands,
    {
      id: "shortcut-help",
      label: "Alle Tastenkürzel",
      group: SETTINGS_GROUP,
      icon: Keyboard,
      keys: "?",
      keywords: ["Tastenkürzel", "Hilfe", "anzeigen"],
      run: () => help.setOpen(true),
    },
  ];
  const visibleShellGroups = groupCommands(
    rank(settingsCommands, text, commandText, commandKeywords),
  );
  const searching = isSearchQuery(text);
  // While the next request runs, the previous query's hits stay visible but
  // dimmed and disabled; the new response replaces them entirely.
  const current = searching && state.status === "done" && state.query === text;
  const stale = searching && state.status === "loading" && state.stale;
  const hitGroups = current
    ? state.outcome.groups
    : stale
      ? state.stale!.groups
      : [];
  const localCount =
    visiblePageGroups.length +
    visibleCreates.length +
    visibleNavigation.length +
    visibleShellGroups.length;
  const showEmpty =
    localCount === 0 &&
    hitGroups.length === 0 &&
    (!searching || state.status === "done");

  // A new query selects its first item. Arriving hits never move the
  // selection; only when the selected item disappears does it fall back to
  // the first one, so Enter never runs a hidden item.
  const listSignature = [
    visiblePageGroups.map(([group, list]) => `${group}:${list.length}`).join(),
    visibleCreates.length,
    visibleNavigation.length,
    hitGroups.map((group) => `${group.id}:${group.hits.length}`).join(),
    stale ? "stale" : "",
    visibleShellGroups.length,
  ].join("|");
  const firstItem = () =>
    listRef.current
      ?.querySelector<HTMLElement>("[cmdk-item]:not([aria-disabled='true'])")
      ?.getAttribute("data-value") ?? "";
  useLayoutEffect(() => {
    if (open) setSelected(firstItem());
  }, [open, text]);
  useLayoutEffect(() => {
    if (!open) return;
    const present = [
      ...(listRef.current?.querySelectorAll<HTMLElement>(
        "[cmdk-item]:not([aria-disabled='true'])",
      ) ?? []),
    ].some((item) => item.getAttribute("data-value") === selected);
    if (!present) setSelected(firstItem());
    // `selected` is read, not tracked: user moves must not re-run this.
  }, [open, listSignature]);

  const run = (action: () => void) => {
    setOpen(false);
    window.setTimeout(action, 0);
  };
  const go = (href: string) => run(() => window.location.assign(href));

  const coverage = [
    "Aktionen, Bestellungen, Rechnungen, Mitglieder",
    ...searchModules.map(
      (module) => zoneForNavKey(module.id)?.label ?? module.search!.label,
    ),
  ].join(", ");

  return (
    <dialog
      aria-label="Befehlspalette"
      className="palette"
      ref={ref}
      {...{ [HOTKEY_PASSTHROUGH_ATTRIBUTE]: "" }}
      onCancel={(event) => {
        event.preventDefault();
        setOpen(false);
      }}
      onClick={(event) => {
        if (event.target === ref.current) setOpen(false);
      }}
      onKeyDown={(event) => {
        // Page bindings (Esc closes a pane, …) must not run behind the
        // palette; only the palette toggle passes through.
        const mod = event.metaKey || event.ctrlKey;
        if (!(mod && event.key.toLowerCase() === "k")) event.stopPropagation();
      }}
    >
      {open ? (
        <Command
          className="palette-command"
          label="Befehlspalette"
          loop
          onValueChange={setSelected}
          shouldFilter={false}
          // Ctrl+K is cmdk's "previous item"; it must toggle the palette.
          vimBindings={false}
          value={selected}
        >
          <div className="palette-search">
            <Search aria-hidden="true" size={18} />
            <Command.Input
              className="palette-input"
              onValueChange={setQuery}
              placeholder="Suchen oder Befehl eingeben …"
              value={query}
            />
            <Kbd keys="escape" subtle />
          </div>
          <Command.List className="palette-list" ref={listRef}>
            {showEmpty ? (
              <Command.Empty className="palette-empty">
                {COPY[surface].empty(text)}
              </Command.Empty>
            ) : null}

            {visiblePageGroups.map(([group, list]) => (
              <Command.Group
                className="palette-group"
                heading={`Auf dieser Seite · ${group}`}
                key={`page:${group}`}
              >
                {list.map((command) => (
                  <CommandItem command={command} key={command.id} onRun={run} />
                ))}
              </Command.Group>
            ))}

            {visibleCreates.length ? (
              <Command.Group className="palette-group" heading="Anlegen">
                {visibleCreates.map((entry) => (
                  <Command.Item
                    className="palette-item"
                    key={entry.id}
                    onSelect={() => go(entry.href)}
                    value={entry.id}
                  >
                    <entry.icon aria-hidden="true" size={16} />
                    <span className="palette-label">{entry.label}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {visibleNavigation.length ? (
              <Command.Group className="palette-group" heading="Gehe zu">
                {visibleNavigation.map(({ item, zone, label }) => {
                  const Icon = zone?.icon ?? ArrowRight;
                  return (
                    <Command.Item
                      className="palette-item"
                      data-zone={item.key}
                      key={item.key}
                      onSelect={() => go(item.href)}
                      value={`nav:${item.key}`}
                    >
                      <span aria-hidden="true" className="palette-zone">
                        <Icon size={14} />
                      </span>
                      <span className="palette-label">{label}</span>
                      {zone?.hint ? (
                        <span className="palette-hint">{zone.hint}</span>
                      ) : null}
                      {zone?.key ? <Kbd keys={`g ${zone.key}`} subtle /> : null}
                    </Command.Item>
                  );
                })}
              </Command.Group>
            ) : null}

            {hitGroups.map((group) => (
              <Command.Group
                className="palette-group"
                data-stale={stale ? "true" : undefined}
                heading={group.label}
                key={group.id}
              >
                {group.hits.map((hit: PaletteSearchHit) => {
                  const Icon = HIT_ICONS[hit.type];
                  return (
                    <Command.Item
                      className="palette-item"
                      data-hit-type={hit.type}
                      disabled={Boolean(stale)}
                      key={`${hit.type}:${hit.id}`}
                      onSelect={() => go(hit.href)}
                      value={`hit:${group.id}:${hit.id}`}
                    >
                      <span aria-hidden="true" className="palette-entity-icon">
                        <Icon size={14} />
                      </span>
                      <span className="palette-label">{hit.title}</span>
                      <span className="palette-hint">{hit.context}</span>
                    </Command.Item>
                  );
                })}
              </Command.Group>
            ))}

            {visibleShellGroups.map(([group, list]) => (
              <Command.Group
                className="palette-group"
                heading={group}
                key={`shell:${group}`}
              >
                {list.map((command) => (
                  <CommandItem command={command} key={command.id} onRun={run} />
                ))}
              </Command.Group>
            ))}
          </Command.List>
          <SearchStatus onRetry={retry} state={state} surface={surface} />
          <footer aria-hidden="true" className="palette-footer">
            <span>
              <Kbd announce={false} keys="arrowup" />{" "}
              <Kbd announce={false} keys="arrowdown" /> wählen
            </span>
            <span>
              <CornerDownLeft size={12} /> ausführen
            </span>
            <span className="palette-coverage">Ab 2 Zeichen: {coverage}</span>
          </footer>
        </Command>
      ) : null}
    </dialog>
  );
}
