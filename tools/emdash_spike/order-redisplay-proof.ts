import assert from "node:assert/strict";
import { readOrderRedisplay } from "../../apps/public/src/lib/order-redisplay";

const id = "20000000-0000-4000-8000-000000000001";
const body = new URLSearchParams({
  publicAlias: "krapfentaxi",
  commandId: id,
  givenName: "Synthetic",
  companyName: "<script>synthetic</script>",
  accessToken: "not-retained",
  quotedUnitPriceMinor: "1",
  offeringId: id,
  quantity: "3",
  deliveryWindowId: id,
  deliveryContactName: "Synthetic reception",
  deliveryContactPhone: "+49 123 / 456",
});
const request = (input: URLSearchParams | string) =>
  new Request("https://localhost/", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: input,
  });
const result = await readOrderRedisplay(request(body), "krapfentaxi");
assert.equal(result?.fields.givenName, "Synthetic");
assert.equal(result?.fields.companyName, "<script>synthetic</script>");
assert.equal(result?.commandId, id);
assert.equal(result?.quantities[id], 3);
assert.equal(result?.billingSameAsDelivery, false);
assert.equal(result?.fields.deliveryWindowId, id);
assert.equal(result?.fields.deliveryContactName, "Synthetic reception");
assert.equal(result?.fields.deliveryContactPhone, "+49 123 / 456");
assert.ok(!JSON.stringify(result).includes("not-retained"));
assert.ok(!JSON.stringify(result).includes("quotedUnitPriceMinor"));
assert.equal(await readOrderRedisplay(request(body), "foreign"), null);
assert.equal(
  await readOrderRedisplay(new Request("https://localhost/"), "krapfentaxi"),
  null,
);
body.append("givenName", "Duplicate");
body.set("quantity", "5001");
body.set("phone", "x".repeat(41));
body.set("commandId", "invalid");
body.append("deliveryWindowId", id);
body.set("deliveryContactName", "x".repeat(201));
body.set("deliveryContactPhone", "x".repeat(41));
const rejected = await readOrderRedisplay(request(body), "krapfentaxi");
assert.equal(rejected?.fields.givenName, undefined);
assert.equal(rejected?.fields.phone, undefined);
assert.equal(rejected?.commandId, undefined);
assert.equal(rejected?.quantities[id], undefined);
assert.equal(rejected?.fields.deliveryWindowId, undefined);
assert.equal(rejected?.fields.deliveryContactName, undefined);
assert.equal(rejected?.fields.deliveryContactPhone, undefined);
assert.equal(
  await readOrderRedisplay(request("x".repeat(65537)), "krapfentaxi"),
  null,
);
console.log(
  "order-redisplay: request-local allowlist, alias binding, quantity/UUID validation, duplicate/oversized denial and credential exclusion passed",
);
