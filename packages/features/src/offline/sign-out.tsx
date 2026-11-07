/*
 * Sign-out with captures still on the device (specs/pwa-offline-queue
 * §12.5): sign-out deletes them, so the PWA asks first.
 */
import { Button, Modal } from "@leonaid/ui";

export function SignOutWarning({
  count,
  online,
  onCancel,
  onSendFirst,
  onSignOut,
  open,
}: {
  readonly count: number;
  readonly online: boolean;
  readonly onCancel: () => void;
  readonly onSendFirst: () => void;
  readonly onSignOut: () => void;
  readonly open: boolean;
}) {
  const entries = count === 1 ? "1 Eintrag" : `${count} Einträge`;
  return (
    <Modal
      description={`Noch ${entries} nicht gesendet. Wenn du dich jetzt abmeldest, ${count === 1 ? "wird er" : "werden sie"} von diesem Gerät gelöscht.`}
      footer={
        <>
          <Button onClick={onCancel} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="sign-out-anyway"
            onClick={onSignOut}
            variant="danger"
          >
            Trotzdem abmelden
          </Button>
          <Button
            data-testid="sign-out-send-first"
            disabled={!online}
            onClick={onSendFirst}
            variant="primary"
          >
            Erst senden
          </Button>
        </>
      }
      onClose={onCancel}
      open={open}
      role="alertdialog"
      title="Abmelden?"
    />
  );
}
