import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import pg from "pg";

// Content witness for the EmDash binary upgrade (legacy release -> pinned
// release). `capture <name>` writes every CMS row that carries editorial
// content, media or LeonAid bindings; `compare <before> <after>` proves the
// upgrade kept them. Only the documented upstream changes are tolerated: new
// columns and options from the added migrations, and datetime values that the
// datetime normalisation migration rewrites to the same instant in UTC ISO.
// Row values are never printed.
const [mode, ...names] = process.argv.slice(2);
const proof = (name) => `/proof/emdash-upgrade-${name}.json`;

const tables = [
  ["ec_campaign_pages", "id"],
  ["revisions", "id"],
  ["media", "id"],
  ["leonaid_campaign_media", "media_id"],
  ["leonaid_external_identity", "core_user_id"],
  ["users", "id"],
  ["_emdash_collections", "slug"],
  ["_emdash_fields", "id"],
  ["options", "name"],
];
// EmDash's scheduler heartbeat changes while the CMS runs; not content.
const volatileOptions = new Set(["system:scheduler:last_completed_at"]);

async function capture(name) {
  const client = new pg.Client({
    host: "core-postgres",
    database: "emdash",
    user: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
    connectionTimeoutMillis: 3000,
    statement_timeout: 10_000,
  });
  await client.connect();
  try {
    const snapshot = {};
    for (const [table, key] of tables) {
      const result = await client.query(
        `SELECT * FROM public.${table} ORDER BY ${key}`,
      );
      snapshot[table] = result.rows
        .filter((row) => table !== "options" || !volatileOptions.has(row.name))
        .map((row) =>
          Object.fromEntries(
            Object.entries(row).map(([column, value]) => [
              column,
              value instanceof Date ? value.toISOString() : value,
            ]),
          ),
        );
    }
    const migrations = await client.query(
      "SELECT name FROM public._emdash_migrations ORDER BY name",
    );
    snapshot.migrations = migrations.rows.map((row) => row.name);
    assert.ok(snapshot.ec_campaign_pages.length > 0, "no campaign content");
    assert.ok(snapshot.media.length > 0, "no campaign media");
    assert.ok(
      snapshot.revisions.some((row) => row.collection === "campaign_pages"),
      "no campaign revisions",
    );
    await writeFile(proof(name), JSON.stringify(snapshot), { mode: 0o600 });
    console.log(
      `emdash-upgrade-snapshot: ${name}: ${snapshot.ec_campaign_pages.length} pages, ${snapshot.revisions.length} revisions, ${snapshot.media.length} media, ${snapshot.migrations.length} migrations`,
    );
  } finally {
    await client.end();
  }
}

const isoLike =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;
// Same instant, independent of the stored text form. A value without offset
// is UTC (site:timezone is unset, so the migration reads it as UTC).
function normalize(value) {
  if (typeof value === "string") {
    if (isoLike.test(value)) {
      const text = /(Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
      const time = Date.parse(text.replace(" ", "T"));
      if (!Number.isNaN(time)) return { instant: new Date(time).toISOString() };
    }
    if (/^[[{]/.test(value)) {
      try {
        return { json: normalize(JSON.parse(value)) };
      } catch {
        return value;
      }
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, normalize(item)]),
    );
  return value;
}

async function compare(beforeName, afterName) {
  const before = JSON.parse(await readFile(proof(beforeName), "utf8"));
  const after = JSON.parse(await readFile(proof(afterName), "utf8"));
  const added = after.migrations.filter(
    (name) => !before.migrations.includes(name),
  );
  assert.ok(
    before.migrations.every((name) => after.migrations.includes(name)),
    "an applied migration disappeared",
  );
  assert.ok(added.length > 0, "no upstream migration was applied");
  const report = [];
  for (const [table, key] of tables) {
    const old = before[table];
    const current = after[table];
    const currentByKey = new Map(current.map((row) => [row[key], row]));
    const oldKeys = new Set(old.map((row) => row[key]));
    const newRows = current.filter((row) => !oldKeys.has(row[key]));
    // Upgrades may only add rows of their own: migration options.
    assert.ok(
      table === "options" ? true : newRows.length === 0,
      `${table}: rows were added by the upgrade`,
    );
    assert.ok(
      newRows.every((row) => !String(row.name).startsWith("leonaid:")),
      `${table}: LeonAid options were added by the upgrade`,
    );
    const oldColumns = Object.keys(old[0] ?? {});
    const newColumns = Object.keys(current[0] ?? {}).filter(
      (column) => !oldColumns.includes(column),
    );
    let changedInstants = 0;
    for (const row of old) {
      const next = currentByKey.get(row[key]);
      assert.ok(next, `${table}: a row was removed by the upgrade`);
      for (const column of oldColumns) {
        assert.ok(column in next, `${table}: a column was removed`);
        if (isDeepStrictEqual(row[column], next[column])) continue;
        assert.ok(
          isDeepStrictEqual(normalize(row[column]), normalize(next[column])),
          `${table}.${column}: value changed by the upgrade`,
        );
        changedInstants++;
      }
    }
    report.push(
      `${table}: ${old.length} rows kept${newRows.length ? `, ${newRows.length} added` : ""}${newColumns.length ? `, new columns ${newColumns.join("/")}` : ""}${changedInstants ? `, ${changedInstants} datetime values normalised` : ""}`,
    );
  }
  console.log(`emdash-upgrade-snapshot: ${added.length} migrations applied`);
  for (const line of report) console.log(`emdash-upgrade-snapshot: ${line}`);
  console.log(
    "emdash-upgrade-snapshot: OK: content, revisions, media, bindings and identities kept",
  );
}

async function compareUnchanged(name) {
  const expected = await readFile(proof(name), "utf8");
  await capture(`${name}-recheck`);
  const actual = await readFile(proof(`${name}-recheck`), "utf8");
  assert.ok(
    isDeepStrictEqual(JSON.parse(actual), JSON.parse(expected)),
    `CMS state changed since snapshot ${name}`,
  );
  console.log(`emdash-upgrade-snapshot: OK: state unchanged since ${name}`);
}

if (mode === "capture" && names.length === 1) await capture(names[0]);
else if (mode === "compare" && names.length === 2)
  await compare(names[0], names[1]);
else if (mode === "compare-unchanged" && names.length === 1)
  await compareUnchanged(names[0]);
else {
  console.error(
    "usage: emdash-upgrade-snapshot.mjs capture NAME | compare A B | compare-unchanged NAME",
  );
  process.exitCode = 2;
}
