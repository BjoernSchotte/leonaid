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

// Docker's default pools hand out whole /16s from 172.17.0.0/12, so on a busy
// host another project can cover 172.29.0.0/16 completely. 10.214.0.0/16 lies
// outside Docker's defaults and outside the Python test pools (10.213/16).
const PREFIXES = ["172.29", "10.214"];

function choose(subnets, offset) {
  const occupied = subnets.map(range).filter(Boolean);
  for (const prefix of PREFIXES) {
    for (let index = 0; index < 256; index++) {
      const candidate = `${prefix}.${(index + offset) % 256}.0/24`;
      const [start, end] = range(candidate);
      if (occupied.every(([low, high]) => end < low || start > high))
        return candidate;
    }
  }
  throw new Error("No non-overlapping isolated CRM subnet available");
}

if (process.argv.includes("--self-test")) {
  assert.equal(choose(["172.29.0.0/23", "fc00::/64"], 0), "172.29.2.0/24");
  assert.equal(choose(["172.29.255.128/25"], 255), "172.29.0.0/24");
  assert.equal(choose(["172.29.0.0/16"], 7), "10.214.7.0/24");
  assert.throws(() => choose(["172.16.0.0/12", "10.0.0.0/8"], 0));
  assert.throws(() => range("invalid/24"));
  console.log(
    "order-subnet: overlap, enclosing/contained ranges, IPv6, fallback pool and exhaustion checks passed",
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
