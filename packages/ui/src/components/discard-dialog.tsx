import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ConfirmDialog } from "./confirm-dialog";

/** Form of address: "Sie" in the back office, "du" in the PWA. */
export type DiscardAddress = "Sie" | "du";

const copy = {
  Sie: "Ihre Änderungen sind noch nicht gespeichert. Wenn Sie fortfahren, gehen sie verloren.",
  du: "Deine Änderungen sind noch nicht gespeichert. Wenn du fortfährst, gehen sie verloren.",
} as const;

export interface DiscardDialog {
  /** Asks in the app (no native dialog, so it works on iOS). */
  readonly confirmDiscard: () => Promise<boolean>;
  /** Render it once in the page. */
  readonly dialog: ReactNode;
}

/**
 * The shared "Entwurf verwerfen?" question before unsaved work is dropped
 * (closing a pane, leaving edit mode, loading another version). A second
 * ask while one is open gets the same answer.
 */
export function useDiscardDialog(
  address: DiscardAddress = "Sie",
): DiscardDialog {
  const [open, setOpen] = useState(false);
  const pending = useRef<{
    readonly promise: Promise<boolean>;
    readonly resolve: (discard: boolean) => void;
  } | null>(null);
  const settle = useCallback((discard: boolean) => {
    const current = pending.current;
    pending.current = null;
    setOpen(false);
    current?.resolve(discard);
  }, []);
  const confirmDiscard = useCallback(() => {
    if (pending.current) return pending.current.promise;
    let resolve: (discard: boolean) => void = () => {};
    const promise = new Promise<boolean>((done) => {
      resolve = done;
    });
    pending.current = { promise, resolve };
    setOpen(true);
    return promise;
  }, []);
  // Unmounted while asking: nothing is dropped.
  useEffect(() => () => pending.current?.resolve(false), []);
  return {
    confirmDiscard,
    dialog: (
      <ConfirmDialog
        cancelLabel="Weiter bearbeiten"
        confirmLabel="Verwerfen"
        description={copy[address]}
        onConfirm={() => settle(true)}
        onOpenChange={(next) => {
          if (!next) settle(false);
        }}
        open={open}
        title="Entwurf verwerfen?"
        tone="danger"
      />
    ),
  };
}
