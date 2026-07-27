import type { ReactNode } from "react";

import { cn } from "../lib/utils";

export interface EmptyStateProps {
  readonly action?: ReactNode;
  readonly className?: string;
  readonly description: ReactNode;
  readonly icon?: ReactNode;
  readonly title: ReactNode;
}

export function EmptyState({
  action,
  className,
  description,
  icon,
  title,
}: EmptyStateProps) {
  return (
    <section className={cn("ui-empty-state", className)}>
      {icon ? (
        <div aria-hidden="true" className="ui-empty-state__icon">
          {icon}
        </div>
      ) : null}
      <h2>{title}</h2>
      <p>{description}</p>
      {action ? <div className="ui-empty-state__action">{action}</div> : null}
    </section>
  );
}
