import {
  CloudOff,
  LayoutGrid,
  LogOut,
  type LucideIcon,
  Wifi,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import {
  HotkeyProvider,
  ShortcutHelp,
  useHotkeys,
  type HotkeyBinding,
} from "../keyboard";
import { cn } from "../lib/utils";
import { useFocusNotObscured } from "./focus-clear";
import { Button, buttonClassName } from "./button";
import { ConfirmDialog } from "./confirm-dialog";
import { LeaveGuardContext, LeaveGuardRegistry } from "./leave-guard";
import { LegalLinks } from "./legal-links";
import { PageBarContext } from "./page-bar";
import {
  resolvedTheme,
  setThemePreference,
  storedTheme,
  type ThemeMode,
} from "./theme";
import { ToastProvider } from "./toast";

export interface MobileShellTab {
  /** Stable key; also `data-nav-key` for tests and zone styling. */
  readonly key: string;
  readonly label: string;
  readonly href: string;
  readonly icon: LucideIcon;
  /** The filled accent tab ("Neu"). */
  readonly primary?: boolean;
  /** Digit that opens the tab ("1"–"9"), fixed per tab. */
  readonly shortcut?: string;
}

export interface MobileShellMenuItem {
  readonly key: string;
  readonly label: string;
  readonly icon: LucideIcon;
  /** null renders a disabled tile marked "In Aufbau". */
  readonly href: string | null;
  readonly current?: boolean;
}

/**
 * The other member app and the start-area choice (specs/multi-domain §6.7),
 * shown in the "Mehr" sheet for members with roles in both apps.
 */
export interface MobileShellSurfaces {
  /** Link into the admin web app, e.g. "Zur Verwaltung". */
  readonly switchTo?: { readonly label: string; readonly href: string };
  /** Start-area options: this app, or back to the default rule. */
  readonly startAreas?: readonly {
    readonly label: string;
    readonly onSelect: () => void;
  }[];
}

/**
 * The capture queue on the network glyph (specs/pwa-offline-queue §12.2):
 * a count in the tone of the most urgent entry, its accessible name, and
 * the "Warteschlange" sheet it opens.
 */
export interface MobileShellQueue {
  readonly count: number;
  readonly state:
    | "empty"
    | "waiting"
    | "sending"
    | "decision"
    | "failed"
    | "settled";
  /** "3 Einträge warten auf Versand"; empty uses "Online"/"Offline". */
  readonly label: string;
  readonly onOpen: () => void;
}

export interface MobileShellProps {
  readonly tabs: readonly MobileShellTab[];
  /** Key of the current tab, or null when the page has no tab. */
  readonly active: string | null;
  readonly offline: boolean;
  readonly children: ReactNode;
  /** Campaign shown in the app bar. */
  readonly campaign: string;
  /** Role line in the app bar, e.g. "Akquise". */
  readonly role: string;
  readonly person: string;
  /** Further areas, listed in the "Mehr" sheet. */
  readonly menuItems?: readonly MobileShellMenuItem[];
  /** Optional search block on top of the "Mehr" sheet. */
  readonly menuSearch?: ReactNode;
  /** Update or install notices under the app bar. */
  readonly notices?: ReactNode;
  readonly onLogout: () => void;
  /** Zone hue of the surface (`data-zone`). */
  readonly zone?: string;
  readonly surfaces?: MobileShellSurfaces;
  /** The PWA's capture queue; without it the glyph is a status image. */
  readonly queue?: MobileShellQueue;
  /** Replaces the offline banner text (the PWA with its queue, §12.1). */
  readonly offlineText?: ReactNode;
}

const OFFLINE_TEXT =
  "Du bist offline. Geöffnete Inhalte bleiben sichtbar. LeonAid speichert keine Änderungen im Hintergrund.";

const SHORTCUT_FOOTNOTE =
  "Kürzel wirken nicht, während du in ein Feld schreibst. Esc verlässt jedes Feld und jeden Dialog.";

const LEAVE_QUESTION =
  "Du hast Eingaben, die noch nicht gespeichert sind. Wenn du die Seite wechselst, gehen sie verloren.";

const TEXT_INPUT_TYPES = new Set([
  "date",
  "datetime-local",
  "email",
  "month",
  "number",
  "tel",
  "text",
  "time",
  "url",
  "week",
]);

/** Put on a field or a container whose input must not count as unsaved. */
export const LEAVE_GUARD_OFF_ATTRIBUTE = "data-leave-guard";

/**
 * Search and filter fields lose nothing on leaving (filters live in the
 * URL), so they never count: `type="search"`, `role="searchbox"`, fields
 * inside `role="search"` and anything under `data-leave-guard="off"`.
 */
function countsAsInput(
  field: Element,
): field is HTMLInputElement | HTMLTextAreaElement {
  const typed =
    field instanceof HTMLTextAreaElement ||
    (field instanceof HTMLInputElement && TEXT_INPUT_TYPES.has(field.type));
  if (!typed) return false;
  if (field.getAttribute("role") === "searchbox") return false;
  return !field.closest(
    `[${LEAVE_GUARD_OFF_ATTRIBUTE}="off"], [role="search"]`,
  );
}

/**
 * One in-app question before shell navigation (tabs, digit keys, sheet
 * links) would drop unsaved work. Unsaved work is a page registered through
 * `useLeaveGuard(dirty)`, or a text field the user typed into that is still
 * on the page, not empty and not opted out. A saved form that resets,
 * unmounts or marks itself `data-leave-guard="off"` stops counting.
 */
function useShellLeaveGuard(registry: LeaveGuardRegistry) {
  const mainRef = useRef<HTMLElement>(null);
  const touched = useRef(new Set<HTMLInputElement | HTMLTextAreaElement>());
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  useEffect(() => {
    const main = mainRef.current;
    if (!main) return;
    const onInput = (event: Event) => {
      const target = event.target;
      if (target instanceof Element && countsAsInput(target)) {
        touched.current.add(target);
      }
    };
    main.addEventListener("input", onInput, true);
    return () => main.removeEventListener("input", onInput, true);
  }, []);

  function hasUnsavedWork(): boolean {
    if (registry.hasDirtyPages()) return true;
    for (const field of touched.current) {
      if (!field.isConnected) touched.current.delete(field);
      // The opt-out can come later, e.g. once a form is saved.
      else if (countsAsInput(field) && field.value.trim() !== "") return true;
    }
    return false;
  }

  /** Leaves at once, or asks first when work would be lost. */
  function requestLeave(href: string): void {
    if (hasUnsavedWork()) setPendingHref(href);
    else window.location.assign(href);
  }

  const question = (
    <ConfirmDialog
      confirmLabel="Verwerfen und wechseln"
      description={LEAVE_QUESTION}
      onConfirm={() => {
        const href = pendingHref;
        setPendingHref(null);
        if (!href) return;
        // Page guards stay silent: the user already answered.
        registry.leaving = true;
        window.location.assign(href);
      }}
      onOpenChange={(open) => {
        if (!open) setPendingHref(null);
      }}
      open={pendingHref !== null}
      title="Seite wechseln?"
      tone="danger"
    />
  );

  return { hasUnsavedWork, mainRef, question, requestLeave };
}

const THEME_OPTIONS: readonly { value: ThemeMode; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Hell" },
  { value: "dark", label: "Dunkel" },
];

/**
 * Phone-first shell of the acquisition app: Lions-blue app bar with
 * campaign, role and network state, offline notice, one 480 px column and a
 * fixed bottom tab bar. Further areas, theme and sign-out sit in the "Mehr"
 * sheet. Mounts the hotkey registry (tabs on 1–n, ⇧T, ?) and the toaster.
 */
export function MobileShell(props: MobileShellProps) {
  const [registry] = useState(() => new LeaveGuardRegistry());
  return (
    <HotkeyProvider>
      <ToastProvider>
        <LeaveGuardContext.Provider value={registry}>
          <MobileShellFrame {...props} registry={registry} />
        </LeaveGuardContext.Provider>
      </ToastProvider>
    </HotkeyProvider>
  );
}

function MobileShellFrame({
  active,
  campaign,
  children,
  menuItems = [],
  menuSearch,
  notices,
  offline,
  offlineText,
  onLogout,
  queue,
  surfaces,
  person,
  role,
  tabs,
  zone = "pwa",
  registry,
}: MobileShellProps & { readonly registry: LeaveGuardRegistry }) {
  useFocusNotObscured();
  const [menuOpen, setMenuOpen] = useState(false);
  const [barSub, setBarSub] = useState<HTMLElement | null>(null);
  const [barEnd, setBarEnd] = useState<HTMLElement | null>(null);
  const pageBar = useMemo(
    () => ({ sub: barSub, end: barEnd }),
    [barSub, barEnd],
  );
  const [theme, setTheme] = useState<ThemeMode>(storedTheme);
  const { hasUnsavedWork, mainRef, question, requestLeave } =
    useShellLeaveGuard(registry);
  const guardLink = (event: MouseEvent<HTMLAnchorElement>) => {
    // A new tab or window (modifier or middle click) drops nothing here.
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    if (!hasUnsavedWork()) return;
    event.preventDefault();
    requestLeave(event.currentTarget.href);
  };

  function chooseTheme(mode: ThemeMode) {
    setThemePreference(mode);
    setTheme(mode);
  }

  // "system" follows the OS while the app is open.
  useEffect(() => {
    if (theme !== "system" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => setThemePreference("system");
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [theme]);

  return (
    <div className="pwa-stage" data-zone={zone}>
      {/* Before the page: page bindings register later and win. */}
      <ShellHotkeys
        onLeave={requestLeave}
        onToggleTheme={() =>
          chooseTheme(resolvedTheme() === "dark" ? "light" : "dark")
        }
        tabs={tabs}
      />
      <div className="pwa">
        <a className="pwa-skip-link" href="#main">
          Zum Inhalt springen
        </a>
        <header className="pwa-bar">
          <span className="pwa-campaign">
            <span className="pwa-campaign-name" data-testid="current-action">
              {campaign}
            </span>
            <span className="pwa-campaign-sub">
              {role ? `${role} · ` : ""}
              <span data-testid="display-name">{person}</span>
            </span>
            {/* A page's own line ("Meine Tour · Sa 05.12.") replaces the
                role line while it is filled (CSS :empty). */}
            <span
              className="pwa-campaign-sub pwa-bar-page-sub"
              ref={setBarSub}
            />
          </span>
          <span className="pwa-bar-end">
            <span className="pwa-bar-page-end" ref={setBarEnd} />
            {queue ? (
              <button
                aria-haspopup="dialog"
                aria-label={
                  queue.state === "empty"
                    ? offline
                      ? "Offline"
                      : "Online"
                    : queue.label
                }
                className={cn("pwa-net", "is-button", offline && "is-offline")}
                data-queue-state={queue.state}
                data-testid="network-state"
                onClick={queue.onOpen}
                title={queue.state === "empty" ? "Warteschlange" : queue.label}
                type="button"
              >
                {offline ? (
                  <CloudOff aria-hidden="true" size={18} />
                ) : (
                  <Wifi aria-hidden="true" size={18} />
                )}
                {queue.state === "sending" ? (
                  <span
                    aria-hidden="true"
                    className="pwa-net-badge is-sending"
                    data-testid="queue-badge"
                  />
                ) : queue.state !== "empty" ? (
                  <span
                    aria-hidden="true"
                    className={cn(
                      "pwa-net-badge",
                      queue.state === "decision" && "tone-warn",
                      queue.state === "failed" && "tone-danger",
                    )}
                    data-testid="queue-badge"
                  >
                    {queue.count}
                  </span>
                ) : null}
              </button>
            ) : (
              <span
                aria-label={offline ? "Offline" : "Online"}
                className={cn("pwa-net", offline && "is-offline")}
                data-testid="network-state"
                role="img"
                title={offline ? "Offline" : "Online"}
              >
                {offline ? (
                  <CloudOff aria-hidden="true" size={18} />
                ) : (
                  <Wifi aria-hidden="true" size={18} />
                )}
              </span>
            )}
            <button
              aria-expanded={menuOpen}
              aria-haspopup="dialog"
              className="pwa-menu-button"
              data-testid="pwa-menu"
              onClick={() => setMenuOpen(true)}
              title="Mehr"
              type="button"
            >
              <LayoutGrid aria-hidden="true" size={20} />
              <span className="sr-only">Mehr</span>
            </button>
          </span>
        </header>
        {/* Always mounted, so screen readers announce the text when it
            appears. */}
        <div className="pwa-offline-region" role="status">
          {offline ? (
            <p className="pwa-offline" data-testid="offline-banner">
              <CloudOff aria-hidden="true" size={16} />
              <span>{offlineText ?? OFFLINE_TEXT}</span>
            </p>
          ) : null}
        </div>
        {notices}
        <main className="pwa-main" id="main" ref={mainRef} tabIndex={-1}>
          <PageBarContext.Provider value={pageBar}>
            <div className="pwa-screen">{children}</div>
          </PageBarContext.Provider>
        </main>
        {tabs.length ? (
          <nav aria-label="App-Navigation" className="pwa-tabs">
            {tabs.map((tab) => {
              const current = tab.key === active;
              return (
                <a
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "pwa-tab",
                    tab.primary && "is-new",
                    current && "is-active",
                  )}
                  data-nav-key={tab.key}
                  href={tab.href}
                  key={tab.key}
                  onClick={guardLink}
                >
                  <span aria-hidden="true" className="pwa-tab-icon">
                    <tab.icon size={tab.primary ? 22 : 20} />
                  </span>
                  <span className="pwa-tab-label">{tab.label}</span>
                </a>
              );
            })}
          </nav>
        ) : null}
      </div>
      <MoreSheet
        items={menuItems}
        onNavigate={guardLink}
        onClose={() => setMenuOpen(false)}
        onLogout={onLogout}
        surfaces={surfaces}
        onTheme={chooseTheme}
        open={menuOpen}
        person={person}
        role={role}
        search={menuSearch}
        theme={theme}
      />
      <ShortcutHelp footnote={SHORTCUT_FOOTNOTE} />
      {question}
    </div>
  );
}

function ShellHotkeys({
  onLeave,
  onToggleTheme,
  tabs,
}: {
  readonly onLeave: (href: string) => void;
  readonly onToggleTheme: () => void;
  readonly tabs: readonly MobileShellTab[];
}) {
  // Fixed digits per tab, as in the prototype: a missing tab leaves its
  // digit unbound instead of shifting the others.
  const bindings: HotkeyBinding[] = tabs.flatMap((tab) =>
    tab.shortcut
      ? [
          {
            keys: tab.shortcut,
            label: `App: ${tab.label}`,
            group: "Akquise-App",
            run: () => onLeave(tab.href),
          },
        ]
      : [],
  );
  bindings.push({
    keys: "shift+t",
    label: "Hell/Dunkel wechseln",
    group: "Allgemein",
    run: onToggleTheme,
  });
  useHotkeys(bindings);
  return null;
}

function MoreSheet({
  items,
  onClose,
  onNavigate,
  onLogout,
  onTheme,
  open,
  person,
  role,
  search,
  surfaces,
  theme,
}: {
  readonly items: readonly MobileShellMenuItem[];
  readonly onClose: () => void;
  readonly onNavigate: (event: MouseEvent<HTMLAnchorElement>) => void;
  readonly onLogout: () => void;
  readonly surfaces?: MobileShellSurfaces;
  readonly onTheme: (mode: ThemeMode) => void;
  readonly open: boolean;
  readonly person: string;
  readonly role: string;
  readonly search?: ReactNode;
  readonly theme: ThemeMode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      returnFocus.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      const target = returnFocus.current;
      returnFocus.current = null;
      if (target?.isConnected) target.focus();
    }
  }, [open]);

  return (
    <dialog
      aria-labelledby="pwa-sheet-title"
      className="pwa-sheet"
      data-testid="pwa-sheet"
      onCancel={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        onCloseRef.current();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onCloseRef.current();
      }}
      onClose={(event) => {
        // A close the browser forces (repeated Esc) still updates the state.
        if (event.target === event.currentTarget && open) onCloseRef.current();
      }}
      ref={ref}
    >
      {open ? (
        <div className="pwa-sheet-body">
          <header className="pwa-sheet-header">
            <h2 id="pwa-sheet-title">Mehr</h2>
            <button
              aria-label="Schließen"
              className="pwa-sheet-close"
              onClick={onClose}
              title="Schließen"
              type="button"
            >
              <X aria-hidden="true" size={20} />
            </button>
          </header>
          {search}
          {items.length ? (
            <nav aria-label="Weitere Bereiche" className="pwa-sheet-grid">
              {items.map((item) =>
                item.href ? (
                  <a
                    aria-current={item.current ? "page" : undefined}
                    className="pwa-sheet-tile"
                    data-nav-key={item.key}
                    data-zone={item.key}
                    href={item.href}
                    key={item.key}
                    onClick={onNavigate}
                  >
                    <span aria-hidden="true" className="pwa-sheet-tile-icon">
                      <item.icon size={18} />
                    </span>
                    {item.label}
                  </a>
                ) : (
                  <span
                    aria-disabled="true"
                    className="pwa-sheet-tile"
                    data-nav-key={item.key}
                    data-zone={item.key}
                    key={item.key}
                  >
                    <span aria-hidden="true" className="pwa-sheet-tile-icon">
                      <item.icon size={18} />
                    </span>
                    {item.label}
                    <span className="pwa-sheet-tile-status">In Aufbau</span>
                  </span>
                ),
              )}
            </nav>
          ) : null}
          <section
            aria-labelledby="pwa-sheet-theme"
            className="pwa-sheet-section"
          >
            <h3 className="pwa-sheet-label" id="pwa-sheet-theme">
              Darstellung
            </h3>
            <div
              aria-labelledby="pwa-sheet-theme"
              className="pwa-segment"
              role="group"
            >
              {THEME_OPTIONS.map((option) => (
                <button
                  aria-pressed={theme === option.value}
                  data-testid={`theme-${option.value}`}
                  key={option.value}
                  onClick={() => onTheme(option.value)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </section>
          {surfaces?.switchTo || surfaces?.startAreas?.length ? (
            <section
              aria-labelledby="pwa-sheet-surfaces"
              className="pwa-sheet-section"
              data-testid="pwa-surfaces"
            >
              <h3 className="pwa-sheet-label" id="pwa-sheet-surfaces">
                Bereiche
              </h3>
              <div className="pwa-surfaces">
                {surfaces.switchTo ? (
                  <a
                    className={buttonClassName({
                      variant: "secondary",
                      size: "lg",
                    })}
                    href={surfaces.switchTo.href}
                    onClick={onNavigate}
                  >
                    {surfaces.switchTo.label}
                  </a>
                ) : null}
                {surfaces.startAreas?.map((choice) => (
                  <Button
                    key={choice.label}
                    onClick={choice.onSelect}
                    size="lg"
                    variant="ghost"
                  >
                    {choice.label}
                  </Button>
                ))}
              </div>
            </section>
          ) : null}
          <div className="pwa-account">
            <span className="pwa-account-text">
              <span className="pwa-account-name">{person}</span>
              {role ? <span className="pwa-account-role">{role}</span> : null}
            </span>
            <Button
              data-testid="logout"
              icon={LogOut}
              onClick={onLogout}
              size="lg"
              variant="secondary"
            >
              Abmelden
            </Button>
          </div>
          <LegalLinks className="sheet-legal" />
        </div>
      ) : null}
    </dialog>
  );
}
