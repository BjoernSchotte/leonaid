import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

export interface PopoverProps {
  /** The trigger the layer is anchored to; focus returns to it on close. */
  readonly anchor: RefObject<HTMLElement | null>;
  readonly open: boolean;
  readonly onClose: () => void;
  readonly children: ReactNode;
  /** Accessible name of the layer (it is a non-modal dialog). */
  readonly label: string;
  readonly align?: "start" | "end";
}

const GAP = 6;
const EDGE = 8;
const FOCUSABLE =
  "input, textarea, select, button, [tabindex]:not([tabindex='-1'])";

/**
 * Floating layer anchored to a trigger. Rendered in a portal with
 * position: fixed, so it escapes overflow containers. The position is set
 * through CSSOM custom properties, never a style attribute (strict CSP).
 * Closes on Escape and on a pointer press outside; focus returns to the
 * trigger.
 */
export function Popover({
  anchor,
  open,
  onClose,
  children,
  label,
  align = "start",
}: PopoverProps) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open) return;
    const timers: number[] = [];
    const place = () => {
      const trigger = anchor.current;
      const layer = ref.current;
      if (!trigger || !layer) return;
      const rect = trigger.getBoundingClientRect();
      const width = layer.offsetWidth;
      const height = layer.offsetHeight;
      let x = align === "end" ? rect.right - width : rect.left;
      x = Math.max(EDGE, Math.min(x, window.innerWidth - width - EDGE));
      let y = rect.bottom + GAP;
      if (y + height > window.innerHeight - EDGE) {
        y = Math.max(EDGE, rect.top - height - GAP);
      }
      layer.style.setProperty("--pop-x", `${Math.round(x)}px`);
      layer.style.setProperty("--pop-y", `${Math.round(y)}px`);
      layer.classList.add("is-placed");
    };
    // autoFocus fails while the layer is still unplaced; focus explicitly.
    const focusFirst = () => {
      const layer = ref.current;
      if (!layer?.isConnected || layer.contains(document.activeElement)) {
        return;
      }
      layer.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    };
    place();
    focusFirst();
    // Chromium can drop a focus() issued while the opening keystroke is
    // still being dispatched; retry briefly until focus is inside.
    for (const delay of [0, 30, 90]) {
      timers.push(window.setTimeout(focusFirst, delay));
    }
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      for (const timer of timers) window.clearTimeout(timer);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchor, align]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (ref.current?.contains(target) || anchor.current?.contains(target)) {
        return;
      }
      onClose();
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open, onClose, anchor]);

  // Return focus to the trigger when closing.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) anchor.current?.focus();
    wasOpen.current = open;
  }, [open, anchor]);

  if (!open) return null;
  return createPortal(
    <div
      aria-label={label}
      className="popover"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          event.preventDefault();
          onClose();
        }
      }}
      ref={ref}
      role="dialog"
    >
      {children}
    </div>,
    document.body,
  );
}
