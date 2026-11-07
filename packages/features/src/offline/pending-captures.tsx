/*
 * Captures of one sponsor still on the device, next to where they appear
 * (specs/pwa-offline-queue §12.3): text plus shape, never colour alone.
 */
import { StatusIcon } from "@leonaid/ui";

import { formatDateTime } from "../shared/dates";
import { entryTitle, queueStateLabel, queueStateShape } from "./labels";
import { useQueueSnapshot } from "./runtime";

export function PendingCaptures({
  partyId,
  partyKind,
}: {
  readonly partyId: string;
  readonly partyKind: "company" | "person";
}) {
  const snapshot = useQueueSnapshot();
  const pending = snapshot.entries.filter(
    (entry) => entry.party.id === partyId && entry.party.kind === partyKind,
  );
  if (!pending.length) return null;
  return (
    <section aria-labelledby="pending-title" data-testid="pending-captures">
      <h2 className="pwa-h2" id="pending-title">
        Noch nicht gesendet
      </h2>
      <ul className="pwa-queue">
        {pending.map((entry) => (
          <li
            className="pwa-queue-entry"
            data-state={entry.state}
            data-testid="pending-capture"
            key={entry.entryId}
          >
            <span className="pwa-queue-title">{entryTitle(entry)}</span>
            <span className="pwa-queue-meta small muted">
              Erfasst am {formatDateTime(entry.capturedAt)}
            </span>
            <span className="pwa-queue-state">
              <StatusIcon
                label=""
                size={16}
                status={queueStateShape[entry.state]}
              />
              {queueStateLabel[entry.state]}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
