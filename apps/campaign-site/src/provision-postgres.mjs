import { createHash, createHmac, pbkdf2Sync, randomBytes } from "node:crypto";
import pg from "pg";

const { escapeIdentifier: ident, escapeLiteral: literal } = pg;

// RFC 5802/7677 SCRAM-SHA-256 verifier, computed here so the plaintext CMS
// password never reaches the server: a failing ALTER ROLE statement (lock
// timeout, concurrent DDL) is logged with its text, and pg_stat_activity
// shows it while it runs. The generated passwords are printable ASCII, for
// which SASLprep is the identity.
export function scramSha256Verifier(password, salt = randomBytes(16)) {
  if (!/^[\x21-\x7e]+$/.test(password))
    throw new Error("cms_password_not_printable_ascii");
  const iterations = 4096;
  const salted = pbkdf2Sync(password, salt, iterations, 32, "sha256");
  const clientKey = createHmac("sha256", salted).update("Client Key").digest();
  const storedKey = createHash("sha256").update(clientKey).digest();
  const serverKey = createHmac("sha256", salted).update("Server Key").digest();
  return `SCRAM-SHA-256$${iterations}:${salt.toString("base64")}$${storedKey.toString("base64")}:${serverKey.toString("base64")}`;
}

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
    await client.query(
      `ALTER ROLE emdash LOGIN PASSWORD ${literal(scramSha256Verifier(password))}`,
    );
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
