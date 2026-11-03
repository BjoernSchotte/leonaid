/**
 * Global keyboard layer, ported from the Leitsystem prototype (keyboard.ts).
 *
 * - Single keys ("j", "?", "shift+t", "mod+k") and two-key sequences ("g t").
 *   A sequence prefix waits SEQUENCE_TIMEOUT_MS for its second key.
 * - Typing guard: while focus is in an input, textarea, select or
 *   contenteditable element, only "mod+…", Escape and bindings marked
 *   `allowInInput` run.
 * - Dialog guard: while an open <dialog> exists that is not marked with
 *   HOTKEY_PASSTHROUGH_ATTRIBUTE (the command palette), only bindings marked
 *   `inDialog` run.
 * - IME composition never triggers anything.
 * - Later registrations win, so a page binding beats the shell binding.
 */

import { isMacPlatform } from "../components/kbd";

export const SEQUENCE_TIMEOUT_MS = 1200;

/** Put on a <dialog> (the palette) that must not mute global bindings. */
export const HOTKEY_PASSTHROUGH_ATTRIBUTE = "data-hotkeys-passthrough";

export interface HotkeyBinding {
  /** "j", "?", "shift+t", "mod+k", "escape" or a sequence like "g t". */
  readonly keys: string;
  /** Shown in the shortcut help, e.g. "Nächste Zeile". */
  readonly label: string;
  /** Help overlay section, e.g. "Allgemein", "Liste", "Gehe zu". */
  readonly group: string;
  readonly run: (event: KeyboardEvent) => void;
  /** Evaluated per key press; false skips the binding. */
  readonly when?: () => boolean;
  /** Also runs while a non-passthrough <dialog> is open. */
  readonly inDialog?: boolean;
  /** Also runs while the user types in a field. */
  readonly allowInInput?: boolean;
  /** Hidden from the help overlay (aliases such as "arrowdown" for "j"). */
  readonly hidden?: boolean;
  /** Server navigation key; the help shows its zone dot ("Gehe zu"). */
  readonly zone?: string;
}

export interface RegisteredHotkey extends HotkeyBinding {
  readonly id: number;
}

interface BindingSet {
  bindings: readonly HotkeyBinding[];
}

export interface HotkeyHandle {
  update(bindings: readonly HotkeyBinding[]): void;
  dispose(): void;
}

type Listener = () => void;

const MODIFIER_KEYS = new Set([
  "shift",
  "control",
  "meta",
  "alt",
  "altgraph",
  "capslock",
  "os",
]);

const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "image",
  "radio",
  "range",
  "reset",
  "submit",
]);

/** Enter and Space keep their native meaning on these. */
const NATIVE_ACTIVATION_SELECTOR =
  "a[href], button, summary, label, [role='button'], [role='link'], [role='tab'], [role='option'], [role='menuitem'], [role='checkbox'], [role='switch']";

/** The pressed combination in binding notation, or null for bare modifiers. */
export function normaliseEvent(
  event: KeyboardEvent,
  mac = isMacPlatform(),
): string | null {
  if (typeof event.key !== "string" || event.key === "") return null;
  let key = event.key.toLowerCase();
  if (MODIFIER_KEYS.has(key) || key === "dead" || key === "unidentified") {
    return null;
  }
  if (key === " ") key = "space";
  else if (key === "esc") key = "escape";
  const parts: string[] = [];
  if (mac ? event.metaKey : event.ctrlKey) parts.push("mod");
  // The other platform's command key must not leave a bare "k" behind.
  if (mac ? event.ctrlKey : event.metaKey) parts.push(mac ? "ctrl" : "meta");
  if (event.altKey) parts.push("alt");
  // "?" and other shifted symbols match by their character; letters and
  // named keys carry an explicit "shift".
  if (event.shiftKey && (key.length > 1 || /[a-z]/.test(key))) {
    parts.push("shift");
  }
  parts.push(key);
  return parts.join("+");
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target instanceof HTMLElement && target.isContentEditable) return true;
  if (target.closest("[contenteditable]:not([contenteditable='false'])")) {
    return true;
  }
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) {
    return !NON_TEXT_INPUT_TYPES.has(target.type);
  }
  return false;
}

/** True while an open <dialog> other than the palette exists. */
export function isBlockingDialogOpen(doc: Document = document): boolean {
  return [...doc.querySelectorAll("dialog[open]")].some(
    (dialog) => !dialog.hasAttribute(HOTKEY_PASSTHROUGH_ATTRIBUTE),
  );
}

function isImeEvent(event: KeyboardEvent): boolean {
  // keyCode 229 is what browsers report for keys consumed by an IME.
  return event.isComposing || event.keyCode === 229;
}

export class HotkeyRegistry {
  private readonly sets = new Map<number, BindingSet>();
  private readonly listeners = new Set<Listener>();
  private readonly prefixListeners = new Set<Listener>();
  private nextOrder = 0;
  private snapshot: readonly RegisteredHotkey[] = [];
  private pendingPrefix: string | null = null;
  private prefixTimer: ReturnType<typeof setTimeout> | undefined;
  private helpOpen = false;
  private readonly helpListeners = new Set<Listener>();

  /** Registers a set of bindings; the handle updates or removes it. */
  register(bindings: readonly HotkeyBinding[]): HotkeyHandle {
    const order = this.nextOrder++;
    this.sets.set(order, { bindings });
    this.changed();
    return {
      update: (next) => {
        const set = this.sets.get(order);
        if (!set) return;
        set.bindings = next;
        this.changed();
      },
      dispose: () => {
        if (this.sets.delete(order)) this.changed();
      },
    };
  }

  /** Every registered binding in registration order (stable snapshot). */
  getAll(): readonly RegisteredHotkey[] {
    return this.snapshot;
  }

  /**
   * The bindings the help overlay lists: one per key (the winning, latest
   * registration), in registration order, without hidden ones and without
   * those whose `when` is currently false.
   */
  getVisible(): RegisteredHotkey[] {
    const winners = new Map<string, RegisteredHotkey>();
    for (const entry of this.snapshot) winners.set(entry.keys, entry);
    return this.snapshot.filter(
      (entry) =>
        winners.get(entry.keys) === entry &&
        !entry.hidden &&
        (entry.when?.() ?? true),
    );
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getPendingPrefix = (): string | null => this.pendingPrefix;

  subscribePrefix = (listener: Listener): (() => void) => {
    this.prefixListeners.add(listener);
    return () => this.prefixListeners.delete(listener);
  };

  isHelpOpen = (): boolean => this.helpOpen;

  setHelpOpen = (open: boolean): void => {
    if (this.helpOpen === open) return;
    this.helpOpen = open;
    this.helpListeners.forEach((listener) => listener());
  };

  subscribeHelp = (listener: Listener): (() => void) => {
    this.helpListeners.add(listener);
    return () => this.helpListeners.delete(listener);
  };

  /** Keydown handler; attach it to window (HotkeyProvider does). */
  handleKeyDown = (event: KeyboardEvent): void => {
    if (event.defaultPrevented || isImeEvent(event)) return;
    const combo = normaliseEvent(event);
    if (!combo) return;

    const typing = isTypingTarget(event.target);
    const dialogOpen =
      typeof document !== "undefined" && isBlockingDialogOpen(document);
    const alwaysOn = combo.startsWith("mod+") || combo === "escape";

    if (
      (combo === "enter" || combo === "space") &&
      event.target instanceof Element &&
      event.target.closest(NATIVE_ACTIVATION_SELECTOR)
    ) {
      this.setPrefix(null);
      return;
    }

    const candidates = this.snapshot.filter((entry) => {
      if (dialogOpen && !entry.inDialog) return false;
      if (typing && !entry.allowInInput && !alwaysOn) return false;
      return true;
    });
    const find = (keys: string) => {
      for (let index = candidates.length - 1; index >= 0; index -= 1) {
        const entry = candidates[index];
        if (entry.keys === keys && (entry.when?.() ?? true)) return entry;
      }
      return undefined;
    };

    const prefix = this.pendingPrefix;
    if (prefix) {
      this.setPrefix(null);
      const match = find(`${prefix} ${combo}`);
      if (match) {
        event.preventDefault();
        match.run(event);
      }
      return;
    }

    const direct = find(combo);
    if (direct) {
      event.preventDefault();
      direct.run(event);
      return;
    }

    if (
      !typing &&
      !dialogOpen &&
      candidates.some(
        (entry) =>
          entry.keys.startsWith(`${combo} `) && (entry.when?.() ?? true),
      )
    ) {
      event.preventDefault();
      this.setPrefix(combo);
    }
  };

  /** Drops a pending prefix and its timer (provider unmount). */
  reset(): void {
    this.setPrefix(null);
  }

  private setPrefix(value: string | null): void {
    clearTimeout(this.prefixTimer);
    this.prefixTimer = undefined;
    if (value) {
      this.prefixTimer = setTimeout(
        () => this.setPrefix(null),
        SEQUENCE_TIMEOUT_MS,
      );
    }
    if (this.pendingPrefix === value) return;
    this.pendingPrefix = value;
    this.prefixListeners.forEach((listener) => listener());
  }

  private changed(): void {
    let id = 0;
    const next: RegisteredHotkey[] = [];
    // Map keeps insertion order, which is registration order.
    for (const set of this.sets.values()) {
      for (const binding of set.bindings) next.push({ ...binding, id: id++ });
    }
    this.snapshot = next;
    this.listeners.forEach((listener) => listener());
  }
}
