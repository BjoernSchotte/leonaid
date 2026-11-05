import { useEffect, useState } from "react";

/**
 * The value after it stopped changing for `delay` ms: list searches send
 * one request per pause in typing, not one per keystroke.
 */
export function useDebouncedValue<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
