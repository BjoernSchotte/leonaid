import assert from "node:assert/strict";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const { services } = JSON.parse(input);
const cms = services["campaign-site"];
assert.ok(!cms.ports?.length);
assert.deepEqual(Object.keys(cms.networks).sort(), [
  "cms-data",
  "edge",
  "storage-data",
]);
assert.ok(!services.proxy.depends_on?.["campaign-site"]);
const env = cms.environment;
assert.equal(env.PGUSER, "emdash");
assert.equal(env.PGDATABASE, "emdash");
assert.equal(env.S3_BUCKET, "emdash-media");
assert.equal(env.S3_ACCESS_KEY_ID, "leonaid-emdash");
assert.ok(env.PGPASSWORD?.length >= 32);
assert.ok(env.S3_SECRET_ACCESS_KEY?.length >= 32);
assert.match(env.EMDASH_ENCRYPTION_KEY, /^emdash_enc_v1_[A-Za-z0-9_-]{43}$/);
assert.notEqual(
  env.PGPASSWORD,
  services["core-postgres"].environment.POSTGRES_PASSWORD,
);
assert.notEqual(
  env.S3_SECRET_ACCESS_KEY,
  services.rustfs.environment.RUSTFS_SECRET_KEY,
);
for (const key of Object.keys(env))
  assert.ok(!/^(CORE_|TWENTY_|RUSTFS_)/.test(key));
console.log(
  "emdash-service-topology: OK: no host port, dedicated networks/credentials, independent proxy",
);
