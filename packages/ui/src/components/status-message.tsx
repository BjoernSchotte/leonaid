import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/utils";
import { Button } from "./button";

export type StatusTone = "error" | "info" | "success" | "warning";

export interface StatusMessageProps {
  readonly children: ReactNode;
  readonly className?: string;
  readonly id?: string;
  readonly tone?: StatusTone;
}

const toneClass = {
  error: "tone-danger",
  info: "tone-info",
  success: "tone-ok",
  warning: "tone-warn",
} as const;

const icons = {
  error: CircleAlert,
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
} as const;

/** Inline notice (the prototype's callout). Errors are announced as alerts. */
export function StatusMessage({
  children,
  className,
  id,
  tone = "info",
}: StatusMessageProps) {
  const ToneIcon = icons[tone];
  return (
    <div
      className={cn("callout", toneClass[tone], className)}
      id={id}
      role={tone === "error" ? "alert" : "status"}
    >
      <ToneIcon aria-hidden="true" size={16} />
      <div>{children}</div>
    </div>
  );
}

export interface ErrorStateProps {
  readonly children: ReactNode;
  readonly className?: string;
  readonly onRetry?: () => void;
  readonly title: ReactNode;
}

/** A failed load: what went wrong and, when possible, "Erneut versuchen". */
export function ErrorState({
  children,
  className,
  onRetry,
  title,
}: ErrorStateProps) {
  return (
    <div className={cn("error-state", className)} role="alert">
      <h3>{title}</h3>
      <div className="error-text">{children}</div>
      {onRetry ? (
        <Button onClick={onRetry} variant="secondary">
          Erneut versuchen
        </Button>
      ) : null}
    </div>
  );
}
