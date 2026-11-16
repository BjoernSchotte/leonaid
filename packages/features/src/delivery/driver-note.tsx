import { Camera, MessageSquare } from "lucide-react";
import { useState } from "react";

import type { DeliveryDropResponse } from "@leonaid/api-client";

/** About three lines at 360 px; longer notes fold behind "mehr". */
const FOLD_LENGTH = 100;

/**
 * The order's "Hinweis für den Fahrer" (spec §5.1). Rows and the planner get
 * one cut line; `full` (dock, done-stop detail) wraps to three lines and
 * unfolds with "mehr" (ruling 20).
 */
export function DriverNote({
  className,
  drop,
  full = false,
}: {
  readonly className?: string;
  readonly drop: DeliveryDropResponse;
  readonly full?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const note = drop.contact?.driverNote;
  if (!note) return null;
  const foldable = full && note.length > FOLD_LENGTH;
  return (
    <span
      className={["tour-note", full && "is-full", className]
        .filter(Boolean)
        .join(" ")}
      data-testid="driver-note"
      title={full ? undefined : note}
    >
      <MessageSquare aria-hidden="true" size={14} />
      <span className="sr-only">Hinweis für den Fahrer: </span>
      <span
        className={["tour-note-text", foldable && !open && "is-folded"]
          .filter(Boolean)
          .join(" ")}
      >
        {note}
      </span>
      {foldable ? (
        <button
          aria-expanded={open}
          className="tour-note-more"
          onClick={() => setOpen(!open)}
          type="button"
        >
          {open ? "weniger" : "mehr"}
        </button>
      ) : null}
    </span>
  );
}

/**
 * The buyer allowed photos of this delivery to be published (E-068). Shown
 * where the full note is, so the driver knows before taking a picture.
 */
export function PhotoConsentNote({
  drop,
}: {
  readonly drop: DeliveryDropResponse;
}) {
  if (!drop.photosAllowed) return null;
  return (
    <span className="tour-note is-full" data-testid="photo-consent-note">
      <Camera aria-hidden="true" size={14} />
      <span className="tour-note-text">Fotos für Veröffentlichung erlaubt</span>
    </span>
  );
}
