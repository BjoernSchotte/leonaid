import assert from "node:assert/strict";
import { orderQuantitySummary } from "../../apps/public/src/lib/order-presentation";

const box = { unit: "box", piecesPerUnit: 24, quantity: 3 };
const pack = { unit: "package", piecesPerUnit: null, quantity: 2 };
const piece = { unit: "piece", piecesPerUnit: null, quantity: 4 };
const sponsor = { unit: "sponsoring", piecesPerUnit: null, quantity: 1 };
assert.equal(orderQuantitySummary([box]), "3 Boxen (72 Stück)");
assert.equal(
  orderQuantitySummary([box, pack, piece, sponsor]),
  "3 Boxen (72 Stück) · 2 Pakete · 4 Stück · 1 Sponsoring",
);
assert.equal(
  orderQuantitySummary([sponsor, piece, pack, box]),
  "1 Sponsoring · 4 Stück · 2 Pakete · 3 Boxen (72 Stück)",
);
assert.equal(
  orderQuantitySummary([{ ...box, quantity: 1 }]),
  "1 Box (24 Stück)",
);
assert.equal(orderQuantitySummary([{ ...pack, quantity: 1 }]), "1 Paket");
assert.equal(orderQuantitySummary([box, box]), "6 Boxen (144 Stück)");
assert.equal(
  orderQuantitySummary([box, { ...box, piecesPerUnit: 12 }]),
  "3 Boxen (72 Stück) · 3 Boxen (36 Stück)",
);
assert.equal(
  orderQuantitySummary([{ ...pack, piecesPerUnit: 6 }]),
  "2 Pakete (12 Stück)",
);
assert.equal(
  orderQuantitySummary([{ ...sponsor, piecesPerUnit: 24 }]),
  "1 Sponsoring",
);
assert.equal(
  orderQuantitySummary([{ ...box, piecesPerUnit: null }]),
  "3 Boxen",
);
assert.equal(
  orderQuantitySummary([{ ...box, quantity: 0 }]),
  "Noch keine Menge gewählt",
);
assert.equal(orderQuantitySummary([]), "Noch keine Menge gewählt");
for (const quantity of [-1, 0.5, 5001, NaN, Infinity]) {
  assert.equal(
    orderQuantitySummary([{ ...box, quantity }]),
    "Bitte prüfe die Mengen.",
  );
}
assert.equal(
  orderQuantitySummary([{ ...box, unit: "unknown" }]),
  "Bitte prüfe die Mengen.",
);
console.log(
  "order-presentation: heterogeneous units, piece counts, missing metadata, ordering, aggregation and invalid quantity checks passed",
);
