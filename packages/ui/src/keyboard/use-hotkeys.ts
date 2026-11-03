import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type DependencyList,
  type ReactNode,
} from "react";

import {
  HotkeyRegistry,
  type HotkeyBinding,
  type RegisteredHotkey,
} from "./hotkeys";

const HotkeyContext = createContext<HotkeyRegistry | null>(null);

export interface HotkeyProviderProps {
  readonly children?: ReactNode;
  /** For tests and stories; the provider creates its own otherwise. */
  readonly registry?: HotkeyRegistry;
}

/** Mount once at the shell root; listens for keydown on window. */
export function HotkeyProvider({ children, registry }: HotkeyProviderProps) {
  const [ownRegistry] = useState(() => new HotkeyRegistry());
  const active = registry ?? ownRegistry;
  useEffect(() => {
    window.addEventListener("keydown", active.handleKeyDown);
    return () => {
      window.removeEventListener("keydown", active.handleKeyDown);
      active.reset();
    };
  }, [active]);
  return createElement(HotkeyContext.Provider, { value: active }, children);
}

export function useHotkeyRegistry(): HotkeyRegistry {
  const registry = useContext(HotkeyContext);
  if (!registry) {
    throw new Error("Hotkey hooks must be used inside <HotkeyProvider>.");
  }
  return registry;
}

/**
 * Registers bindings while the component is mounted; unmounting removes
 * them. `run` and `when` always call the latest render's functions. The set
 * is re-published when keys, labels or groups change, or when `deps` change.
 */
export function useHotkeys(
  bindings: readonly HotkeyBinding[],
  deps: DependencyList = [],
): void {
  const registry = useHotkeyRegistry();
  const latest = useRef(bindings);
  latest.current = bindings;

  const signature = bindings
    .map((binding) =>
      [
        binding.keys,
        binding.label,
        binding.group,
        binding.zone ?? "",
        binding.hidden ? 1 : 0,
        binding.inDialog ? 1 : 0,
        binding.allowInInput ? 1 : 0,
        binding.when ? 1 : 0,
      ].join("\u0000"),
    )
    .join("\u0001");

  // Stable wrappers so the registry never holds a stale closure.
  const published = useMemo(
    () =>
      latest.current.map((binding, index): HotkeyBinding => {
        const current = () => latest.current[index] ?? binding;
        return {
          ...binding,
          run: (event) => current().run(event),
          when: binding.when ? () => current().when?.() ?? true : undefined,
        };
      }),
    [signature, ...deps],
  );

  // Reserved during render: parents render before children (see reserve()).
  const [order] = useState(() => registry.reserve());
  const handle = useRef<ReturnType<HotkeyRegistry["register"]> | null>(null);
  useEffect(() => {
    const registration = registry.register(published, order);
    handle.current = registration;
    return () => {
      registration.dispose();
      if (handle.current === registration) handle.current = null;
    };
    // Register once per registry; updates keep the set's priority position.
  }, [registry, order]);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    handle.current?.update(published);
  }, [published]);
}

/** Every registered binding the help overlay should list. */
export function useRegisteredHotkeys(): RegisteredHotkey[] {
  const registry = useHotkeyRegistry();
  const all = useSyncExternalStore(
    registry.subscribe,
    () => registry.getAll(),
    () => registry.getAll(),
  );
  return useMemo(() => registry.getVisible(), [registry, all]);
}

/** The pending sequence prefix ("g") or null. */
export function usePendingPrefix(): string | null {
  const registry = useHotkeyRegistry();
  return useSyncExternalStore(
    registry.subscribePrefix,
    registry.getPendingPrefix,
    registry.getPendingPrefix,
  );
}

export interface ShortcutHelpControls {
  readonly open: boolean;
  readonly setOpen: (open: boolean) => void;
  readonly toggle: () => void;
}

/** Open state of the "?" overlay, shared with buttons that open it. */
export function useShortcutHelp(): ShortcutHelpControls {
  const registry = useHotkeyRegistry();
  const open = useSyncExternalStore(
    registry.subscribeHelp,
    registry.isHelpOpen,
    registry.isHelpOpen,
  );
  return useMemo(
    () => ({
      open,
      setOpen: registry.setHelpOpen,
      toggle: () => registry.setHelpOpen(!registry.isHelpOpen()),
    }),
    [open, registry],
  );
}
