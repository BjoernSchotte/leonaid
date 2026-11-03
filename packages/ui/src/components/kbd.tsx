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

export interface KbdProps {
  /** A binding ("mod+k", "g b") or its steps (["g", "b"]). */
  readonly keys: string | readonly string[];
  readonly subtle?: boolean;
}

export function Kbd({ keys, subtle }: KbdProps) {
  const steps = keyLabels(typeof keys === "string" ? keys : keys.join(" "));
  return (
    <span className={cn("kbd-group", subtle && "is-subtle")} aria-hidden="true">
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
  );
}
