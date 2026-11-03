/*
 * Status is carried by SHAPE first, colour second (readable without colour):
 *   draft     dashed ring
 *   open      empty ring
 *   review    ring with centre dot
 *   progress  half-filled ring
 *   done      filled disc with check
 *   alert     ring with exclamation (overdue, failed)
 *   cancelled ring struck through
 */
export type StatusShape =
  | "draft"
  | "open"
  | "review"
  | "progress"
  | "done"
  | "alert"
  | "cancelled";

const toneForShape: Record<StatusShape, string> = {
  draft: "neutral",
  open: "info",
  review: "warn",
  progress: "warn",
  done: "ok",
  alert: "danger",
  cancelled: "neutral",
};

function ShapeDrawing({ shape }: { readonly shape: StatusShape }) {
  switch (shape) {
    case "draft":
      return (
        <circle
          cx="8"
          cy="8"
          fill="none"
          r="6"
          stroke="currentColor"
          strokeDasharray="2.4 2.2"
          strokeWidth="1.6"
        />
      );
    case "open":
      return (
        <circle
          cx="8"
          cy="8"
          fill="none"
          r="6"
          stroke="currentColor"
          strokeWidth="1.6"
        />
      );
    case "review":
      return (
        <>
          <circle
            cx="8"
            cy="8"
            fill="none"
            r="6"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <circle cx="8" cy="8" fill="currentColor" r="2.2" />
        </>
      );
    case "progress":
      return (
        <>
          <circle
            cx="8"
            cy="8"
            fill="none"
            r="6"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <path d="M8 3.2 A4.8 4.8 0 0 1 8 12.8 Z" fill="currentColor" />
        </>
      );
    case "done":
      return (
        <>
          <circle cx="8" cy="8" fill="currentColor" r="7" />
          <path
            d="M5 8.2 7.1 10.2 11 6"
            fill="none"
            stroke="var(--surface)"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.8"
          />
        </>
      );
    case "alert":
      return (
        <>
          <circle
            cx="8"
            cy="8"
            fill="none"
            r="6"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <path
            d="M8 4.8v3.8"
            stroke="currentColor"
            strokeLinecap="round"
            strokeWidth="1.8"
          />
          <circle cx="8" cy="11" fill="currentColor" r="1" />
        </>
      );
    case "cancelled":
      return (
        <>
          <circle
            cx="8"
            cy="8"
            fill="none"
            r="6"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <path
            d="M3.8 12.2 12.2 3.8"
            stroke="currentColor"
            strokeLinecap="round"
            strokeWidth="1.6"
          />
        </>
      );
  }
}

function StatusSvg({
  shape,
  size,
  label,
}: {
  readonly shape: StatusShape;
  readonly size: number;
  readonly label?: string;
}) {
  return (
    <svg
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={`status-icon tone-${toneForShape[shape]}`}
      height={size}
      role={label ? "img" : undefined}
      viewBox="0 0 16 16"
      width={size}
    >
      <ShapeDrawing shape={shape} />
    </svg>
  );
}

export interface StatusIconProps {
  readonly status: StatusShape;
  /** The status word for assistive tech, e.g. "Überfällig". */
  readonly label: string;
  readonly size?: number;
}

/** Shape-coded record status, always exposed as a labelled image. */
export function StatusIcon({ status, label, size = 14 }: StatusIconProps) {
  return <StatusSvg label={label} shape={status} size={size} />;
}

/** The only mapping from domain status to shape. Extend it here. */
export const statusShape: Readonly<Record<string, StatusShape>> = {
  // orders
  Entwurf: "draft",
  Prüfbereit: "review",
  Eingegangen: "open",
  Bestätigt: "progress",
  Berechnet: "progress",
  Geliefert: "done",
  Storniert: "cancelled",
  // invoices
  Offen: "open",
  Überfällig: "alert",
  Bezahlt: "done",
  // tasks
  "In Arbeit": "progress",
  Erledigt: "done",
  // inbox
  Neu: "open",
  "In Bearbeitung": "progress",
  Abgeschlossen: "done",
  // surveys / campaigns / pages
  Live: "progress",
  Geschlossen: "done",
  Aktiv: "progress",
  Geplant: "open",
  Archiviert: "done",
  Veröffentlicht: "done",
  Geändert: "review",
  // pipeline
  Angesprochen: "open",
  Interessiert: "review",
  Zugesagt: "done",
  Abgesagt: "cancelled",
  // services/jobs
  Betriebsbereit: "done",
  Eingeschränkt: "alert",
  Fehlgeschlagen: "alert",
  Wartet: "progress",
};

/** Shape plus word; the word carries the meaning, so the shape is decorative. */
export function StatusLabel({ status }: { readonly status: string }) {
  const shape = statusShape[status] ?? "open";
  return (
    <span className={`status-label is-${shape}`}>
      <StatusSvg shape={shape} size={14} />
      <span>{status}</span>
    </span>
  );
}
