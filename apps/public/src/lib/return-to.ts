/** Keep login navigation same-origin, including after URL decoding/normalizing. */
export function safeLocalReturnTo(value: string, fallback: string): string {
  let decoded = value;
  for (let depth = 0; depth < 5; depth += 1) {
    if (
      !decoded.startsWith("/") ||
      decoded.startsWith("//") ||
      /[\\\u0000-\u0020\u007f]/.test(decoded)
    )
      return fallback;
    try {
      if (
        new URL(decoded, "https://leonaid.invalid").origin !==
        "https://leonaid.invalid"
      )
        return fallback;
      const next = decodeURIComponent(decoded);
      if (next === decoded) return value;
      decoded = next;
    } catch {
      return fallback;
    }
  }
  return fallback;
}
