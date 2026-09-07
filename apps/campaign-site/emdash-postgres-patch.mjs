import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";

export function postgresAdapterEntry() {
  return createRequire(import.meta.url).resolve("emdash/db/postgres");
}

// Upstream only forwards min/max. Bound actual pg acquisition rather than
// racing a timer against an operation that would remain queued indefinitely.
// Preserve upstream's fail-fast migration adapter and runtime credential reads.
export function patchPostgresSource(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    "5fef8beca87d9875671f92d1907d13ea0e2b3b93862054dbc767ce43face56f5",
    "EmDash PostgreSQL source changed; re-review connection budgets",
  );
  const needle = "max: config.pool?.max ?? 10";
  assert.equal(source.split(needle).length, 2);
  return source.replace(
    needle,
    `${needle},\n\t\tconnectionTimeoutMillis: 2000`,
  );
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
