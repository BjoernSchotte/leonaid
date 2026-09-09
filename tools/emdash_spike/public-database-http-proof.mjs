import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import { setTimeout as delay } from "node:timers/promises";
import pg from "pg";

const ca = await readFile("/proof/root.crt");
const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const media = JSON.parse(await readFile("/proof/public-media.json", "utf8"));
const pool = new pg.Pool({
  max: 2,
  connectionTimeoutMillis: 2000,
  query_timeout: 3000,
});
const pagePath = "/campaigns/krapfentaxi-2026/";
async function get(path, authenticated = false) {
  return new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        headers: authenticated
          ? { Cookie: `__Host-leonaid_session=${tokens.system}` }
          : {},
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", reject);
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            bytes: Buffer.concat(chunks),
          }),
        );
      },
    );
    req.on("error", reject);
    req.setTimeout(12000, () =>
      req.destroy(new Error("public_database_http_timeout")),
    );
    req.end();
  });
}
try {
  for (const table of ["options", "ec_campaign_pages"]) {
    const blocker = await pool.connect();
    let transaction = false;
    let pending;
    try {
      await blocker.query("BEGIN");
      transaction = true;
      // Fixed table names only, in this test project's synthetic CMS database.
      await blocker.query(
        `LOCK TABLE public.${table} IN ACCESS EXCLUSIVE MODE`,
      );
      const pid = (await blocker.query("SELECT pg_backend_pid() AS pid"))
        .rows[0].pid;
      const started = performance.now();
      pending = Promise.all([get(pagePath), get(media.url)]);
      void pending.catch(() => {});
      let waiting = false;
      const deadline = performance.now() + 1200;
      while (performance.now() < deadline) {
        const activity = await pool.query(
          `SELECT query FROM pg_stat_activity
          WHERE datname=current_database() AND wait_event_type='Lock'
          AND $1::integer=ANY(pg_blocking_pids(pid))`,
          [pid],
        );
        waiting = activity.rows.some((row) =>
          row.query.toLowerCase().includes(table),
        );
        if (waiting) break;
        await delay(20);
      }
      assert.ok(
        waiting,
        "the actual public SQL read must wait on the fixture lock",
      );
      // The shared PostgreSQL server remains useful to Core during CMS failure.
      assert.equal((await get("/api/v1/identity/me", true)).status, 200);
      const core = await get(
        "/api/v1/public/actions/campaign/krapfentaxi-2026",
      );
      assert.equal(core.status, 200);
      for (const result of await pending) {
        assert.equal(result.status, 503);
        assert.equal(result.headers["cache-control"], "no-store");
        assert.equal(result.headers["set-cookie"], undefined);
        assert.notEqual(result.headers["content-type"], "image/png");
        const body = result.bytes.toString();
        for (const privateValue of [
          "PRIVATE_DRAFT_PROOF",
          "PUBLIC_STORY_PROOF",
          "storage_key",
          "pg_stat_activity",
          "statement timeout",
        ])
          assert.ok(!body.includes(privateValue));
      }
      assert.ok(
        performance.now() - started < 6000,
        "locked CMS reads must fail within the HTTP budget",
      );
      await blocker.query("ROLLBACK");
      transaction = false;
      assert.equal((await get(pagePath)).status, 200);
      assert.equal((await get(media.url)).status, 200);
      console.log(
        `public-database-http: ${table} real lock, bounded sanitized page/media 503, Core reads available and recovery passed`,
      );
    } finally {
      if (transaction) await blocker.query("ROLLBACK");
      blocker.release();
      if (pending) await Promise.allSettled([pending]);
    }
  }
} finally {
  await pool.end();
}
