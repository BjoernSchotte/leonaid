import { AlertDialog } from "@base-ui/react/alert-dialog";

import { Button } from "./button";

export interface ConfirmDialogProps {
  readonly confirmLabel: string;
  readonly description: string;
  readonly onConfirm: () => void;
  readonly open: boolean;
  readonly pending?: boolean;
  readonly title: string;
  readonly tone?: "danger" | "primary";
  readonly onOpenChange: (open: boolean) => void;
}

export function ConfirmDialog({
  confirmLabel,
  description,
  onConfirm,
  onOpenChange,
  open,
  pending = false,
  title,
  tone = "primary",
}: ConfirmDialogProps) {
  return (
    <AlertDialog.Root onOpenChange={onOpenChange} open={open}>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="ui-dialog-backdrop" />
        <AlertDialog.Viewport className="ui-dialog-viewport">
          <AlertDialog.Popup className="ui-dialog">
            <AlertDialog.Title className="ui-dialog__title">
              {title}
            </AlertDialog.Title>
            <AlertDialog.Description className="ui-dialog__description">
              {description}
            </AlertDialog.Description>
            <div className="ui-dialog__actions">
              <AlertDialog.Close
                className="ui-button ui-button--secondary"
                disabled={pending}
              >
                Abbrechen
              </AlertDialog.Close>
              <Button disabled={pending} onClick={onConfirm} variant={tone}>
                {pending ? "Wird gespeichert …" : confirmLabel}
              </Button>
            </div>
          </AlertDialog.Popup>
        </AlertDialog.Viewport>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
