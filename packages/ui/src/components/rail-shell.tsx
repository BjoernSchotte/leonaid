import {
  ChevronsUpDown,
  Command as CommandIcon,
  Keyboard,
  LayoutGrid,
  LogOut,
  type LucideIcon,
  Moon,
  Search,
  Sun,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import { GO_TO_GROUP } from "../keyboard/shortcut-help";
import {
  HotkeyProvider,
  useHotkeys,
  useShortcutHelp,
} from "../keyboard/use-hotkeys";
import { PrefixHint } from "../keyboard/prefix-hint";
import { ShortcutHelp } from "../keyboard/shortcut-help";
import type { HotkeyBinding } from "../keyboard/hotkeys";
import { cn } from "../lib/utils";
import { Avatar } from "./avatar";
import { IconButton } from "./button";
import { isMacPlatform, Kbd } from "./kbd";
import { OptionMenu } from "./option-menu";
import { Popover } from "./popover";
import {
  resolvedTheme,
  setThemePreference,
  storedTheme,
  toggleTheme,
} from "./theme-switcher";
import { ToastProvider } from "./toast";

/** One rail destination, built from an item the server navigation returned. */
export interface RailNavItem {
  /** Server navigation key; also the item's `data-zone`. */
  readonly key: string;
  readonly label: string;
  readonly href: string;
  readonly icon: LucideIcon;
  /** Rail section title ("Arbeit", "Module", …); sections keep item order. */
  readonly group: string;
  /** Second key of the "g" sequence, when the zone has one. */
  readonly goKey?: string;
}

export interface RailCampaign {
  readonly id: string;
  readonly name: string;
  /** Second line in the switcher, e.g. the role in that campaign. */
  readonly hint?: string;
}

export interface RailCampaignSwitcherProps {
  readonly campaigns: readonly RailCampaign[];
  readonly currentId: string;
  readonly onSelect: (id: string) => void;
}

export interface RailShellUser {
  readonly name: string;
  readonly role: string;
}

export interface RailShellProps {
  readonly navigation: readonly RailNavItem[];
  /** Server navigation key of the current area; sets the shell's zone. */
  readonly activeKey?: string;
  readonly campaignSwitcher?: RailCampaignSwitcherProps;
  readonly user: RailShellUser;
  readonly onLogout: () => void;
  /** Second brand line, e.g. the club name. */
  readonly organizationName?: string;
  /** The command palette, mounted inside the shell's hotkey provider. */
  readonly palette?: ReactNode;
  /** Opens the palette; without it the search entries are not shown. */
  readonly onOpenPalette?: () => void;
  /** Keys shown first in the mobile bottom nav (up to four). */
  readonly mobilePrimaryKeys?: readonly string[];
  readonly systemBanner?: ReactNode;
  /** Follows a "g" shortcut; a full page load by default. */
  readonly navigate?: (href: string) => void;
  readonly children: ReactNode;
}

function assignLocation(href: string) {
  window.location.assign(href);
}

/** Zone of a page without a rail entry: a neutral band and no area name. */
export const NEUTRAL_ZONE = "none";

const MOBILE_QUERY = "(max-width: 720px)";

const DEFAULT_MOBILE_PRIMARY = [
  "overview-web",
  "orders",
  "invoices",
  "tasks",
] as const;
const MOBILE_PRIMARY_COUNT = 4;

function normalisePath(path: string): string {
  return path.replace(/\/+$/, "") || "/";
}

/**
 * The navigation key whose href is the longest prefix of `pathname`.
 * "/admin/" only matches itself, so the overview is not active everywhere.
 */
export function activeNavigationKey(
  items: readonly Pick<RailNavItem, "key" | "href">[],
  pathname: string,
): string | undefined {
  const path = normalisePath(pathname);
  let best: { key: string; length: number } | undefined;
  for (const item of items) {
    if (!item.href.startsWith("/")) continue;
    const href = normalisePath(new URL(item.href, "https://x").pathname);
    const matches = item.href.endsWith("/")
      ? path === href
      : path === href || path.startsWith(`${href}/`);
    if (matches && (!best || href.length > best.length)) {
      best = { key: item.key, length: href.length };
    }
  }
  return best?.key;
}

/** The items of the bottom nav: preferred keys first, then rail order. */
export function mobilePrimaryItems(
  items: readonly RailNavItem[],
  preferred: readonly string[] = DEFAULT_MOBILE_PRIMARY,
): RailNavItem[] {
  const chosen = preferred
    .map((key) => items.find((item) => item.key === key))
    .filter((item): item is RailNavItem => Boolean(item));
  for (const item of items) {
    if (chosen.length >= MOBILE_PRIMARY_COUNT) break;
    if (!chosen.includes(item)) chosen.push(item);
  }
  return chosen.slice(0, MOBILE_PRIMARY_COUNT);
}

function groupItems(items: readonly RailNavItem[]) {
  const groups = new Map<string, RailNavItem[]>();
  for (const item of items) {
    const list = groups.get(item.group);
    if (list) list.push(item);
    else groups.set(item.group, [item]);
  }
  return [...groups.entries()];
}

function NavItem({
  item,
  active,
  compact,
}: {
  readonly item: RailNavItem;
  readonly active: boolean;
  readonly compact?: boolean;
}) {
  const Glyph = item.icon;
  return (
    <a
      aria-current={active ? "page" : undefined}
      className={cn("nav-item", active && "is-active", compact && "is-compact")}
      data-nav-key={item.key}
      data-zone={item.key}
      href={item.href}
      title={compact ? undefined : item.label}
    >
      <span aria-hidden="true" className="nav-icon">
        <Glyph aria-hidden="true" size={compact ? 20 : 16} />
      </span>
      <span className="nav-label">{item.label}</span>
      {!compact && item.goKey ? (
        <Kbd announce={false} keys={`g ${item.goKey}`} subtle />
      ) : null}
    </a>
  );
}

function BrandMark() {
  return (
    <span aria-hidden="true" className="brand-mark">
      <span className="brand-l" />
      <span className="brand-dot" />
    </span>
  );
}

const campaignOpeners = new Set<() => void>();

/**
 * Opens the campaign switcher where it is visible: the rail (also the
 * collapsed rail) above 720 px, the "Mehr" sheet below. For the palette's
 * "Aktion wechseln …" command.
 */
export function openCampaignSwitcher(): void {
  // Let a closing dialog (the palette) restore focus first.
  window.setTimeout(() => {
    for (const open of campaignOpeners) open();
  }, 0);
}

function isVisible(element: HTMLElement | null): element is HTMLElement {
  return Boolean(element && element.getClientRects().length > 0);
}

function CampaignSwitcher({
  campaigns,
  currentId,
  onSelect,
  open,
  onOpenChange,
  variant,
}: RailCampaignSwitcherProps & {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly variant: "rail" | "sheet";
}) {
  const full = useRef<HTMLButtonElement>(null);
  const compact = useRef<HTMLButtonElement>(null);
  // The popover follows whichever trigger the layout shows right now.
  const anchor = useMemo<RefObject<HTMLButtonElement | null>>(
    () => ({
      get current() {
        if (isVisible(full.current)) return full.current;
        return compact.current ?? full.current;
      },
    }),
    [],
  );
  const current = campaigns.find((campaign) => campaign.id === currentId);
  if (campaigns.length === 0) return null;
  const name = current?.name ?? "Aktion wählen";
  const toggle = () => onOpenChange(!open);
  return (
    <>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className={variant === "rail" ? "rail-campaign" : "sheet-campaign"}
        data-testid={variant === "rail" ? "campaign-switcher" : undefined}
        onClick={toggle}
        ref={full}
        type="button"
      >
        <span className="rail-campaign-label">Aktion</span>
        <span
          className="rail-campaign-name"
          data-testid={variant === "rail" ? "current-action" : undefined}
        >
          {name}
        </span>
        <span className="sr-only"> wechseln</span>
        <ChevronsUpDown aria-hidden="true" size={14} />
      </button>
      {variant === "rail" ? (
        <button
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-label={`Aktion wechseln: ${name}`}
          className="rail-campaign-compact"
          data-testid="campaign-switcher-compact"
          onClick={toggle}
          ref={compact}
          title={`Aktion: ${name}`}
          type="button"
        >
          <ChevronsUpDown aria-hidden="true" size={16} />
        </button>
      ) : null}
      <Popover
        anchor={anchor}
        label="Aktion wechseln"
        onClose={() => onOpenChange(false)}
        open={open}
      >
        <OptionMenu
          onSelect={(id) => {
            onOpenChange(false);
            if (id !== current?.id) onSelect(id);
          }}
          options={campaigns.map((campaign) => ({
            value: campaign.id,
            label: campaign.name,
            hint: campaign.hint,
          }))}
          placeholder="Aktion suchen …"
          value={current?.id ?? ""}
        />
      </Popover>
    </>
  );
}

function RailUser({
  user,
  onLogout,
}: {
  readonly user: RailShellUser;
  readonly onLogout: () => void;
}) {
  return (
    <div className="rail-user">
      <Avatar name={user.name} />
      <span className="rail-user-text">
        <span className="rail-user-name" data-testid="display-name">
          {user.name}
        </span>
        <span className="rail-user-role" data-testid="roles">
          {user.role}
        </span>
      </span>
      <IconButton
        className="rail-logout"
        data-testid="logout"
        icon={LogOut}
        label="Abmelden"
        onClick={onLogout}
        size="sm"
      />
    </div>
  );
}

function ThemeButton() {
  const [dark, setDark] = useState(() => resolvedTheme() === "dark");

  // Any switch (this button, shift+t, the palette) changes <html data-theme>.
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setDark(resolvedTheme() === "dark");
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributeFilter: ["data-theme"] });
    sync();
    return () => observer.disconnect();
  }, []);

  // Follow the system while no explicit choice is stored.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      if (storedTheme() === "system") setThemePreference("system");
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return (
    <IconButton
      data-testid="theme-toggle"
      icon={dark ? Sun : Moon}
      label={
        dark
          ? "Helle Darstellung (Umschalt+T)"
          : "Dunkle Darstellung (Umschalt+T)"
      }
      onClick={() => void toggleTheme()}
    />
  );
}

/** Registered between the palette and the help, as listed in the prototype. */
function ThemeHotkey() {
  useHotkeys([
    {
      keys: "shift+t",
      label: "Hell/Dunkel wechseln",
      group: "Allgemein",
      run: () => void toggleTheme(),
    },
  ]);
  return null;
}

function closeDialog(dialog: HTMLDialogElement) {
  if (!dialog.open) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

function MoreSheet({
  open,
  onClose,
  items,
  activeKey,
  user,
  onLogout,
  onOpenPalette,
  campaignSwitcher,
  campaignOpen,
  onCampaignOpenChange,
}: {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly items: readonly RailNavItem[];
  readonly activeKey: string | undefined;
  readonly user: RailShellUser;
  readonly onLogout: () => void;
  readonly onOpenPalette?: () => void;
  readonly campaignSwitcher?: RailCampaignSwitcherProps;
  readonly campaignOpen: boolean;
  readonly onCampaignOpenChange: (open: boolean) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) closeDialog(dialog);
  }, [open]);

  return (
    <dialog
      aria-label="Alle Bereiche"
      className="sheet"
      data-testid="mobile-sheet"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      ref={ref}
    >
      {open ? (
        <div className="sheet-body">
          <header className="sheet-header">
            <h2>Alle Bereiche</h2>
            <IconButton icon={X} label="Schließen" onClick={onClose} />
          </header>
          {onOpenPalette ? (
            <button
              className="rail-search sheet-search"
              onClick={() => {
                // Close first, so focus is back on "Mehr" when the palette
                // opens and records where to return.
                if (ref.current) closeDialog(ref.current);
                onClose();
                onOpenPalette();
              }}
              type="button"
            >
              <CommandIcon aria-hidden="true" size={15} />
              Suchen und Befehle
            </button>
          ) : null}
          <nav aria-label="Alle Bereiche" className="sheet-grid">
            {items.map((item) => {
              const Glyph = item.icon;
              return (
                <a
                  aria-current={item.key === activeKey ? "page" : undefined}
                  className="sheet-tile"
                  data-nav-key={item.key}
                  data-zone={item.key}
                  href={item.href}
                  key={item.key}
                >
                  <span aria-hidden="true" className="sheet-tile-icon">
                    <Glyph aria-hidden="true" size={18} />
                  </span>
                  {item.label}
                </a>
              );
            })}
          </nav>
          {campaignSwitcher ? (
            <div className="sheet-campaign-row">
              <CampaignSwitcher
                {...campaignSwitcher}
                onOpenChange={onCampaignOpenChange}
                open={campaignOpen}
                variant="sheet"
              />
            </div>
          ) : null}
          <div className="sheet-account">
            <Avatar name={user.name} size="md" />
            <span className="sheet-account-text">
              <span className="sheet-account-name">{user.name}</span>
              <span className="sheet-account-role">{user.role}</span>
            </span>
            <button
              className="btn btn-secondary btn-md sheet-logout"
              onClick={onLogout}
              type="button"
            >
              <LogOut aria-hidden="true" size={16} />
              <span className="btn-label">Abmelden</span>
            </button>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}

function ShellFrame({
  navigation,
  activeKey,
  campaignSwitcher,
  user,
  onLogout,
  organizationName,
  palette,
  onOpenPalette,
  mobilePrimaryKeys,
  systemBanner,
  navigate = assignLocation,
  children,
}: RailShellProps) {
  const help = useShortcutHelp();
  const [moreOpen, setMoreOpen] = useState(false);
  const [railCampaignOpen, setRailCampaignOpen] = useState(false);
  const [sheetCampaignOpen, setSheetCampaignOpen] = useState(false);
  const active = navigation.find((item) => item.key === activeKey);
  const ActiveIcon = active?.icon;
  // A page without a rail entry gets a neutral band, not the overview hue.
  const zone = active?.key ?? NEUTRAL_ZONE;

  // The sheet belongs to the bottom nav: growing past 720 px closes it.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(MOBILE_QUERY);
    const update = () => {
      if (!media.matches) {
        setMoreOpen(false);
        setSheetCampaignOpen(false);
      }
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  // openCampaignSwitcher(): the rail switcher, or the sheet's on phones.
  useEffect(() => {
    const open = () => {
      const mobile =
        typeof window.matchMedia === "function" &&
        window.matchMedia(MOBILE_QUERY).matches;
      if (mobile) {
        setMoreOpen(true);
        setSheetCampaignOpen(true);
      } else {
        setRailCampaignOpen(true);
      }
    };
    campaignOpeners.add(open);
    return () => {
      campaignOpeners.delete(open);
    };
  }, []);

  // Registered here, before the page renders, so page bindings win.
  const bindings: HotkeyBinding[] = navigation
    .filter((item) => item.goKey)
    .map((item) => ({
      keys: `g ${item.goKey}`,
      label: item.label,
      group: GO_TO_GROUP,
      zone: item.key,
      run: () => navigate(item.href),
    }));
  useHotkeys(bindings);

  return (
    <div className="shell" data-testid="rail-shell" data-zone={zone}>
      <a className="skip-link" href="#main-content">
        Zum Inhalt springen
      </a>
      {/* Overlays render before the page so page bindings ("/", "?") win. */}
      {palette}
      <ThemeHotkey />
      <ShortcutHelp />
      <PrefixHint />
      <aside
        aria-label="Seitenleiste"
        className="shell-rail"
        data-testid="desktop-sidebar"
      >
        <div className="rail">
          <div className="rail-brand">
            <BrandMark />
            <span className="brand-text">
              <span className="brand-name">LeonAid</span>
              {organizationName ? (
                <span className="brand-club" title={organizationName}>
                  {organizationName}
                </span>
              ) : null}
            </span>
          </div>
          {campaignSwitcher ? (
            <CampaignSwitcher
              {...campaignSwitcher}
              onOpenChange={setRailCampaignOpen}
              open={railCampaignOpen}
              variant="rail"
            />
          ) : null}
          {onOpenPalette ? (
            <button
              aria-label="Suchen und Befehle"
              className="rail-search"
              onClick={onOpenPalette}
              type="button"
            >
              <Search aria-hidden="true" size={15} />
              <span>Suchen und Befehle</span>
              <Kbd announce={false} keys="mod+k" subtle />
            </button>
          ) : null}
          <nav aria-label="Hauptnavigation" className="rail-nav">
            {groupItems(navigation).map(([group, items]) => (
              <div className="rail-group" key={group}>
                <h2 className="rail-group-title">{group}</h2>
                {items.map((item) => (
                  <NavItem
                    active={item.key === active?.key}
                    item={item}
                    key={item.key}
                  />
                ))}
              </div>
            ))}
          </nav>
          <RailUser onLogout={onLogout} user={user} />
        </div>
      </aside>
      <div className="shell-body">
        {systemBanner}
        <header className="topbar">
          <div className="topbar-start">
            {ActiveIcon ? (
              <span aria-hidden="true" className="zone-mark">
                <ActiveIcon aria-hidden="true" size={16} />
              </span>
            ) : null}
            <span className="topbar-zone" data-testid="topbar-zone">
              {active?.label}
            </span>
          </div>
          <div className="topbar-end">
            {onOpenPalette ? (
              <button
                aria-label="Suchen und Befehle"
                className="topbar-search"
                onClick={onOpenPalette}
                title={`Suchen und Befehle (${isMacPlatform() ? "⌘K" : "Strg+K"})`}
                type="button"
              >
                <Search aria-hidden="true" size={15} />
                <span className="topbar-search-text">Suchen</span>
                <Kbd announce={false} keys="mod+k" subtle />
              </button>
            ) : null}
            <IconButton
              className="hide-mobile"
              icon={Keyboard}
              label="Tastenkürzel (?)"
              onClick={() => help.setOpen(true)}
            />
            <ThemeButton />
          </div>
        </header>
        <main className="main" data-zone={zone} id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>

      <nav aria-label="Hauptnavigation mobil" className="bottom-nav">
        {mobilePrimaryItems(navigation, mobilePrimaryKeys).map((item) => (
          <NavItem
            active={item.key === active?.key}
            compact
            item={item}
            key={item.key}
          />
        ))}
        <button
          aria-expanded={moreOpen}
          aria-haspopup="dialog"
          className="nav-item is-compact"
          data-testid="mobile-menu"
          onClick={() => setMoreOpen(true)}
          type="button"
        >
          <span aria-hidden="true" className="nav-icon">
            <LayoutGrid aria-hidden="true" size={20} />
          </span>
          <span className="nav-label">Mehr</span>
        </button>
      </nav>

      <MoreSheet
        activeKey={active?.key}
        campaignOpen={sheetCampaignOpen}
        campaignSwitcher={campaignSwitcher}
        items={navigation}
        onCampaignOpenChange={setSheetCampaignOpen}
        onClose={() => {
          setMoreOpen(false);
          setSheetCampaignOpen(false);
        }}
        onLogout={onLogout}
        onOpenPalette={onOpenPalette}
        open={moreOpen}
        user={user}
      />
    </div>
  );
}

/**
 * Admin shell of the Leitsystem: Lions-blue rail with zone tiles, campaign
 * switcher and search entry, a topbar with the 3 px zone band, a collapsed
 * icon rail at ≤ 1024 px and a bottom nav with a "Mehr" sheet at ≤ 720 px.
 * The rail lists only the items passed in, which come from the server
 * navigation of the current account.
 */
export function RailShell(props: RailShellProps) {
  return (
    <ToastProvider>
      <HotkeyProvider>
        <ShellFrame {...props} />
      </HotkeyProvider>
    </ToastProvider>
  );
}
