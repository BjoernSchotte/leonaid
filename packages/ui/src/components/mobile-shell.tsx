import {
  CloudOff,
  LayoutGrid,
  LogOut,
  type LucideIcon,
  Wifi,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  HotkeyProvider,
  ShortcutHelp,
  useHotkeys,
  type HotkeyBinding,
} from "../keyboard";
import { cn } from "../lib/utils";
import { Button } from "./button";
import {
  resolvedTheme,
  setThemePreference,
  storedTheme,
  type ThemeMode,
} from "./theme-switcher";
import { ToastProvider } from "./toast";

export interface MobileShellTab {
  /** Stable key; also `data-nav-key` for tests and zone styling. */
  readonly key: string;
  readonly label: string;
  readonly href: string;
  readonly icon: LucideIcon;
  /** The filled accent tab ("Neu"). */
  readonly primary?: boolean;
}

export interface MobileShellMenuItem {
  readonly key: string;
  readonly label: string;
  readonly icon: LucideIcon;
  /** null renders a disabled tile marked "In Aufbau". */
  readonly href: string | null;
  readonly current?: boolean;
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
}

const OFFLINE_TEXT =
  "Du bist offline. Geöffnete Inhalte bleiben sichtbar. LeonAid speichert keine Änderungen im Hintergrund.";

const SHORTCUT_FOOTNOTE =
  "Kürzel wirken nicht, während du in ein Feld schreibst. Esc verlässt jedes Feld und jeden Dialog.";

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
  return (
    <HotkeyProvider>
      <ToastProvider>
        <MobileShellFrame {...props} />
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
  onLogout,
  person,
  role,
  tabs,
  zone = "pwa",
}: MobileShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(storedTheme);

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
          </span>
          <span className="pwa-bar-end">
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
        {offline ? (
          <p className="pwa-offline" data-testid="offline-banner" role="status">
            <CloudOff aria-hidden="true" size={16} />
            {OFFLINE_TEXT}
          </p>
        ) : null}
        {notices}
        <main className="pwa-main" id="main" tabIndex={-1}>
          <div className="pwa-screen">{children}</div>
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
        onClose={() => setMenuOpen(false)}
        onLogout={onLogout}
        onTheme={chooseTheme}
        open={menuOpen}
        person={person}
        role={role}
        search={menuSearch}
        theme={theme}
      />
      <ShortcutHelp footnote={SHORTCUT_FOOTNOTE} />
    </div>
  );
}

function ShellHotkeys({
  onToggleTheme,
  tabs,
}: {
  readonly onToggleTheme: () => void;
  readonly tabs: readonly MobileShellTab[];
}) {
  const bindings: HotkeyBinding[] = tabs.slice(0, 9).map((tab, index) => ({
    keys: String(index + 1),
    label: `App: ${tab.label}`,
    group: "Akquise-App",
    run: () => window.location.assign(tab.href),
  }));
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
  onLogout,
  onTheme,
  open,
  person,
  role,
  search,
  theme,
}: {
  readonly items: readonly MobileShellMenuItem[];
  readonly onClose: () => void;
  readonly onLogout: () => void;
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
        </div>
      ) : null}
    </dialog>
  );
}
