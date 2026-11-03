import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";

/** A command a page or the shell contributes to the palette. */
export interface PaletteCommand {
  readonly id: string;
  readonly label: string;
  /** Palette section; page commands show as "Auf dieser Seite · <group>". */
  readonly group: string;
  readonly icon?: LucideIcon;
  /** The binding shown as keycaps, e.g. "c" or "shift+u". */
  readonly keys?: string;
  /** Extra search terms. */
  readonly keywords?: readonly string[];
  readonly run: () => void;
}

type Listener = () => void;

class Store<T> {
  private readonly listeners = new Set<Listener>();
  constructor(private value: T) {}
  readonly get = (): T => this.value;
  readonly set = (next: T): void => {
    if (Object.is(next, this.value)) return;
    this.value = next;
    for (const listener of [...this.listeners]) listener();
  };
  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

// One palette per document: the shell mounts exactly one CommandPalette.
const openStore = new Store(false);

interface CommandEntry {
  readonly owner: number;
  readonly commands: readonly PaletteCommand[];
}

const commandStore = new Store<readonly CommandEntry[]>([]);
let nextOwner = 0;

export interface CommandPaletteControls {
  readonly open: boolean;
  readonly setOpen: (open: boolean) => void;
  readonly toggle: () => void;
}

/** Open state of the palette, shared with buttons that open it. */
export function useCommandPalette(): CommandPaletteControls {
  const open = useSyncExternalStore(
    openStore.subscribe,
    openStore.get,
    openStore.get,
  );
  return useMemo(
    () => ({
      open,
      setOpen: openStore.set,
      toggle: () => openStore.set(!openStore.get()),
    }),
    [open],
  );
}

/**
 * Contributes page commands while the calling component is mounted. `run`
 * always calls the latest render's function; the list is re-published when
 * ids, labels, groups or keys change.
 */
export function useContextCommands(commands: readonly PaletteCommand[]): void {
  const latest = useRef(commands);
  latest.current = commands;
  const signature = commands
    .map((command) =>
      [
        command.id,
        command.label,
        command.group,
        command.keys ?? "",
        (command.keywords ?? []).join(" "),
      ].join("\u0000"),
    )
    .join("\u0001");
  useEffect(() => {
    nextOwner += 1;
    const owner = nextOwner;
    const published = latest.current.map(
      (command, index): PaletteCommand => ({
        ...command,
        run: () => (latest.current[index] ?? command).run(),
      }),
    );
    commandStore.set([...commandStore.get(), { owner, commands: published }]);
    return () => {
      commandStore.set(
        commandStore.get().filter((entry) => entry.owner !== owner),
      );
    };
  }, [signature]);
}

/** Every page command currently mounted, in mount order. */
export function useRegisteredContextCommands(): readonly PaletteCommand[] {
  const entries = useSyncExternalStore(
    commandStore.subscribe,
    commandStore.get,
    commandStore.get,
  );
  return useMemo(() => entries.flatMap((entry) => entry.commands), [entries]);
}

/** Test helper: back to a closed palette without page commands. */
export function resetCommandPaletteState(): void {
  openStore.set(false);
  commandStore.set([]);
}
