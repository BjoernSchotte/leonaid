import { useEffect, useId, useRef, type ReactNode } from "react";

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
  const titleId = useId();
  const descriptionId = useId();
  const returnFocus = useRef<HTMLElement | null>(null);
  const openRef = useRef(open);
  openRef.current = open;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    openRef.current = open;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) {
        returnFocus.current = document.activeElement as HTMLElement | null;
        dialog.showModal();
      }
      return;
    }
    if (dialog.open) dialog.close();
    restoreFocus(returnFocus);
  }, [open]);

  // An open modal that unmounts (conditional rendering) still hands focus back.
  useEffect(() => {
    const dialog = ref.current;
    return () => {
      // Not a user close: do not report it through onClose.
      openRef.current = false;
      if (dialog?.open) dialog.close();
      restoreFocus(returnFocus);
    };
  }, []);

  return (
    <dialog
      aria-describedby={description ? descriptionId : undefined}
      aria-labelledby={titleId}
      className={cn("modal", `modal-${size}`, className)}
      onCancel={(event) => {
        event.preventDefault();
        onCloseRef.current();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onCloseRef.current();
      }}
      onClose={() => {
        // Chromium closes without a cancelable `cancel` on a repeated Esc.
        if (openRef.current) {
          restoreFocus(returnFocus);
          onCloseRef.current();
        }
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
    </dialog>
  );
}

function restoreFocus(target: { current: HTMLElement | null }) {
  const element = target.current;
  target.current = null;
  if (element?.isConnected) element.focus();
}
