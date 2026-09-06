import { randomBytes } from "node:crypto";

export class IdentityMappingError extends Error {
  constructor(code) {
    super(code);
    this.name = "IdentityMappingError";
    this.code = code;
  }
}

// User IDs remain valid ULIDs for upstream routes; Core UUIDs live separately.
function newUserId() {
  const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  let value =
    (BigInt(Date.now()) << 80n) |
    BigInt(`0x${randomBytes(10).toString("hex")}`);
  let id = "";
  for (let index = 0; index < 26; index++) {
    id = alphabet[Number(value & 31n)] + id;
    value >>= 5n;
  }
  return id;
}

async function requireCmsDatabase(client) {
  const { rows } = await client.query(
    "SELECT current_database() AS database, current_user AS role",
  );
  if (rows[0].database !== "emdash" || rows[0].role !== "emdash") {
    throw new IdentityMappingError("cms_database_required");
  }
}

async function connect(pool) {
  try {
    return await pool.connect();
  } catch {
    throw new IdentityMappingError("identity_store_unavailable");
  }
}

// Operator-only schema installation, after EmDash migrations and before HTTP.
// Never called from authentication; an absent table fails closed at runtime.
export async function installIdentityMapping(pool) {
  const client = await connect(pool);
  try {
    await requireCmsDatabase(client);
    await client.query(`CREATE TABLE IF NOT EXISTS leonaid_external_identity (
      core_user_id uuid PRIMARY KEY,
      cms_user_id text NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT
    )`);
    const { rows } = await client.query(`
      SELECT pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c
      WHERE c.conrelid='leonaid_external_identity'::regclass
      ORDER BY c.contype`);
    const expected = [
      "FOREIGN KEY (cms_user_id) REFERENCES users(id) ON DELETE RESTRICT",
      "PRIMARY KEY (core_user_id)",
      "UNIQUE (cms_user_id)",
    ];
    const columns = await client.query(`
      SELECT column_name, data_type, is_nullable FROM information_schema.columns
      WHERE table_schema=current_schema() AND table_name='leonaid_external_identity'
      ORDER BY ordinal_position`);
    if (
      JSON.stringify(rows.map((row) => row.definition)) !==
        JSON.stringify(expected) ||
      JSON.stringify(columns.rows) !==
        JSON.stringify([
          { column_name: "core_user_id", data_type: "uuid", is_nullable: "NO" },
          { column_name: "cms_user_id", data_type: "text", is_nullable: "NO" },
        ])
    ) {
      throw new IdentityMappingError("identity_schema_mismatch");
    }
  } catch (error) {
    if (error instanceof IdentityMappingError) throw error;
    throw new IdentityMappingError("identity_migration_failed");
  } finally {
    client.release();
  }
}

/**
 * Internal boundary: input MUST come from current validated Core /identity/me,
 * never request headers, a form, an EmDash session or an email lookup.
 * Campaign authorization is a separate mandatory layer above this mapper.
 */
export async function synchronizeExternalIdentity(pool, profile) {
  const { coreUserId, email, name, role } = profile;
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      coreUserId,
    ) ||
    typeof email !== "string" ||
    email.length > 320 ||
    !/^[^\s@]+@[^\s@]+$/.test(email) ||
    email !== email.toLowerCase() ||
    typeof name !== "string" ||
    !name.trim() ||
    name.length > 400 ||
    ![40, 50].includes(role)
  ) {
    throw new IdentityMappingError("invalid_core_profile");
  }
  const client = await connect(pool);
  let transaction = false;
  let discard = false;
  try {
    await requireCmsDatabase(client);
    await client.query("BEGIN");
    transaction = true;
    await client.query("SET LOCAL lock_timeout = '2s'");
    await client.query("SET LOCAL statement_timeout = '3s'");
    // Serializes identity provisioning/update only, not editorial transactions.
    await client.query("SELECT pg_advisory_xact_lock(724381901)");
    const existing = await client.query(
      "SELECT cms_user_id FROM leonaid_external_identity WHERE core_user_id=$1",
      [coreUserId],
    );
    let cmsUserId = existing.rows[0]?.cms_user_id;
    if (!cmsUserId) {
      const mappings = await client.query(
        "SELECT 1 FROM leonaid_external_identity LIMIT 1",
      );
      if (!mappings.rowCount && role !== 50) {
        throw new IdentityMappingError("system_admin_bootstrap_required");
      }
      cmsUserId = newUserId();
      // Unique email conflicts deliberately deny instead of linking accounts.
      await client.query(
        `INSERT INTO users (id,email,name,role,email_verified,disabled,created_at,updated_at)
         VALUES ($1,$2,$3,$4,1,0,$5,$5)`,
        [cmsUserId, email, name, role, new Date().toISOString()],
      );
      await client.query(
        "INSERT INTO leonaid_external_identity (core_user_id,cms_user_id) VALUES ($1,$2)",
        [coreUserId, cmsUserId],
      );
    } else {
      const updated = await client.query(
        `UPDATE users SET email=$2,name=$3,role=$4,disabled=0,updated_at=$5
         WHERE id=$1 RETURNING id`,
        [cmsUserId, email, name, role, new Date().toISOString()],
      );
      if (updated.rowCount !== 1) {
        throw new IdentityMappingError("identity_mapping_missing_user");
      }
    }
    await client.query("COMMIT");
    transaction = false;
    return { coreUserId, cmsUserId, role };
  } catch (error) {
    if (transaction) {
      try {
        await client.query("ROLLBACK");
      } catch {
        discard = true;
      }
    }
    if (error instanceof IdentityMappingError) throw error;
    // pg error detail can include email or database information; never rethrow it.
    throw new IdentityMappingError(
      error?.code === "23505"
        ? "identity_conflict"
        : "identity_store_unavailable",
    );
  } finally {
    client.release(discard);
  }
}
