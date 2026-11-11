// Pure classification of the CMS provisioning state (cms-provision-operator.mjs
// status, ./leonaid pilot-cms-provision). No I/O: the operator collects the
// facts, these functions decide which step is open, done or refused.

// 28P01 wrong password, 28000 unknown role, 3D000 unknown database: the
// database step has not run (or ran with another password). Anything else
// (server down, timeout, refused connection) must not look like a step to
// repeat.
export function databaseErrorState(error) {
  return ["28P01", "28000", "3D000"].includes(error?.code)
    ? "missing"
    : "unavailable";
}

// RustFS answered with a client error (no bucket, unknown or refused key): the
// storage step has not run. No HTTP answer at all is an outage.
export function storageErrorState(error) {
  const status = (error?.cause ?? error)?.$metadata?.httpStatusCode;
  return Number.isInteger(status) && status >= 400 && status < 500
    ? "missing"
    : "unavailable";
}

// EmDash's own migrations: exactly this release's list is ready; a gapless
// prefix without unknown names is an unfinished first run; anything else
// belongs to the reviewed migration controller, never to provisioning.
export function migrationState(migrations, names) {
  const applied = migrations.knownApplied;
  if (
    !migrations.pending.length &&
    !migrations.unknownApplied.length &&
    JSON.stringify(applied) === JSON.stringify(names)
  )
    return "ready";
  return !migrations.unknownApplied.length &&
    JSON.stringify(applied) === JSON.stringify(names.slice(0, applied.length))
    ? "missing"
    : "refused";
}

// A live CMS (completed setup) whose database lacks only later migrations of
// a newer release image: the release's CMS migration step applies them
// (upgrade, cms-migration-operator upgrade-emdash), never provisioning.
export function releaseDatabaseState(state, appliedCount, bootstrap) {
  return state === "missing" && appliedCount > 0 && bootstrap === "complete"
    ? "pending"
    : state;
}

// The campaign schema step installs three parts, each in its own transaction
// with its own version option: the collection (schema), the binding guards
// and the media guards. `versions` holds the stored option values (undefined
// when absent), `expected` this release's values, `verified` whether the
// require* check of each present part passed. A step interrupted between two
// parts leaves the later ones absent: "partial" lets the step run again, as
// every installer verifies what exists instead of repairing it.
export function schemaState(versions, expected, verified) {
  const parts = ["schema", "bindings", "media"];
  const present = parts.filter((part) => versions[part] !== undefined);
  if (!present.length) return "missing";
  if (versions.schema === undefined) return "refused";
  for (const part of present)
    if (versions[part] !== expected[part] || verified[part] !== true)
      return "refused";
  return present.length === parts.length ? "ready" : "partial";
}
