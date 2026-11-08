/*
 * Sign-out with captures still on the device (specs/pwa-offline-queue
 * §12.5): sign-out deletes them, so both apps ask first. The PWA speaks
 * "Du", the admin web app "Sie".
 */
import { Button, Modal } from "@leonaid/ui";

import {
  DeviceStore,
  activeDeviceUser,
  deviceStorageAvailable,
} from "./device-store";

/**
 * Entries of the device's user still in the queue, read from the store
 * (not from a view that may not have loaded yet).
 */
export async function pendingDeviceEntries(): Promise<number> {
  const userId = activeDeviceUser();
  if (!userId || !deviceStorageAvailable()) return 0;
  try {
    const store = await DeviceStore.open(userId);
    try {
      return await store.queueCount();
    } finally {
      store.close();
    }
  } catch {
    return 0;
  }
}

/** Opens the PWA's "Warteschlange" sheet. */
export const OPEN_QUEUE_EVENT = "leonaid:open-queue";

function entries(count: number) {
  return count === 1 ? "1 Eintrag" : `${count} Einträge`;
}

export function SignOutWarning({
  address = "du",
  count,
  online,
  onCancel,
  onSendFirst,
  onSignOut,
  open,
}: {
  /** "du" in the PWA, "Sie" in the admin web app. */
  readonly address?: "du" | "Sie";
  readonly count: number;
  readonly online: boolean;
  readonly onCancel: () => void;
  readonly onSendFirst: () => void;
  readonly onSignOut: () => void;
  readonly open: boolean;
}) {
  const description =
    address === "du"
      ? `Noch ${entries(count)} nicht gesendet. Wenn du dich jetzt abmeldest, ${count === 1 ? "wird er" : "werden sie"} von diesem Gerät gelöscht.`
      : `In der Akquise-App auf diesem Gerät ${count === 1 ? "ist" : "sind"} noch ${entries(count)} nicht gesendet. Wenn Sie sich jetzt abmelden, ${count === 1 ? "wird er" : "werden sie"} von diesem Gerät gelöscht.`;
  return (
    <Modal
      description={description}
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
            {address === "du" ? "Erst senden" : "Zur Akquise-App"}
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
