import { createContext, useContext, useEffect } from "react";

/**
 * Pages with unsaved work register here, so the shell owning in-app
 * navigation (the PWA's MobileShell) asks one in-app question before its
 * tabs, digit keys or sheet links leave the page. iOS Safari shows no
 * beforeunload dialog, so the in-app question is the one that works there.
 */
export class LeaveGuardRegistry {
  private readonly dirty = new Set<object>();
  /** Set once the user confirmed leaving: page guards stay silent. */
  leaving = false;

  register(token: object): void {
    this.dirty.add(token);
  }

  unregister(token: object): void {
    this.dirty.delete(token);
  }

  hasDirtyPages(): boolean {
    return this.dirty.size > 0;
  }
}

export const LeaveGuardContext = createContext<LeaveGuardRegistry | null>(null);

/**
 * Marks the page as having unsaved work while `dirty` is true.
 * - Inside a shell with a registry, shell navigation asks first.
 * - Reload, close and other navigation keep the browser's beforeunload
 *   dialog, except after the user confirmed leaving in the shell.
 * Keep beforeunload listeners free of side effects; use `pagehide` for
 * unload work.
 */
export function useLeaveGuard(dirty: boolean): void {
  const registry = useContext(LeaveGuardContext);
  useEffect(() => {
    if (!dirty) return;
    const token = {};
    registry?.register(token);
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (registry?.leaving) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      registry?.unregister(token);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [dirty, registry]);
}
