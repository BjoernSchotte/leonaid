import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Slots a page may fill in the PWA app bar: `sub` replaces the role line
 * under the campaign name, `end` sits before the network glyph. The shell
 * owns the nodes; pages render into them through `PageBarPortal`.
 */
export interface PageBarSlots {
  readonly sub: HTMLElement | null;
  readonly end: HTMLElement | null;
}

export const PageBarContext = createContext<PageBarSlots | null>(null);

/** The app bar slots, or null outside the mobile shell (tests, web). */
export function usePageBar(): PageBarSlots | null {
  return useContext(PageBarContext);
}

/** Renders `children` into one app bar slot; nothing while it is missing. */
export function PageBarPortal({
  children,
  slot,
}: {
  readonly children: ReactNode;
  readonly slot: keyof PageBarSlots;
}) {
  const node = usePageBar()?.[slot];
  return node ? createPortal(children, node) : null;
}
