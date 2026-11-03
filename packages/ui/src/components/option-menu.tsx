import { Command } from "cmdk";
import { Check } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Icon } from "./icon";
import { Kbd } from "./kbd";

export interface OptionMenuOption<T extends string | number> {
  readonly value: T;
  readonly label: string;
  readonly icon?: ReactNode;
  readonly hint?: string;
  /** Extra search terms that match this option. */
  readonly keywords?: readonly string[];
}

export interface OptionMenuProps<T extends string | number> {
  readonly options: readonly OptionMenuOption<T>[];
  /** The current value; an array when several values can be chosen. */
  readonly value: T | readonly T[];
  readonly onSelect: (value: T) => void;
  /** Placeholder and accessible name of the search input. */
  readonly placeholder: string;
  /** Toggle several values; hides the number-key hints (keys still work). */
  readonly multiple?: boolean;
}

/**
 * Searchable option menu (cmdk) for filter chips and inline property edits.
 * Render it inside a Popover; never inside Command.Dialog, whose scroll lock
 * injects a <style> element that the strict CSP blocks.
 * Number keys 1–9 pick an option directly while the search is empty.
 */
export function OptionMenu<T extends string | number>({
  options,
  value,
  onSelect,
  placeholder,
  multiple,
}: OptionMenuProps<T>) {
  const [query, setQuery] = useState("");
  const selected: readonly T[] = Array.isArray(value)
    ? (value as readonly T[])
    : [value as T];
  return (
    <Command
      className="menu"
      label={placeholder}
      loop
      onKeyDown={(event) => {
        if (query || event.ctrlKey || event.metaKey || event.altKey) return;
        if (!/^[1-9]$/.test(event.key)) return;
        const option = options[Number(event.key) - 1];
        if (!option) return;
        event.preventDefault();
        onSelect(option.value);
      }}
    >
      <Command.Input
        autoFocus
        className="menu-input"
        onValueChange={setQuery}
        placeholder={placeholder}
        value={query}
      />
      <Command.List
        aria-multiselectable={multiple || undefined}
        className="menu-list"
        label="Optionen"
      >
        <Command.Empty className="menu-empty">Nichts gefunden</Command.Empty>
        {options.map((option, index) => {
          const isSelected = selected.includes(option.value);
          const numberKey = index < 9 ? String(index + 1) : null;
          return (
            <Command.Item
              aria-checked={isSelected}
              aria-keyshortcuts={numberKey ?? undefined}
              className="menu-item"
              key={String(option.value)}
              keywords={option.keywords ? [...option.keywords] : undefined}
              onSelect={() => onSelect(option.value)}
              value={`${option.label} ${String(option.value)}`}
            >
              <span aria-hidden="true" className="menu-check">
                {isSelected ? <Icon icon={Check} size={14} /> : null}
              </span>
              {option.icon ? (
                <span aria-hidden="true" className="menu-icon">
                  {option.icon}
                </span>
              ) : null}
              <span className="menu-label">{option.label}</span>
              {option.hint ? (
                <span className="menu-hint">{option.hint}</span>
              ) : null}
              {numberKey && !multiple ? (
                <Kbd announce={false} keys={numberKey} subtle />
              ) : null}
            </Command.Item>
          );
        })}
      </Command.List>
    </Command>
  );
}
