import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import { setTimeout as delay } from "node:timers/promises";
import pg from "pg";
import sharp from "sharp";
import { createStorage } from "emdash/storage/s3";

const sessions = JSON.parse(
  await readFile("/proof/race-sessions.json", "utf8"),
);
const ca = await readFile("/proof/root.crt");
const pool = new pg.Pool({
  max: 3,
  connectionTimeoutMillis: 2000,
  query_timeout: 2500,
});
const storage = createStorage({});
const root = "/_emdash/api/media";
const action = "20000000-0000-4000-8000-000000000001";
const image = await sharp({
  create: { width: 4, height: 3, channels: 3, background: "red" },
})
  .png()
  .toBuffer();
async function call(path, token, method = "GET", body) {
  const bytes =
    body === undefined
      ? undefined
      : Buffer.isBuffer(body)
        ? body
        : Buffer.from(JSON.stringify(body));
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
          ...(bytes
            ? {
                "Content-Type": Buffer.isBuffer(body)
                  ? "image/png"
                  : "application/json",
                "Content-Length": bytes.length,
              }
            : {}),
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", reject);
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            body: JSON.parse(Buffer.concat(chunks).toString() || "null"),
          }),
        );
      },
    );
    req.setTimeout(15000, () => req.destroy(new Error("media_race_timeout")));
    req.on("error", reject);
    req.end(bytes);
  });
}
const snapshot = async (id) => ({
  media: (await pool.query("SELECT * FROM public.media WHERE id=$1", [id]))
    .rows,
  attempts: (
    await pool.query(
      "SELECT * FROM public._emdash_media_upload_attempts WHERE media_id=$1 ORDER BY storage_key",
      [id],
    )
  ).rows,
  objects: (await storage.list()).files.map((item) => item.key).sort(),
});
try {
  for (const operation of ["upload-start", "upload-link", "confirm"]) {
    const token = sessions[operation];
    const reserved = await call(
      `${root}/upload-url?campaign=${action}`,
      token,
      "POST",
      {
        filename: `synthetic-race-${operation}.png`,
        contentType: "image/png",
        size: image.length,
      },
    );
    assert.equal(reserved.status, 200);
    const { mediaId, uploadUrl } = reserved.body.data;
    if (operation === "confirm")
      assert.equal((await call(uploadUrl, token, "PUT", image)).status, 200);
    const before = await snapshot(mediaId);
    const blocker = await pool.connect();
    let active = false;
    let pending;
    let trigger = false;
    try {
      if (operation === "upload-link") {
        // Pause the real upload after initial Core authorization but before
        // object PUT/final linking. This tests the SECOND authority check.
        await pool.query(`CREATE FUNCTION public.synthetic_media_race() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN PERFORM pg_advisory_xact_lock(724381906); RETURN NEW; END; $$`);
        await pool.query(`CREATE TRIGGER synthetic_media_race AFTER INSERT ON public._emdash_media_upload_attempts
          FOR EACH ROW EXECUTE FUNCTION public.synthetic_media_race()`);
        trigger = true;
      }
      await blocker.query("BEGIN");
      active = true;
      const pid = (await blocker.query("SELECT pg_backend_pid() AS pid"))
        .rows[0].pid;
      if (operation === "upload-link")
        await blocker.query("SELECT pg_advisory_xact_lock(724381906)");
      else
        await blocker.query(
          "SELECT id FROM public.media WHERE id=$1 FOR SHARE",
          [mediaId],
        );
      pending = call(
        operation === "confirm" ? `${root}/${mediaId}/confirm` : uploadUrl,
        token,
        operation === "confirm" ? "POST" : "PUT",
        operation === "confirm" ? {} : image,
      );
      void pending.catch(() => {});
      let waiting = false;
      const deadline = Date.now() + 1500;
      while (Date.now() < deadline) {
        const result = await pool.query(
          `SELECT query FROM pg_stat_activity WHERE datname=current_database()
          AND wait_event_type='Lock' AND $1::integer=ANY(pg_blocking_pids(pid))`,
          [pid],
        );
        waiting = result.rows.some((row) =>
          row.query
            .toLowerCase()
            .includes(
              operation === "upload-link" ? "insert into" : "for update",
            ),
        );
        if (waiting) break;
        await delay(20);
      }
      assert.ok(
        waiting,
        `${operation}: actual mutation must wait on our database lock`,
      );
      assert.equal(
        (await call("/api/v1/auth/logout", token, "POST")).status,
        200,
      );
      assert.equal((await call("/api/v1/identity/me", token)).status, 401);
      await blocker.query("COMMIT");
      active = false;
      assert.equal(
        (await pending).status,
        401,
        `${operation}: Core revocation must win`,
      );
      assert.deepEqual(await snapshot(mediaId), before);
      console.log(
        `campaign-media-auth-race: ${operation}: real Charity session, database wait, actual Core logout, 401 and unchanged SQL/attempt/object state`,
      );
    } finally {
      if (active) await blocker.query("ROLLBACK");
      blocker.release();
      if (pending) await Promise.allSettled([pending]);
      if (trigger) {
        await pool.query(
          "DROP TRIGGER synthetic_media_race ON public._emdash_media_upload_attempts",
        );
        await pool.query("DROP FUNCTION public.synthetic_media_race()");
      }
    }
  }
} finally {
  await pool.end();
}
