import pg from "pg";

// A separate small, bounded pool keeps health requests from exhausting the CMS
// request pool. All connection values come from runtime PG* environment vars.
const pool = new pg.Pool({
  max: 1,
  connectionTimeoutMillis: 1500,
  query_timeout: 1500,
  statement_timeout: 1500,
  idleTimeoutMillis: 5000,
});
pool.on("error", () => {
  // Do not log connection details or credentials. Readiness reports only 503.
});

export async function databaseReady(): Promise<boolean> {
  if (process.env.PGDATABASE !== "emdash" || process.env.PGUSER !== "emdash") {
    return false;
  }
  try {
    await pool.query("SELECT 1");
    return true;
  } catch {
    return false;
  }
}
