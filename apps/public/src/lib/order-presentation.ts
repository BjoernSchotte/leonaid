import type { PublicOfferingResponse } from "@leonaid/api-client";

export function offeringPrice(offering: PublicOfferingResponse): string {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: offering.currency,
  }).format(offering.unitPriceMinor / 100);
}

export function money(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency,
  }).format(amountMinor / 100);
}

export function offeringUnit(offering: PublicOfferingResponse): string {
  const labels: Record<PublicOfferingResponse["unit"], string> = {
    box: "je Box",
    package: "je Paket",
    piece: "je Stück",
    sponsoring: "je Sponsoring",
  };
  return labels[offering.unit];
}

/** Keep unlike units separate; sponsoring is never a count of physical items. */
export function orderQuantitySummary(
  lines: readonly {
    unit: string;
    piecesPerUnit: number | null;
    quantity: number;
  }[],
): string {
  const groups = new Map<
    string,
    { label: string; quantity: number; pieces: number | null }
  >();
  for (const { unit, piecesPerUnit, quantity } of lines) {
    if (!Number.isInteger(quantity) || quantity < 0 || quantity > 5000)
      return "Bitte prüfe die Mengen.";
    if (quantity === 0) continue;
    if (!["box", "package", "piece", "sponsoring"].includes(unit))
      return "Bitte prüfe die Mengen.";
    const pieces =
      (unit === "box" || unit === "package") &&
      piecesPerUnit !== null &&
      Number.isInteger(piecesPerUnit) &&
      piecesPerUnit > 0
        ? piecesPerUnit
        : null;
    const key = `${unit}:${pieces}`;
    const group = groups.get(key);
    if (group) group.quantity += quantity;
    else groups.set(key, { label: unit, quantity, pieces });
  }
  return (
    [...groups.values()]
      .map(({ label, quantity, pieces }) => {
        const unit =
          label === "box"
            ? quantity === 1
              ? "Box"
              : "Boxen"
            : label === "package"
              ? quantity === 1
                ? "Paket"
                : "Pakete"
              : label === "piece"
                ? "Stück"
                : "Sponsoring";
        return `${quantity} ${unit}${pieces === null ? "" : ` (${quantity * pieces} Stück)`}`;
      })
      .join(" · ") || "Noch keine Menge gewählt"
  );
}
