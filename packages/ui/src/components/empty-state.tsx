import type { LucideIcon } from "lucide-react";
import {
  createElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "../lib/utils";

export interface EmptyStateProps {
  readonly action?: ReactNode;
  readonly className?: string;
  /** What is missing and what to do next. */
  readonly description?: ReactNode;
  /** A Lucide icon (drawn at 22 px) or an icon element. */
  readonly icon?: LucideIcon | ReactElement;
  readonly title: ReactNode;
  /** 3 inside a section (default), 2 when the state replaces a whole page. */
  readonly headingLevel?: 2 | 3;
}

export function EmptyState({
  action,
  className,
  description,
  headingLevel = 3,
  icon,
  title,
}: EmptyStateProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <div className={cn("empty", className)}>
      {icon ? (
        <span aria-hidden="true" className="empty-icon">
          {isValidElement(icon)
            ? icon
            : createElement(icon as LucideIcon, { size: 22 })}
        </span>
      ) : null}
      <Heading className="empty-title">{title}</Heading>
      {description ? <div className="empty-text">{description}</div> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}
