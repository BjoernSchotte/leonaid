import type { ComponentPropsWithRef, ReactNode } from "react";

import { cn } from "../lib/utils";

export interface SwitchProps extends Omit<
  ComponentPropsWithRef<"input">,
  "type" | "role"
> {
  /** Visible label; without it, name the switch with `aria-label`. */
  readonly label?: ReactNode;
}

/**
 * On/off switch. A real checkbox covers the track, so label, focus and
 * keyboard stay native.
 */
export function Switch({ className, label, ...props }: SwitchProps) {
  const control = (
    <span className={cn("switch", label == null && className)}>
      <input role="switch" type="checkbox" {...props} />
      <span aria-hidden="true" className="switch-track" />
    </span>
  );
  if (label == null) return control;
  return (
    <label className={cn("switch-row", className)}>
      {control}
      {label}
    </label>
  );
}
