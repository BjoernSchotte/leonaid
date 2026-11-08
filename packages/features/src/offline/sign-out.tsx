/*
 * Sign-out with captures still on the device (specs/pwa-offline-queue
 * §12.5): sign-out deletes them, so both apps ask first. The PWA speaks
 * "Du", the admin web app "Sie".
 */
import { Button, Modal } from "@leonaid/ui";

import {
  DeviceStore,
  activeDeviceUser,
  databaseName,
  deviceStorageAvailable,
} from "./device-store";

/**
 * Entries still in the queue of every user sign-out deletes (the signed-in
 * user and the device's active user, as forgetDevice), read from the store,
 * not from a view that may not have loaded yet. `null`: the store could not
 * be read; the caller asks anyway (fails closed).
 */
export async function pendingDeviceEntries(
  userId: string | null,
): Promise<number | null> {
  if (!deviceStorageAvailable()) return 0;
  const users = new Set(
    [userId, activeDeviceUser()].filter((value): value is string =>
      Boolean(value),
    ),
  );
  if (!users.size) return 0;
  try {
    // A user without a database has nothing queued; opening would create one.
    const existing =
      typeof indexedDB.databases === "function"
        ? new Set((await indexedDB.databases()).map((item) => item.name))
        : null;
    let total = 0;
    for (const user of users) {
      if (existing && !existing.has(databaseName(user))) continue;
      const store = await DeviceStore.open(user);
      try {
        total += await store.queueCount();
      } finally {
        store.close();
      }
    }
    return total;
  } catch {
    return null;
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
  /** `null`: the device's queue could not be read. */
  readonly count: number | null;
  readonly online: boolean;
  readonly onCancel: () => void;
  readonly onSendFirst: () => void;
  readonly onSignOut: () => void;
  readonly open: boolean;
}) {
  const description =
    count === null
      ? address === "du"
        ? "LeonAid kann gerade nicht prüfen, ob auf diesem Gerät noch Einträge warten. Wenn du dich jetzt abmeldest, wird alles, was noch wartet, von diesem Gerät gelöscht."
        : "LeonAid kann gerade nicht prüfen, ob in der Akquise-App auf diesem Gerät noch Einträge warten. Wenn Sie sich jetzt abmelden, wird alles, was noch wartet, von diesem Gerät gelöscht."
      : address === "du"
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
