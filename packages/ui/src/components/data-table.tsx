import type { HTMLAttributes, ReactNode, TableHTMLAttributes } from "react";

import { cn } from "../lib/utils";

export interface DataTableProps extends TableHTMLAttributes<HTMLTableElement> {
  readonly caption: string;
  readonly children: ReactNode;
  readonly containerProps?: HTMLAttributes<HTMLDivElement>;
}

/**
 * The prototype table (`.table-wrap` / `.table` in page-sections.css) with a
 * caption and a labelled, focusable scroll region: scrollbars are hidden, so
 * keyboard users scroll wide tables through the focused region.
 */
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
      className={cn("table-wrap", containerProps?.className)}
      role="region"
      tabIndex={0}
    >
      <table className={cn("table", className)} {...props}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}
