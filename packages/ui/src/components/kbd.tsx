import { cn } from "../lib/utils";

/** True on macOS and iOS, where the modifier key is ⌘ instead of Strg. */
export function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
}

/**
 * Splits a binding into steps and keycap labels: "mod+k" → [["Strg", "K"]],
 * "g b" → [["G"], ["B"]].
 */
export function keyLabels(keys: string): string[][] {
  const mac = isMacPlatform();
  return keys
    .split(" ")
    .filter(Boolean)
    .map((step) =>
      step.split("+").map((part) => {
        switch (part) {
          case "mod":
            return mac ? "⌘" : "Strg";
          case "shift":
            return "⇧";
          case "alt":
            return mac ? "⌥" : "Alt";
          case "escape":
            return "Esc";
          case "enter":
            return "↵";
          case "arrowup":
            return "↑";
          case "arrowdown":
            return "↓";
          case "space":
            return "Leertaste";
          default:
            return part.length === 1 ? part.toUpperCase() : part;
        }
      }),
    );
}

const spokenKeys: Readonly<Record<string, string>> = {
  shift: "Umschalt",
  escape: "Escape",
  enter: "Eingabe",
  arrowup: "Pfeil nach oben",
  arrowdown: "Pfeil nach unten",
  space: "Leertaste",
  "?": "Fragezeichen",
  "/": "Schrägstrich",
};

/** The binding as words for assistive tech: "mod+k" → "Strg plus K". */
export function keySpeech(keys: string): string {
  const mac = isMacPlatform();
  return keys
    .split(" ")
    .filter(Boolean)
    .map((step) =>
      step
        .split("+")
        .map((part) => {
          if (part === "mod") return mac ? "Befehl" : "Strg";
          if (part === "alt") return mac ? "Wahl" : "Alt";
          return (
            spokenKeys[part] ?? (part.length === 1 ? part.toUpperCase() : part)
          );
        })
        .join(" plus "),
    )
    .join(" dann ");
}

export interface KbdProps {
  /** A binding ("mod+k", "g b") or its steps (["g", "b"]). */
  readonly keys: string | readonly string[];
  readonly subtle?: boolean;
  /**
   * Adds the binding as visually hidden words ("Strg plus K"). Turn it off
   * where a control's label already names the action (Button shortcuts).
   */
  readonly announce?: boolean;
}

export function Kbd({ keys, subtle, announce = true }: KbdProps) {
  const binding = typeof keys === "string" ? keys : keys.join(" ");
  const steps = keyLabels(binding);
  return (
    <>
      <span
        aria-hidden="true"
        className={cn("kbd-group", subtle && "is-subtle")}
      >
        {steps.map((parts, index) => (
          <span className="kbd-step" key={index}>
            {index > 0 ? <span className="kbd-then">dann</span> : null}
            {parts.map((part) => (
              <kbd className="kbd" key={part}>
                {part}
              </kbd>
            ))}
          </span>
        ))}
      </span>
      {announce ? <span className="kbd-text">{keySpeech(binding)}</span> : null}
    </>
  );
}
