import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import { setTimeout as delay } from "node:timers/promises";
import pg from "pg";

const sessions = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const races = JSON.parse(await readFile("/proof/race-sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const root = "/_emdash/api/content/campaign_pages";
async function call(path, token, method = "GET", body) {
  const encoded = body === undefined ? undefined : JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          Cookie: `__Host-leonaid_session=${token}`,
          Origin: "https://proxy:8443",
          "X-EmDash-Request": "1",
          ...(encoded
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(encoded),
              }
            : {}),
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", reject);
        response.on("end", () => {
          try {
            const text = Buffer.concat(chunks).toString("utf8");
            resolve({
              status: response.statusCode,
              body: text ? JSON.parse(text) : null,
            });
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    req.setTimeout(7000, () => req.destroy(new Error("race_http_timeout")));
    req.on("error", reject);
    req.end(encoded);
  });
}
const get = async (path) => {
  const result = await call(path, sessions.system);
  assert.equal(result.status, 200);
  return result.body;
};
const pool = new pg.Pool({
  max: 3,
  connectionTimeoutMillis: 2000,
  query_timeout: 2500,
});
try {
  const listing = await get(root);
  const entry = listing.data.items.find(
    (item) => item.data.action_id === "20000000-0000-4000-8000-000000000001",
  );
  assert.ok(entry);
  const path = `${root}/${entry.id}`;
  for (const operation of [
    "update",
    "restore",
    "discard",
    "publish",
    "unpublish",
    "create",
  ]) {
    const before = await get(path);
    const history = await get(`${path}/revisions`);
    const beforeList = await get(root);
    const token = races[operation];
    assert.equal((await call("/_emdash/api/auth/me", token)).status, 200);
    const creating = operation === "create";
    const actionId = "20000000-0000-4000-8000-000000000003";
    const target =
      operation === "update"
        ? path
        : operation === "restore"
          ? `/_emdash/api/revisions/${history.data.items[0].id}/restore`
          : operation === "discard"
            ? `${path}/discard-draft`
            : creating
              ? root
              : `${path}/${operation}`;
    const body =
      operation === "update"
        ? {
            _rev: before.data._rev,
            data: { title: "Must not survive Core revocation" },
          }
        : creating
          ? { data: { action_id: actionId, title: "Revoked creation" } }
          : undefined;
    const blocker = await pool.connect();
    let pending;
    let active = false;
    try {
      await blocker.query("BEGIN");
      active = true;
      const pid = (await blocker.query("SELECT pg_backend_pid() AS pid"))
        .rows[0].pid;
      if (creating) {
        await blocker.query(
          "SELECT pg_advisory_xact_lock(hashtextextended($1, 724381903))",
          [actionId],
        );
      } else {
        // Shared authorization reads can pass. Only the actual mutation's
        // FOR UPDATE is blocked; the test does not just delay initial auth.
        await blocker.query(
          "SELECT id FROM public.ec_campaign_pages WHERE id=$1 FOR SHARE",
          [entry.id],
        );
      }
      pending = call(
        target,
        token,
        operation === "update" ? "PUT" : "POST",
        body,
      );
      // Attach immediately so an HTTP failure cannot become unhandled while
      // the real PostgreSQL lock graph is inspected.
      void pending.catch(() => {});
      const deadline = Date.now() + 1500;
      let blocked = false;
      while (Date.now() < deadline) {
        const result = await pool.query(
          `SELECT query FROM pg_stat_activity
          WHERE datname=current_database() AND wait_event_type='Lock'
            AND $1::integer=ANY(pg_blocking_pids(pid))`,
          [pid],
        );
        blocked = result.rows.some((row) =>
          row.query
            .toLowerCase()
            .includes(creating ? "pg_advisory_xact_lock" : "for update"),
        );
        if (blocked) break;
        await delay(20);
      }
      assert.ok(
        blocked,
        `${operation}: actual mutation must be waiting on our database lock`,
      );
      assert.equal(
        (await call("/api/v1/auth/logout", token, "POST")).status,
        200,
      );
      assert.equal((await call("/api/v1/identity/me", token)).status, 401);
      await blocker.query("COMMIT");
      active = false;
      const response = await pending;
      assert.equal(
        response.status,
        401,
        `${operation}: revoked session must not mutate after lock wait`,
      );
      assert.deepEqual(await get(path), before);
      assert.deepEqual(await get(`${path}/revisions`), history);
      assert.deepEqual(await get(root), beforeList);
      console.log(
        `campaign-auth-race: OK: ${operation}: real lock wait, Core logout, 401 and unchanged content/revisions`,
      );
    } finally {
      if (active) await blocker.query("ROLLBACK");
      blocker.release();
      if (pending) await Promise.allSettled([pending]);
    }
  }
} finally {
  await pool.end();
}
