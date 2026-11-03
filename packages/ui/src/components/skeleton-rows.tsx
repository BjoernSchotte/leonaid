import { cn } from "../lib/utils";

const lineWidths = ["w-60", "w-40", "w-50"] as const;

/**
 * Loading placeholder rows. Hidden from assistive technology; set `aria-busy`
 * on the region that is loading.
 */
export function SkeletonRows({
  className,
  rows = 6,
}: {
  readonly className?: string;
  readonly rows?: number;
}) {
  return (
    <div aria-hidden="true" className={cn("skeleton-list", className)}>
      {Array.from({ length: rows }, (_value, index) => (
        <div className="skeleton-row" key={index}>
          <span className="skeleton skeleton-dot" />
          <span className={`skeleton skeleton-line ${lineWidths[index % 3]}`} />
          <span className="skeleton skeleton-chip" />
        </div>
      ))}
    </div>
  );
}
