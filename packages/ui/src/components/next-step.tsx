import { Eye } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/utils";
import { Icon } from "./icon";

export interface NextStepProps {
  /** Bold lead; default "Nächster Schritt:". */
  readonly lead?: ReactNode;
  /** The consequence in plain words, after the lead. */
  readonly consequence: ReactNode;
  /** Exactly one primary action (a `Button variant="primary"` or link). */
  readonly action: ReactNode;
  /** Optional ghost alternatives after the primary action. */
  readonly alternatives?: ReactNode;
  readonly className?: string;
  readonly "data-testid"?: string;
}

/**
 * The "Nächster Schritt" block (DESIGN.md Patterns): zone-soft box with the
 * zone hairline, the consequence and exactly one primary action. Render it
 * only when the viewer may act; read-only roles get {@link ReadOnlyNotice}.
 */
export function NextStep({
  action,
  alternatives,
  className,
  consequence,
  lead = "Nächster Schritt:",
  "data-testid": testId,
}: NextStepProps) {
  return (
    <div className={cn("next-step", className)} data-testid={testId}>
      <p>
        <strong>{lead}</strong> {consequence}
      </p>
      <div className="next-step-actions">
        {action}
        {alternatives}
      </div>
    </div>
  );
}

/** Info callout for read-only roles: "Nur lesen." and what the role sees. */
export function ReadOnlyNotice({
  children,
  className,
  "data-testid": testId,
}: {
  readonly children: ReactNode;
  readonly className?: string;
  readonly "data-testid"?: string;
}) {
  return (
    <div className={cn("callout", className)} data-testid={testId} role="note">
      <Icon icon={Eye} size={16} />
      <span>
        <strong>Nur lesen.</strong> {children}
      </span>
    </div>
  );
}
