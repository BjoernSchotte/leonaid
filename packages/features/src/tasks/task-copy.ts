import type { ErrorAddress } from "../action-admin/errors";

/** Admin pages address people with "Sie", the app with "du" (as errors.ts). */
export type Address = ErrorAddress;

/** Picks the Du or the Sie variant of a text. */
export function says(address: Address, du: string, sie: string): string {
  return address === "du" ? du : sie;
}
