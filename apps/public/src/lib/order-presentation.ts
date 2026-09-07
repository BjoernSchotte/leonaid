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
