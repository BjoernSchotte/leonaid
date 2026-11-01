import type { UnitQuantityResponse } from "@leonaid/api-client";

export type OfferingUnit = UnitQuantityResponse["unit"];

// German singular/plural labels per offering unit. Units are generic: a
// campaign sells boxes, pieces, packages or sponsorings, never "krapfen".
export const unitLabels: Readonly<
  Record<OfferingUnit, readonly [string, string]>
> = {
  box: ["Box", "Boxen"],
  package: ["Paket", "Pakete"],
  piece: ["Stück", "Stück"],
  sponsoring: ["Sponsoring", "Sponsorings"],
};

export function quantityLabel(quantity: number, unit: OfferingUnit): string {
  return unitLabels[unit][quantity === 1 ? 0 : 1];
}

interface QuantitySummary {
  readonly labels: readonly string[];
  readonly values: readonly number[];
}

/**
 * Split per-unit quantities into parallel label/value lists. A piece total is
 * appended when another unit converts into pieces (e.g. boxes of 24).
 */
export function quantitySummary(
  quantities: readonly UnitQuantityResponse[],
  totalPieces: number,
): QuantitySummary {
  const labels = quantities.map((item) => unitLabels[item.unit][1]);
  const values = quantities.map((item) => item.quantity);
  const directPieces = quantities
    .filter((item) => item.unit === "piece")
    .reduce((sum, item) => sum + item.quantity, 0);
  if (totalPieces > directPieces) {
    labels.push(directPieces > 0 ? "Stück gesamt" : "Stück");
    values.push(totalPieces);
  }
  if (!labels.length) return { labels: ["Menge"], values: [0] };
  return { labels, values };
}

/** Human-readable quantities, e.g. "25 Boxen · 600 Stück" or "3 Stück". */
export function formatQuantities(
  quantities: readonly UnitQuantityResponse[],
  totalPieces: number,
): string {
  const parts = quantities.map(
    (item) => `${item.quantity} ${quantityLabel(item.quantity, item.unit)}`,
  );
  const directPieces = quantities
    .filter((item) => item.unit === "piece")
    .reduce((sum, item) => sum + item.quantity, 0);
  if (totalPieces > directPieces) {
    parts.push(`${totalPieces} Stück${directPieces > 0 ? " gesamt" : ""}`);
  }
  return parts.length ? parts.join(" · ") : "0 Stück";
}
