import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { cn } from "../lib/utils";

export type StatusTone = "error" | "info" | "success";

export interface StatusMessageProps {
  readonly children: React.ReactNode;
  readonly className?: string;
  readonly id?: string;
  readonly tone?: StatusTone;
}

const icons = {
  error: Alert02Icon,
  info: InformationCircleIcon,
  success: CheckmarkCircle02Icon,
} as const;

export function StatusMessage({
  children,
  className,
  id,
  tone = "info",
}: StatusMessageProps) {
  return (
    <div
      className={cn("ui-status", `ui-status--${tone}`, className)}
      id={id}
      role={tone === "error" ? "alert" : "status"}
    >
      <HugeiconsIcon
        aria-hidden="true"
        icon={icons[tone]}
        size={20}
        strokeWidth={1.8}
      />
      <div>{children}</div>
    </div>
  );
}
