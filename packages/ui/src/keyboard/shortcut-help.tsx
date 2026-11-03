import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { IconButton } from "../components/button";
import { Kbd } from "../components/kbd";
import type { RegisteredHotkey } from "./hotkeys";
import {
  useHotkeys,
  useRegisteredHotkeys,
  useShortcutHelp,
} from "./use-hotkeys";

/** Group of the "g …" navigation bindings, listed with zone dots. */
export const GO_TO_GROUP = "Gehe zu";

export interface ShortcutHelpProps {
  readonly title?: string;
  /** Admin uses "Sie" (default); the PWA passes its "Du" wording. */
  readonly footnote?: string;
}

const DEFAULT_FOOTNOTE =
  "Kürzel wirken nicht, während Sie in ein Feld schreiben. Esc verlässt jedes Feld und jeden Dialog.";

function groupBindings(bindings: readonly RegisteredHotkey[]) {
  const groups = new Map<string, RegisteredHotkey[]>();
  const goTo: RegisteredHotkey[] = [];
  for (const binding of bindings) {
    if (binding.group === GO_TO_GROUP) {
      goTo.push(binding);
      continue;
    }
    const items = groups.get(binding.group);
    if (items) items.push(binding);
    else groups.set(binding.group, [binding]);
  }
  return { groups: [...groups.entries()], goTo };
}

/**
 * "?" overlay listing every binding registered on the current screen,
 * grouped as registered, plus the "Gehe zu" legend. Mount once inside
 * HotkeyProvider.
 */
export function ShortcutHelp({
  title = "Tastenkürzel",
  footnote = DEFAULT_FOOTNOTE,
}: ShortcutHelpProps) {
  const { open, setOpen, toggle } = useShortcutHelp();
  const bindings = useRegisteredHotkeys();
  const ref = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useHotkeys([
    {
      keys: "?",
      label: "Tastenkürzel anzeigen",
      group: "Allgemein",
      inDialog: true,
      // Only toggles from inside a dialog when that dialog is this overlay.
      when: () => !isOtherDialogOpen(ref.current),
      run: toggle,
    },
  ]);

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
      returnFocus.current?.focus();
      returnFocus.current = null;
    }
  }, [open]);

  const { groups, goTo } = groupBindings(bindings);

  return (
    <dialog
      ref={ref}
      aria-labelledby="shortcut-help-title"
      className="help-dialog"
      onCancel={(event) => {
        event.preventDefault();
        setOpen(false);
      }}
      onClick={(event) => {
        if (event.target === ref.current) setOpen(false);
      }}
    >
      {open ? (
        <div className="help-body">
          <header className="help-header">
            <h2 id="shortcut-help-title">{title}</h2>
            <IconButton
              icon={X}
              label="Schließen"
              onClick={() => setOpen(false)}
            />
          </header>
          <div className="help-grid">
            {groups.map(([group, items]) => (
              <section className="help-section" key={group}>
                <h3>{group}</h3>
                <ul>
                  {items.map((item) => (
                    <li key={item.keys}>
                      <span>{item.label}</span>
                      <Kbd keys={item.keys} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            {goTo.length > 0 ? (
              <section className="help-section">
                <h3>{GO_TO_GROUP}</h3>
                <ul>
                  {goTo.map((item) => (
                    <li data-zone={item.zone} key={item.keys}>
                      <span className="help-zone">
                        {item.zone ? (
                          <span aria-hidden="true" className="zone-dot" />
                        ) : null}
                        {item.label}
                      </span>
                      <Kbd keys={item.keys} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
          <p className="help-foot">{footnote}</p>
        </div>
      ) : null}
    </dialog>
  );
}

function isOtherDialogOpen(own: HTMLDialogElement | null): boolean {
  return [...document.querySelectorAll("dialog[open]")].some(
    (dialog) => dialog !== own,
  );
}
