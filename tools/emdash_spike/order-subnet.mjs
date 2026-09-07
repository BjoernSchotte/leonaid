import assert from "node:assert/strict";
import { randomInt } from "node:crypto";

function range(cidr) {
  const [address, prefix] = cidr.split("/");
  if (address.includes(":")) return null;
  const octets = address.split(".").map(Number);
  assert.ok(
    octets.length === 4 &&
      octets.every((n) => Number.isInteger(n) && n >= 0 && n <= 255),
  );
  const bits = Number(prefix);
  assert.ok(Number.isInteger(bits) && bits >= 0 && bits <= 32);
  const size = 2 ** (32 - bits);
  const start =
    Math.floor(octets.reduce((n, octet) => n * 256 + octet, 0) / size) * size;
  return [start, start + size - 1];
}

function choose(subnets, offset) {
  const occupied = subnets.map(range).filter(Boolean);
  for (let index = 0; index < 256; index++) {
    const candidate = `172.29.${(index + offset) % 256}.0/24`;
    const [start, end] = range(candidate);
    if (occupied.every(([low, high]) => end < low || start > high))
      return candidate;
  }
  throw new Error("No non-overlapping isolated CRM subnet available");
}

if (process.argv.includes("--self-test")) {
  assert.equal(choose(["172.29.0.0/23", "fc00::/64"], 0), "172.29.2.0/24");
  assert.equal(choose(["172.29.255.128/25"], 255), "172.29.0.0/24");
  assert.throws(() => choose(["172.16.0.0/12"], 0));
  assert.throws(() => range("invalid/24"));
  console.log(
    "order-subnet: overlap, enclosing/contained ranges, IPv6 and exhaustion checks passed",
  );
} else {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const networks = JSON.parse(input);
  const subnets = networks.flatMap((network) =>
    (network.IPAM?.Config ?? []).map((item) => item.Subnet).filter(Boolean),
  );
  process.stdout.write(choose(subnets, randomInt(256)));
}
