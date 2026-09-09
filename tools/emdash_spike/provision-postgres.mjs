import { pathToFileURL } from "node:url";
import pg from "pg";

const { Pool, escapeIdentifier: ident, escapeLiteral: literal } = pg;

// Operator-only: this connection must never be supplied to the CMS runtime.
// CREATE DATABASE cannot run in a transaction; the advisory lock serializes
// retries. Each operation is idempotent and existing unexpected ownership fails.
export async function provisionPostgres({
  admin,
  coreDatabase,
  coreRole,
  password,
}) {
  if (
    !coreDatabase ||
    !coreRole ||
    coreDatabase === "emdash" ||
    coreRole === "emdash"
  ) {
    throw new Error("invalid_core_target");
  }
  if (typeof password !== "string" || password.length < 32) {
    throw new Error("cms_password_too_short");
  }
  const client = await admin.connect();
  try {
    await client.query("SELECT pg_advisory_lock(174405, 1)");
    const core = await client.query(
      "SELECT pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname=$1",
      [coreDatabase],
    );
    if (core.rows[0]?.owner !== coreRole)
      throw new Error("unexpected_core_owner");
    const role = await client.query(
      "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname='emdash'",
    );
    if (role.rows.some((row) => Object.values(row).some(Boolean))) {
      throw new Error("unsafe_existing_cms_role");
    }
    const memberships = await client.query(
      "SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='emdash') OR roleid=(SELECT oid FROM pg_roles WHERE rolname='emdash')",
    );
    if (memberships.rowCount) throw new Error("unexpected_cms_role_membership");
    const databases = await client.query(
      "SELECT datname, pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname='emdash' OR datdba=(SELECT oid FROM pg_roles WHERE rolname='emdash')",
    );
    if (
      databases.rows.some(
        (row) => row.datname !== "emdash" || row.owner !== "emdash",
      )
    ) {
      throw new Error("unexpected_cms_database_owner");
    }
    // Do not silently disconnect clients relying on PUBLIC instead of grants.
    const implicitClients = await client.query(
      "SELECT DISTINCT usename FROM pg_stat_activity WHERE datname=$1 AND usename<>$2 AND usename<>current_user AND usename<>'emdash'",
      [coreDatabase, coreRole],
    );
    if (implicitClients.rowCount)
      throw new Error("review_additional_core_clients");
    if (!role.rowCount)
      await client.query(
        "CREATE ROLE emdash LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
      );
    await client.query(`ALTER ROLE emdash LOGIN PASSWORD ${literal(password)}`);
    if (!databases.rowCount)
      await client.query("CREATE DATABASE emdash OWNER emdash");
    await client.query("REVOKE ALL ON DATABASE emdash FROM PUBLIC");
    await client.query(
      `GRANT CONNECT, TEMPORARY ON DATABASE ${ident(coreDatabase)} TO ${ident(coreRole)}`,
    );
    await client.query(
      `REVOKE CONNECT, TEMPORARY ON DATABASE ${ident(coreDatabase)} FROM PUBLIC`,
    );
    await client.query(
      `REVOKE ALL ON DATABASE ${ident(coreDatabase)} FROM emdash`,
    );
    const grants = await client.query(
      "SELECT has_database_privilege('emdash',$1,'CONNECT') AS core, has_database_privilege('emdash','emdash','CONNECT') AS cms",
      [coreDatabase],
    );
    if (grants.rows[0].core || !grants.rows[0].cms)
      throw new Error("cms_database_grants_invalid");
  } finally {
    await client.query("SELECT pg_advisory_unlock(174405, 1)");
    client.release();
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  if (!process.env.CMS_PROVISION_DATABASE_URL)
    throw new Error("operator_database_url_required");
  const admin = new Pool({
    connectionString: process.env.CMS_PROVISION_DATABASE_URL,
    connectionTimeoutMillis: 5000,
  });
  try {
    await provisionPostgres({
      admin,
      coreDatabase: process.env.CORE_POSTGRES_DB ?? "leonaid",
      coreRole: process.env.CORE_POSTGRES_USER ?? "leonaid",
      password: process.env.CMS_POSTGRES_PASSWORD,
    });
    console.log(
      "emdash-postgres: OK: dedicated database and least-privilege role provisioned",
    );
  } catch {
    // SQL errors can contain literal credentials or deployment identifiers.
    console.error(
      "emdash-postgres: FAILED: provisioning refused; inspect target/grants privately",
    );
    process.exitCode = 1;
  } finally {
    await admin.end();
  }
}
