import { pathToFileURL } from "node:url";
import pg from "pg";
import { provisionPostgres } from "../../apps/campaign-site/src/provision-postgres.mjs";

// The operator library ships in the campaign-site image (pilot-cms-provision);
// this spike CLI and the spike proofs keep importing it from here.
export { provisionPostgres };

const { Pool } = pg;

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
