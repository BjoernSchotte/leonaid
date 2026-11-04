import { Eye } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/utils";

export interface NextStepProps {
  /** The consequence in plain words, after the bold "Nächster Schritt:". */
  readonly children?: ReactNode;
  /** Exactly one primary action, then optional ghost alternatives. */
  readonly action?: ReactNode;
  /**
   * The viewer may not act: shows the "Nur lesen. …" note with this text
   * instead of the block.
   */
  readonly readOnly?: ReactNode;
  readonly className?: string;
}

/**
 * The "Nächster Schritt" block (DESIGN.md Patterns): a zone-soft box with
 * the next action, shown only when the viewer may act. Read-only viewers
 * get an info note instead.
 */
export function NextStep({
  action,
  children,
  className,
  readOnly,
}: NextStepProps) {
  if (readOnly != null && readOnly !== false) {
    return (
      <div
        className={cn("callout", "next-step-readonly", className)}
        role="note"
      >
        <Eye aria-hidden="true" size={16} />
        <span>
          <strong>Nur lesen.</strong> {readOnly}
        </span>
      </div>
    );
  }
  return (
    <div className={cn("next-step", className)}>
      <p>
        <strong>Nächster Schritt:</strong> {children}
      </p>
      {action ? <div className="next-step-actions">{action}</div> : null}
    </div>
  );
}
