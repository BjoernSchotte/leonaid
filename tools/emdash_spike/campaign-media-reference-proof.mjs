import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import { setTimeout as delay } from "node:timers/promises";
import pg from "pg";
import sharp from "sharp";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
Object.assign(
  tokens,
  JSON.parse(await readFile("/proof/reference-sessions.json", "utf8")),
);
const media = JSON.parse(
  await readFile("/proof/media-http-state.json", "utf8"),
);
const ca = await readFile("/proof/root.crt");
const pool = new pg.Pool({
  max: 2,
  connectionTimeoutMillis: 2000,
  query_timeout: 3000,
});
const root = "/_emdash/api/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
const newAction = "20000000-0000-4000-8000-000000000041";
async function call(actor, path, status = 200, method = "GET", body) {
  const bytes =
    body === undefined
      ? undefined
      : Buffer.isBuffer(body)
        ? body
        : Buffer.from(JSON.stringify(body));
  const response = await new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          Cookie: `__Host-leonaid_session=${tokens[actor]}`,
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
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("error", reject);
        res.on("end", () =>
          resolve({
            status: res.statusCode,
            headers: res.headers,
            text: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(15000, () =>
      req.destroy(new Error("reference_proof_timeout")),
    );
    req.on("error", reject);
    req.end(bytes);
  });
  assert.equal(response.status, status, `${actor} ${method} ${path}`);
  assert.equal(response.headers["cache-control"], "no-store");
  if (!path.startsWith("/api/v1/"))
    assert.equal(response.headers["set-cookie"], undefined);
  if (status === 403) {
    assert.ok(!response.text.includes(media.foreign.id));
    assert.ok(!response.text.includes(media.foreign.storageKey));
  }
  return JSON.parse(response.text).data;
}

const snapshot = async () => ({
  entries: (
    await pool.query("SELECT * FROM public.ec_campaign_pages ORDER BY id")
  ).rows,
  revisions: (await pool.query("SELECT * FROM public.revisions ORDER BY id"))
    .rows,
  media: (await pool.query("SELECT * FROM public.media ORDER BY id")).rows,
});

async function lateWriteRevocation(actor, path, method, body) {
  // Native creation inserts the content row directly; later edits insert a
  // draft revision. Block the actual write in each path, not an assumed hook.
  const table = method === "POST" ? "ec_campaign_pages" : "revisions";
  const before = await snapshot();
  const blocker = await pool.connect();
  let active = false;
  let pending;
  let trigger = false;
  try {
    await pool.query(`CREATE FUNCTION public.synthetic_reference_race() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN PERFORM pg_advisory_xact_lock(724381907); RETURN NEW; END; $$`);
    await pool.query(`CREATE TRIGGER synthetic_reference_race AFTER INSERT ON public.${table}
      FOR EACH ROW EXECUTE FUNCTION public.synthetic_reference_race()`);
    trigger = true;
    await blocker.query("BEGIN");
    active = true;
    const pid = (await blocker.query("SELECT pg_backend_pid() AS pid")).rows[0]
      .pid;
    await blocker.query("SELECT pg_advisory_xact_lock(724381907)");
    pending = call(actor, path, 401, method, body);
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
        row.query.toLowerCase().includes("insert into"),
      );
      if (waiting) break;
      await delay(20);
    }
    assert.ok(
      waiting,
      `${actor}: real ${table} write must wait after initial Core authorization`,
    );
    await call(actor, "/api/v1/auth/logout", 200, "POST");
    await call(actor, "/api/v1/identity/me", 401);
    await blocker.query("COMMIT");
    active = false;
    await pending;
    assert.deepEqual(await snapshot(), before);
    console.log(
      `campaign-reference-late-race: ${actor}: actual ${table} INSERT wait, Core logout, 401 and complete SQL rollback`,
    );
  } finally {
    if (active) await blocker.query("ROLLBACK");
    blocker.release();
    if (pending) await Promise.allSettled([pending]);
    if (trigger)
      await pool.query(
        `DROP TRIGGER synthetic_reference_race ON public.${table}`,
      );
    await pool.query(
      "DROP FUNCTION IF EXISTS public.synthetic_reference_race()",
    );
  }
}

try {
  // Even two actions belonging to the SAME Charity actor cannot share a media
  // binding. Rejected creation must not consume the new campaign's unique slot.
  const initial = await call("charity", root);
  const create = {
    data: {
      action_id: newAction,
      title: "Synthetic image creation",
      hero_image: { id: media.ready.id },
    },
  };
  await call("charity", root, 403, "POST", create);
  await call("system", root, 403, "POST", create);
  await call("charity", root, 403, "POST", {
    data: {
      action_id: newAction,
      title: "Synthetic foreign logo",
      brand_logo: { id: media.ready.id },
    },
  });
  assert.deepEqual(await call("charity", root), initial);
  const image = await sharp({
    create: { width: 5, height: 3, channels: 3, background: "blue" },
  })
    .png()
    .toBuffer();
  const reserved = await call(
    "charity",
    `/_emdash/api/media/upload-url?campaign=${newAction}`,
    200,
    "POST",
    {
      filename: "synthetic-created-reference.png",
      contentType: "image/png",
      size: image.length,
    },
  );
  await call("charity", reserved.uploadUrl, 200, "PUT", image);
  await call(
    "charity",
    `/_emdash/api/media/${reserved.mediaId}/confirm`,
    200,
    "POST",
    {},
  );
  create.data.hero_image = { id: reserved.mediaId };
  await lateWriteRevocation("reference-create", root, "POST", create);
  const created = await call("charity", root, 201, "POST", create);
  assert.equal(created.item.status, "draft");
  assert.equal(created.item.data.hero_image.id, reserved.mediaId);
  assert.equal(
    (await call("charity", `${root}/${created.item.id}`)).item.data.hero_image
      .id,
    reserved.mediaId,
  );
  await call("charity_b", `${root}/${created.item.id}`, 404);

  const page = initial.items.find((item) => item.data.action_id === action);
  const pagePath = `${root}/${page.id}`;
  const original = await call("charity", pagePath);
  const revisionId = original.item.draftRevisionId;
  assert.ok(revisionId);
  await lateWriteRevocation("reference-update", pagePath, "PUT", {
    _rev: original._rev,
    data: { title: "Synthetic revoked late update" },
  });
  const before = await snapshot();
  const stored = before.revisions.find(
    (revision) => revision.id === revisionId,
  );
  assert.ok(stored);
  const data =
    typeof stored.data === "string" ? JSON.parse(stored.data) : stored.data;
  const poisoned = {
    ...data,
    hero_image: {
      id: media.foreign.id,
      provider: "local",
      meta: { storageKey: media.foreign.storageKey },
    },
  };
  // Actual stored-revision corruption, not an HTTP stub. Keep the immutable
  // parent/action intact so media-reference checks are the protection under test.
  await pool.query("UPDATE public.revisions SET data=$1 WHERE id=$2", [
    JSON.stringify(poisoned),
    revisionId,
  ]);
  try {
    const corrupt = await snapshot();
    for (const actor of ["charity", "system"]) {
      for (const [path, method] of [
        [pagePath, "GET"],
        [`${pagePath}/revisions`, "GET"],
        [`/_emdash/api/revisions/${revisionId}`, "GET"],
        [`${pagePath}/compare`, "GET"],
        [`/_emdash/api/revisions/${revisionId}/restore`, "POST"],
        [`${pagePath}/publish`, "POST"],
      ])
        await call(
          actor,
          path,
          403,
          method,
          method === "POST" ? {} : undefined,
        );
    }
    assert.deepEqual(await snapshot(), corrupt);
    assert.equal(
      (await call("charity_b", `/_emdash/api/media/${media.foreign.id}`)).item
        .id,
      media.foreign.id,
    );
  } finally {
    await pool.query("UPDATE public.revisions SET data=$1 WHERE id=$2", [
      stored.data,
      revisionId,
    ]);
  }
  assert.deepEqual(await snapshot(), before);
  assert.deepEqual(await call("charity", pagePath), original);
  console.log(
    "campaign-media-reference-storage: OK: same-actor cross-action and System Admin foreign-image creation denied without consuming binding; actual native image creation succeeded; real poisoned revision cannot be read, compared, restored or published by either admin role; SQL/media unchanged and explicit fixture restore recovered access",
  );
} finally {
  await pool.end();
}
