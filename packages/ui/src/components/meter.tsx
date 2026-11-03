import { useLayoutEffect, useRef } from "react";

import type { Tone } from "./badge";

export interface MeterProps {
  readonly value: number;
  readonly max: number;
  readonly label: string;
  readonly tone?: Tone;
}

/** Progress bar; the fill ratio goes through CSSOM to stay CSP-safe. */
export function Meter({ value, max, label, tone = "zone" }: MeterProps) {
  const ref = useRef<HTMLDivElement>(null);
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const now = Math.min(Math.max(value, 0), Math.max(max, 0));
  useLayoutEffect(() => {
    ref.current?.style.setProperty("--meter", String(ratio));
  }, [ratio]);
  return (
    <div
      aria-label={label}
      aria-valuemax={max}
      aria-valuemin={0}
      aria-valuenow={now}
      className={`meter tone-${tone}`}
      ref={ref}
      role="meter"
    >
      <span className="meter-fill" />
    </div>
  );
}
