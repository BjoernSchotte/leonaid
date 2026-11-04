import type { LucideIcon } from "lucide-react";

export type IconSize = 12 | 14 | 16 | 18 | 20;

export interface IconProps {
  readonly icon: LucideIcon;
  readonly size?: IconSize;
  /** Makes the icon a labelled image; without it the icon is decorative. */
  readonly label?: string;
  readonly className?: string;
}

/** The one adapter between product code and Lucide. */
export function Icon({ icon: Glyph, size = 16, label, className }: IconProps) {
  return label ? (
    <Glyph aria-label={label} className={className} role="img" size={size} />
  ) : (
    <Glyph aria-hidden="true" className={className} size={size} />
  );
}
