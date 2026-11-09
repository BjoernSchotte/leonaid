import { MessageSquare } from "lucide-react";

import type { DeliveryDropResponse } from "@leonaid/api-client";

/** The order's "Hinweis für den Fahrer" (spec §5.1): one quiet line with an icon. */
export function DriverNote({
  className,
  drop,
}: {
  readonly className?: string;
  readonly drop: DeliveryDropResponse;
}) {
  const note = drop.contact?.driverNote;
  if (!note) return null;
  return (
    <span
      className={className ? `tour-note ${className}` : "tour-note"}
      data-testid="driver-note"
    >
      <MessageSquare aria-hidden="true" size={14} />
      <span className="sr-only">Hinweis für den Fahrer: </span>
      <span className="tour-note-text">{note}</span>
    </span>
  );
}
