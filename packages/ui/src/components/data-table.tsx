import type { HTMLAttributes, ReactNode, TableHTMLAttributes } from "react";

import { cn } from "../lib/utils";

export interface DataTableProps extends TableHTMLAttributes<HTMLTableElement> {
  readonly caption: string;
  readonly children: ReactNode;
  readonly containerProps?: HTMLAttributes<HTMLDivElement>;
}

export function DataTable({
  caption,
  children,
  className,
  containerProps,
  ...props
}: DataTableProps) {
  return (
    <div
      {...containerProps}
      aria-label={`${caption}, horizontaler Bildlaufbereich`}
      className={cn("ui-table-scroll", containerProps?.className)}
      role="region"
      tabIndex={0}
    >
      <table className={cn("ui-table", className)} {...props}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}
