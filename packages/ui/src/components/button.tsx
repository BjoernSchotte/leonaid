import type { LucideIcon } from "lucide-react";
import {
  createElement,
  isValidElement,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type Ref,
} from "react";

import { cn } from "../lib/utils";
import { Kbd } from "./kbd";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "danger"
  | "zone";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** A Lucide icon, or an icon element from code not yet moved to Lucide. */
  readonly icon?: LucideIcon | ReactNode;
  readonly variant?: ButtonVariant;
  readonly size?: ButtonSize;
  /** A binding such as "c" or "mod+enter", shown as subtle keycaps. */
  readonly shortcut?: string;
  readonly loading?: boolean;
  /**
   * Keep the button focusable while `disabled`: it is marked
   * `aria-disabled` and ignores activation instead of carrying the HTML
   * `disabled` attribute, which would drop focus to `<body>`. For buttons
   * that disable themselves after being pressed (a move that saves), so a
   * keyboard user keeps their place.
   */
  readonly focusableWhenDisabled?: boolean;
  /** For anchoring a Popover to the button. */
  readonly ref?: Ref<HTMLButtonElement>;
}

/** Class names for links that look like a button. */
export function buttonClassName({
  variant = "primary",
  size = "md",
}: { readonly variant?: ButtonVariant; readonly size?: ButtonSize } = {}) {
  return `btn btn-${variant} btn-${size}`;
}

function renderIcon(icon: ButtonProps["icon"], size: number): ReactNode {
  if (icon == null || isValidElement(icon)) return icon;
  // Lucide icons are forwardRef components (objects with a render function).
  if (
    typeof icon === "function" ||
    (typeof icon === "object" && "render" in icon)
  ) {
    return createElement(icon as LucideIcon, { "aria-hidden": true, size });
  }
  return icon;
}

/**
 * `disabled` as native attribute, or (with `focusableWhenDisabled`) as
 * `aria-disabled` with activation ignored, so the button keeps focus.
 */
function disabledProps(
  inactive: boolean,
  focusable: boolean | undefined,
  onClick: ButtonProps["onClick"],
): Pick<ButtonProps, "aria-disabled" | "disabled" | "onClick"> {
  if (!inactive || !focusable) return { disabled: inactive, onClick };
  return {
    "aria-disabled": true,
    disabled: false,
    // Also stops a submit button from submitting its form.
    onClick: (event) => event.preventDefault(),
  };
}

export function Button({
  children,
  className,
  disabled,
  focusableWhenDisabled,
  icon,
  loading,
  onClick,
  shortcut,
  size = "md",
  type = "button",
  variant = "primary",
  ...props
}: ButtonProps) {
  return (
    <button
      aria-busy={loading || undefined}
      className={cn(buttonClassName({ size, variant }), className)}
      type={type}
      {...props}
      {...disabledProps(
        !!(disabled || loading),
        focusableWhenDisabled,
        onClick,
      )}
    >
      {loading ? (
        <span aria-hidden="true" className="spinner" />
      ) : (
        renderIcon(icon, size === "sm" ? 14 : 16)
      )}
      {children != null && children !== false ? (
        <span className="btn-label">{children}</span>
      ) : null}
      {shortcut ? <Kbd announce={false} keys={shortcut} subtle /> : null}
    </button>
  );
}

export interface IconButtonProps
  extends Omit<ButtonProps, "children" | "icon" | "shortcut" | "loading"> {
  readonly icon: LucideIcon | ReactElement;
  /** Required: becomes the accessible name and the tooltip. */
  readonly label: string;
}

export function IconButton({
  className,
  disabled,
  focusableWhenDisabled,
  icon,
  label,
  onClick,
  size = "md",
  type = "button",
  variant = "ghost",
  ...props
}: IconButtonProps) {
  return (
    <button
      aria-label={label}
      className={cn(
        "btn",
        "btn-icon",
        `btn-${variant}`,
        `btn-${size}`,
        className,
      )}
      title={label}
      type={type}
      {...props}
      {...disabledProps(!!disabled, focusableWhenDisabled, onClick)}
    >
      {renderIcon(icon, size === "sm" ? 14 : 18)}
    </button>
  );
}
