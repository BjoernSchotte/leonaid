/**
 * The sentence fragment that says in which time zone delivery times apply,
 * for buyers and members: "nach deutscher Zeit" instead of the IANA name
 * "Europe/Berlin", which reads like a code. Other zones keep their name.
 */
export function timeZoneHint(timeZone: string): string {
  return timeZone === "Europe/Berlin"
    ? "nach deutscher Zeit"
    : `in der Zeitzone ${timeZone}`;
}
