import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type SyntheticEvent,
} from "react";

import { cn } from "../lib/utils";

export interface ModalProps {
  readonly open: boolean;
  /** Called for Esc, a backdrop click and a close the browser forces. */
  readonly onClose: () => void;
  readonly title: ReactNode;
  readonly description?: ReactNode;
  readonly children?: ReactNode;
  /** Actions, right-aligned: ghost "Abbrechen" first, then the verb. */
  readonly footer?: ReactNode;
  readonly size?: "sm" | "md" | "lg";
  readonly className?: string;
  readonly role?: "dialog" | "alertdialog";
}

/*
 * Open modals, innermost last. It drives the page scroll lock (a class on
 * <html>, CSP-safe) and tells the toaster where the top layer is: content
 * outside the topmost modal dialog is hidden behind it and inert.
 */
const SCROLL_LOCK_CLASS = "modal-open";
const openSlots: HTMLElement[] = [];
const listeners = new Set<() => void>();

function register(slot: HTMLElement) {
  if (openSlots.includes(slot)) return;
  openSlots.push(slot);
  document.documentElement.classList.add(SCROLL_LOCK_CLASS);
  listeners.forEach((listener) => listener());
}

function unregister(slot: HTMLElement) {
  const index = openSlots.indexOf(slot);
  if (index < 0) return;
  openSlots.splice(index, 1);
  if (openSlots.length === 0) {
    document.documentElement.classList.remove(SCROLL_LOCK_CLASS);
  }
  listeners.forEach((listener) => listener());
}

/** The toast slot of the topmost open modal, or null. */
export function topModalSlot(): HTMLElement | null {
  return openSlots.at(-1) ?? null;
}

export function subscribeModalStack(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React bubbles `cancel`/`close` of nested dialogs and inputs; skip those. */
function isOwn(event: SyntheticEvent) {
  return event.target === event.currentTarget;
}

/**
 * Modal on the native `<dialog>` with `showModal()`: the browser provides the
 * focus trap, the inert background and Esc. Focus returns to the opener.
 */
export function Modal({
  children,
  className,
  description,
  footer,
  onClose,
  open,
  role,
  size = "md",
  title,
}: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const slotRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const returnFocus = useRef<HTMLElement | null>(null);
  const openRef = useRef(open);
  openRef.current = open;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const pointerDownOnBackdrop = useRef(false);
  // Bumped after a forced close, so the effect re-opens a modal the consumer
  // keeps open.
  const [forcedCloses, setForcedCloses] = useState(0);

  // Layout effects: the modal stack (scroll lock, toaster placement) changes
  // in the same commit as the dialog, before the browser paints.
  useLayoutEffect(() => {
    const dialog = ref.current;
    const slot = slotRef.current;
    openRef.current = open;
    if (!dialog || !slot) return;
    if (open) {
      if (dialog.open) return;
      const show = () => {
        if (!openRef.current || dialog.open || !dialog.isConnected) return;
        returnFocus.current ??= document.activeElement as HTMLElement | null;
        dialog.showModal();
        register(slot);
      };
      // A child effect runs before its parent's. Wait for an enclosing
      // dialog that opens in the same commit, so the child ends on top.
      const parent = dialog.parentElement?.closest("dialog");
      if (parent && !parent.open) queueMicrotask(show);
      else show();
      return;
    }
    if (dialog.open) dialog.close();
    unregister(slot);
    restoreFocus(returnFocus);
  }, [open, forcedCloses]);

  // An open modal that unmounts (conditional rendering) still hands focus back.
  useLayoutEffect(() => {
    const dialog = ref.current;
    const slot = slotRef.current;
    return () => {
      // Not a user close: do not report it through onClose.
      openRef.current = false;
      if (dialog?.open) dialog.close();
      if (slot) unregister(slot);
      restoreFocus(returnFocus);
    };
  }, []);

  return (
    <dialog
      aria-describedby={description ? descriptionId : undefined}
      aria-labelledby={titleId}
      className={cn("modal", `modal-${size}`, className)}
      onCancel={(event) => {
        if (!isOwn(event)) return;
        event.preventDefault();
        onCloseRef.current();
      }}
      onClick={(event) => {
        // Only a press and release both on the backdrop close it, not a text
        // selection that ends there.
        const onBackdrop =
          pointerDownOnBackdrop.current && event.target === ref.current;
        pointerDownOnBackdrop.current = false;
        if (onBackdrop) onCloseRef.current();
      }}
      onClose={(event) => {
        if (!isOwn(event) || !openRef.current) return;
        // Chromium closes without a cancelable `cancel` on a repeated Esc.
        // Report it; the effect then closes for good or opens again.
        onCloseRef.current();
        setForcedCloses((count) => count + 1);
      }}
      onPointerDown={(event) => {
        pointerDownOnBackdrop.current = event.target === ref.current;
      }}
      ref={ref}
      role={role}
    >
      {open ? (
        <div className="modal-body">
          <header className="modal-header">
            <h2 id={titleId}>{title}</h2>
            {description ? (
              <p className="modal-description" id={descriptionId}>
                {description}
              </p>
            ) : null}
          </header>
          {children != null && children !== false ? (
            <div className="modal-content">{children}</div>
          ) : null}
          {footer ? <footer className="modal-footer">{footer}</footer> : null}
        </div>
      ) : null}
      {/* The toaster renders here while this is the topmost modal. */}
      <div className="modal-toast-slot" ref={slotRef} />
    </dialog>
  );
}

function restoreFocus(target: { current: HTMLElement | null }) {
  const element = target.current;
  target.current = null;
  if (element?.isConnected) element.focus();
}
