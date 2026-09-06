import assert from "node:assert/strict";
import { safeLocalReturnTo } from "../../apps/public/src/lib/return-to";

for (const value of [
  "/_emdash/admin/",
  "/admin/?action=demo",
  "/campaigns/example/",
]) {
  assert.equal(safeLocalReturnTo(value, "/app/"), value);
}
for (const value of [
  "https://attacker.invalid",
  "//attacker.invalid",
  "/\\attacker.invalid",
  "/%5cattacker.invalid",
  "/%255cattacker.invalid",
  "/%2fattacker.invalid",
  "/%252fattacker.invalid",
  "/%0a/attacker.invalid",
  "/%",
  " /admin/",
  "/%25252525252fattacker.invalid",
]) {
  assert.equal(safeLocalReturnTo(value, "/app/"), "/app/");
}
console.log(
  "emdash-return-to: OK: local destinations retained; external, backslash, control and nested encoded escapes denied",
);
