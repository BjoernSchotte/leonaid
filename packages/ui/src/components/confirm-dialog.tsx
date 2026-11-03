import { Button } from "./button";
import { Modal } from "./modal";

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

/** A small alert dialog that names the consequence before a critical change. */
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
    <Modal
      description={description}
      footer={
        <>
          <Button
            disabled={pending}
            onClick={() => onOpenChange(false)}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button loading={pending} onClick={onConfirm} variant={tone}>
            {pending ? "Wird gespeichert …" : confirmLabel}
          </Button>
        </>
      }
      onClose={() => onOpenChange(false)}
      open={open}
      role="alertdialog"
      size="sm"
      title={title}
    />
  );
}
