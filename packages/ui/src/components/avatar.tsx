import { cn } from "../lib/utils";

const AVATAR_BUCKETS = 24;

/** First letter of the first and last word; a single word gives two letters. */
export function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const letters = (word: string) => Array.from(word);
  const first = letters(words[0]!);
  const initials =
    words.length === 1
      ? first.slice(0, 2).join("")
      : `${first[0]}${letters(words[words.length - 1]!)[0]}`;
  return initials.toLocaleUpperCase("de-DE");
}

/** Stable hue bucket (24 steps of 15°) from the name, FNV-1a hashed. */
export function avatarHueBucket(name: string): number {
  let hash = 0x811c9dc5;
  for (const character of name.trim().toLocaleLowerCase("de-DE")) {
    hash ^= character.codePointAt(0)!;
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) % AVATAR_BUCKETS;
}

export interface AvatarProps {
  readonly name: string;
  readonly size?: "xs" | "sm" | "md";
  /** Makes the avatar a labelled image; without it the avatar is decorative. */
  readonly label?: string;
}

/**
 * The hue comes from a class bucket, never a style attribute: WebKit reports
 * CSSOM-written style attributes as CSP style-src-attr violations.
 */
export function Avatar({ name, size = "sm", label }: AvatarProps) {
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={cn(
        "avatar",
        `avatar-${size}`,
        `avatar-h${avatarHueBucket(name)}`,
      )}
      role={label ? "img" : undefined}
    >
      {initialsFor(name)}
    </span>
  );
}
