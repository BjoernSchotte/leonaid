/** Admin pages address people with "Sie", the app with "Du". */
export type Address = "sie" | "du";

/** Picks the Du or the Sie variant of a text. */
export function says(address: Address, du: string, sie: string): string {
  return address === "du" ? du : sie;
}
