import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export type Tone =
  | "neutral"
  | "ok"
  | "warn"
  | "danger"
  | "info"
  | "accent"
  | "zone";

export interface BadgeProps {
  readonly tone?: Tone;
  readonly icon?: LucideIcon;
  readonly children: ReactNode;
}

/** A secondary fact. The main record status belongs to StatusIcon. */
export function Badge({ tone = "neutral", icon: Glyph, children }: BadgeProps) {
  return (
    <span className={`badge tone-${tone}`}>
      {Glyph ? <Glyph aria-hidden="true" size={12} /> : null}
      {children}
    </span>
  );
}
