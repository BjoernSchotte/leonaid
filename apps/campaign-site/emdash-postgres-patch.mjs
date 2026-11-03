import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";

export function postgresAdapterEntry() {
  return createRequire(import.meta.url).resolve("emdash/db/postgres");
}

// The CMS request pool. EmDash 1.x forwards connectionTimeoutMillis to pg.
// This bounds actual pg acquisition instead of racing a timer against an
// operation that stays queued. astro.config.mjs and the postgres-pool proof
// use this exact object.
export const cmsPoolConfig = Object.freeze({
  min: 0,
  max: 5,
  connectionTimeoutMillis: 2000,
});

// Upstream does not forward a statement timeout. A server-side statement
// timeout also covers native queries outside our explicit transactions; those
// transactions keep their stricter local limits. Upstream's fail-fast
// migration adapter, pool error redaction and runtime credential reads stay.
export function patchPostgresSource(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    "fe956a3c0d307e98f9830a7c7a27e6cd8afb448b6963c3f85fa1e61b386e7ad4",
    "EmDash PostgreSQL source changed; re-review connection budgets",
  );
  assert.equal(
    source.split(
      "connectionTimeoutMillis: config.pool?.connectionTimeoutMillis",
    ).length,
    2,
  );
  const needle = "idleTimeoutMillis: config.pool?.idleTimeoutMillis";
  assert.equal(source.split(needle).length, 2);
  return source.replace(needle, `${needle},\n\t\tstatement_timeout: 5000`);
}

export default function postgresPatch() {
  const entry = postgresAdapterEntry();
  let transformed = false;
  return {
    name: "leonaid-pinned-postgres-acquisition-budget",
    hooks: {
      "astro:config:setup": async ({ updateConfig }) => {
        patchPostgresSource(await readFile(entry, "utf8"));
        updateConfig({
          vite: {
            plugins: [
              {
                name: "leonaid-postgres-acquisition-budget",
                enforce: "pre",
                transform(source, id) {
                  if (id.split("?")[0] !== entry) return;
                  transformed = true;
                  return { code: patchPostgresSource(source), map: null };
                },
              },
            ],
          },
        });
      },
      "astro:build:done": () => {
        assert.ok(
          transformed,
          "PostgreSQL acquisition budget was not applied to the production build",
        );
      },
    },
  };
}
