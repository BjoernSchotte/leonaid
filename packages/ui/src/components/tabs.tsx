import {
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { cn } from "../lib/utils";

export interface TabItem<T extends string = string> {
  readonly id: T;
  readonly label: ReactNode;
  readonly count?: number;
}

export interface TabsProps<T extends string> {
  readonly items: readonly TabItem<T>[];
  readonly value: T;
  readonly onChange: (id: T) => void;
  /** Accessible name of the tab list. */
  readonly label?: string;
  /**
   * Prefix for the tab and panel ids. Set it when a {@link TabPanel} with the
   * same prefix renders the content; only then the tabs point at a panel.
   */
  readonly idPrefix?: string;
  readonly className?: string;
}

export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const tabPanelId = (prefix: string, id: string) =>
  `${prefix}-panel-${id}`;

/**
 * Tab list with a roving tab stop. Arrow keys, Home and End move focus;
 * Enter or Space selects the focused tab.
 */
export function Tabs<T extends string>({
  className,
  idPrefix,
  items,
  label,
  onChange,
  value,
}: TabsProps<T>) {
  const generatedPrefix = useId();
  const prefix = idPrefix ?? generatedPrefix;
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  // The focused tab holds the tab stop while focus is inside the list.
  const [focusedId, setFocusedId] = useState<T | null>(null);
  const stopId =
    focusedId !== null && items.some((item) => item.id === focusedId)
      ? focusedId
      : value;

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = items.length - 1;
    const next =
      event.key === "ArrowRight"
        ? index === last
          ? 0
          : index + 1
        : event.key === "ArrowLeft"
          ? index === 0
            ? last
            : index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : -1;
    if (next < 0) return;
    event.preventDefault();
    refs.current[next]?.focus();
  }

  return (
    <div
      aria-label={label}
      className={cn("tabs", className)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setFocusedId(null);
        }
      }}
      role="tablist"
    >
      {items.map((item, index) => {
        const selected = item.id === value;
        return (
          <button
            aria-controls={idPrefix ? tabPanelId(prefix, item.id) : undefined}
            aria-selected={selected}
            className={cn("tab", selected && "is-active")}
            id={tabId(prefix, item.id)}
            key={item.id}
            onClick={() => onChange(item.id)}
            onFocus={() => setFocusedId(item.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            ref={(element) => {
              refs.current[index] = element;
            }}
            role="tab"
            tabIndex={item.id === stopId ? 0 : -1}
            type="button"
          >
            {item.label}
            {item.count !== undefined ? (
              <span className="tab-count">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export interface TabPanelProps {
  readonly children: ReactNode;
  readonly className?: string;
  /** Same prefix as on {@link Tabs}. */
  readonly idPrefix: string;
  /** Id of the tab that labels this panel. */
  readonly tabId: string;
}

export function TabPanel({
  children,
  className,
  idPrefix,
  tabId: id,
}: TabPanelProps) {
  return (
    <div
      aria-labelledby={tabId(idPrefix, id)}
      className={className}
      id={tabPanelId(idPrefix, id)}
      role="tabpanel"
      tabIndex={0}
    >
      {children}
    </div>
  );
}
