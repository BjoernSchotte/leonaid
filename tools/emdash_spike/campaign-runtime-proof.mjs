import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const revoked = process.argv.includes("--revoked");
const guardUnavailable = process.argv.includes("--guard-unavailable");
async function call(
  path,
  status,
  {
    token = tokens.system,
    method = "GET",
    origin = "https://proxy:8443",
    extra = {},
    body,
    marker = true,
  } = {},
) {
  const encoded = body === undefined ? undefined : JSON.stringify(body);
  const response = await new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          ...(token ? { Cookie: `__Host-leonaid_session=${token}` } : {}),
          Origin: origin,
          ...(marker ? { "X-EmDash-Request": "1" } : {}),
          ...(encoded
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(encoded),
              }
            : {}),
          ...extra,
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(6000, () => req.destroy(new Error("CMS HTTP deadline")));
    req.on("error", reject);
    req.end(encoded);
  });
  if (Array.isArray(status))
    assert.ok(
      status.includes(response.status),
      `${method} ${path}: unexpected status ${response.status}`,
    );
  else
    assert.equal(
      response.status,
      status,
      `${method} ${path}: unexpected status`,
    );
  assert.equal(response.headers["cache-control"], "no-store");
  assert.equal(response.headers["set-cookie"], undefined);
  const payload = response.headers["content-type"]?.includes("application/json")
    ? JSON.parse(response.body)
    : null;
  return Array.isArray(status) ? { status: response.status, payload } : payload;
}
const root = "/_emdash/api/content/campaign_pages";
if (guardUnavailable) {
  await call(root, 503);
  await call(`${root}/00000000000000000000000000/compare`, 503);
  await call(`${root}/00000000000000000000000000/discard-draft`, 503, {
    method: "POST",
  });
  await call("/_emdash/api/revisions/00000000000000000000000000/restore", 503, {
    method: "POST",
  });
  await call(`${root}/00000000000000000000000000`, 503, {
    method: "PUT",
    body: { _rev: "synthetic", data: { title: "denied" } },
  });
} else if (revoked) {
  await call(root, 401);
  await call(`${root}/00000000000000000000000000/compare`, 401);
  await call(`${root}/00000000000000000000000000/discard-draft`, 401, {
    method: "POST",
  });
  await call("/_emdash/api/revisions/00000000000000000000000000/restore", 401, {
    method: "POST",
  });
  await call(`${root}/00000000000000000000000000`, 401, {
    method: "PUT",
    body: { _rev: "synthetic", data: { title: "denied" } },
  });
} else if (process.argv.includes("--discard-failure")) {
  const listing = await call(root, 200);
  const path = `${root}/${listing.data.items[0].id}`;
  const before = await call(path, 200);
  assert.ok(before.data.item.draftRevisionId);
  const history = await call(`${path}/revisions`, 200);
  const comparison = await call(`${path}/compare`, 200);
  await call(`${path}/discard-draft`, 503, { method: "POST" });
  assert.deepEqual(await call(path, 200), before);
  assert.deepEqual(await call(`${path}/revisions`, 200), history);
  assert.deepEqual(await call(`${path}/compare`, 200), comparison);
  console.log(
    "campaign-runtime: deferred database commit failure rolls back discard",
  );
} else if (process.argv.includes("--late-write-failure")) {
  const listing = await call(root, 200);
  const path = `${root}/${listing.data.items[0].id}`;
  const before = await call(path, 200);
  const history = await call(`${path}/revisions`, 200);
  await call(path, 503, {
    method: "PUT",
    body: { _rev: before.data._rev, data: { title: "must roll back" } },
  });
  assert.deepEqual(await call(path, 200), before);
  assert.deepEqual(await call(`${path}/revisions`, 200), history);
  await call(
    `/_emdash/api/revisions/${history.data.items[0].id}/restore`,
    503,
    { method: "POST" },
  );
  assert.deepEqual(await call(path, 200), before);
  assert.deepEqual(await call(`${path}/revisions`, 200), history);
  console.log(
    "campaign-runtime: late database failure rolls back content and revisions",
  );
} else {
  const result = await call(root, 200);
  assert.equal(result.data.total, 4);
  assert.equal(result.data.items.length, 4);
  for (const entry of result.data.items) {
    const path = `${root}/${entry.id}`;
    const item = await call(path, 200);
    assert.equal(item.data.item.id, entry.id);
    const revisions = await call(`${path}/revisions`, 200);
    assert.ok(revisions.data.total > 0);
    const draft = revisions.data.items.find(
      (revision) => revision.id === item.data.item.draftRevisionId,
    );
    assert.ok(draft);
    assert.equal(item.data.item.data.title, draft.data.title);
    assert.equal(item.data.item.liveData.title, entry.data.title);
    const compared = await call(`${path}/compare`, 200);
    assert.equal(compared.data.hasChanges, true);
    assert.deepEqual(compared.data.draft, draft.data);
    assert.deepEqual(compared.data.live, item.data.item.liveData);
    await call(`${path}/compare`, 401, { token: null });
    await call(`${path}/compare`, 403, { token: tokens.charity });
    assert.notEqual(item.data.item.data.title, item.data.item.liveData.title);
    for (const revision of revisions.data.items) {
      const detail = await call(`/_emdash/api/revisions/${revision.id}`, 200);
      assert.equal(detail.data.item.entryId, entry.id);
      await call(`/_emdash/api/revisions/${revision.id}`, 401, { token: null });
      await call(`/_emdash/api/revisions/${revision.id}`, 403, {
        token: tokens.charity,
      });
    }
    await call(path, 401, { token: null });
    await call(path, 403, { token: tokens.charity });
  }
  const entry = result.data.items[0];
  const path = `${root}/${entry.id}`;
  const before = await call(path, 200);
  const revisionsBefore = await call(`${path}/revisions`, 200);
  const body = {
    _rev: before.data._rev,
    data: {
      title: `${entry.data.title} HTTP edit`,
      action_id: entry.data.action_id,
    },
  };
  for (const options of [
    { token: null },
    { token: tokens.charity },
    { origin: "https://attacker.invalid" },
    { marker: false },
  ])
    await call(path, options.token === null ? 401 : 403, {
      method: "PUT",
      body,
      ...options,
    });
  await call(path, 403, {
    method: "PUT",
    body: {
      ...body,
      data: { ...body.data, action_id: "20000000-0000-4000-8000-000000000099" },
    },
  });
  await call(path, 400, {
    method: "PUT",
    body: { ...body, status: "published" },
  });
  await call(path, 403, {
    method: "PUT",
    body: { ...body, status: "draft" },
  });
  await call(path, 403, { method: "PUT", body: { data: body.data } });
  await call(path, 403, {
    method: "PUT",
    body: { ...body, authorId: "00000000000000000000000000" },
  });
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    revisionsBefore.data.total,
  );
  const edited = await call(path, 200, { method: "PUT", body });
  assert.equal(edited.data.item.data.title, body.data.title);
  const after = await call(path, 200);
  const identity = await call("/_emdash/api/auth/me", 200);
  const savedRevision = await call(
    `/_emdash/api/revisions/${after.data.item.draftRevisionId}`,
    200,
  );
  assert.equal(savedRevision.data.item.authorId, identity.data.id);
  assert.equal(after.data.item.authorId, before.data.item.authorId);
  assert.equal(after.data.item.data.title, body.data.title);
  assert.equal(after.data.item.liveData.title, entry.data.title);
  assert.equal(after.data.item.status, "published");
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    revisionsBefore.data.total + 1,
  );
  await call(path, 409, {
    method: "PUT",
    body: { ...body, data: { title: "stale revision must not write" } },
  });
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    revisionsBefore.data.total + 1,
  );
  assert.equal((await call(path, 200)).data.item.data.title, body.data.title);
  for (let round = 0; round < 5; round++) {
    const current = await call(path, 200);
    const history = await call(`${path}/revisions`, 200);
    const attempts = await Promise.all(
      Array.from({ length: 4 }, (_, index) =>
        call(path, [200, 409], {
          method: "PUT",
          body: {
            _rev: current.data._rev,
            data: { title: `concurrent draft ${round}-${index}` },
          },
        }),
      ),
    );
    assert.equal(
      attempts.filter((attempt) => attempt.status === 200).length,
      1,
      "Exactly one same-revision write may succeed",
    );
    assert.equal(
      (await call(`${path}/revisions`, 200)).data.total,
      history.data.total + 1,
    );
    const winner = attempts.find((attempt) => attempt.status === 200);
    const stored = await call(path, 200);
    assert.equal(
      stored.data.item.data.title,
      winner.payload.data.item.data.title,
    );
    assert.equal(stored.data.item.liveData.title, entry.data.title);
  }
  const restoreTarget = revisionsBefore.data.items.find(
    (revision) => revision.id === before.data.item.draftRevisionId,
  );
  assert.ok(restoreTarget);
  const restorePath = `/_emdash/api/revisions/${restoreTarget.id}/restore`;
  const preRestore = await call(path, 200);
  const historyBeforeRestore = await call(`${path}/revisions`, 200);
  for (const options of [
    { token: null },
    { token: tokens.charity },
    { origin: "https://attacker.invalid" },
    { marker: false },
  ]) {
    await call(restorePath, options.token === null ? 401 : 403, {
      method: "POST",
      ...options,
    });
  }
  assert.deepEqual(await call(path, 200), preRestore);
  assert.deepEqual(await call(`${path}/revisions`, 200), historyBeforeRestore);
  const restored = await call(restorePath, 200, { method: "POST" });
  const restoredRead = await call(path, 200);
  assert.deepEqual(restored.data.item.data, restoreTarget.data);
  assert.deepEqual(restoredRead.data.item.data, restoreTarget.data);
  assert.deepEqual(
    restoredRead.data.item.liveData,
    preRestore.data.item.liveData,
  );
  assert.equal(restoredRead.data.item.status, preRestore.data.item.status);
  assert.equal(restoredRead.data.item.authorId, preRestore.data.item.authorId);
  assert.notEqual(restoredRead.data.item.draftRevisionId, restoreTarget.id);
  assert.notEqual(
    restoredRead.data.item.draftRevisionId,
    preRestore.data.item.draftRevisionId,
  );
  const restoredRevision = await call(
    `/_emdash/api/revisions/${restoredRead.data.item.draftRevisionId}`,
    200,
  );
  assert.equal(restoredRevision.data.item.authorId, identity.data.id);
  assert.equal(restoredRevision.data.item.entryId, entry.id);
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    historyBeforeRestore.data.total + 1,
  );
  assert.deepEqual(
    (await call(`/_emdash/api/revisions/${restoreTarget.id}`, 200)).data.item,
    restoreTarget,
  );
  await call("/_emdash/api/revisions/00000000000000000000000000/restore", 404, {
    method: "POST",
  });
  const preDiscard = await call(path, 200);
  const historyBeforeDiscard = await call(`${path}/revisions`, 200);
  const comparisonBeforeDiscard = await call(`${path}/compare`, 200);
  for (const options of [
    { token: null },
    { token: tokens.charity },
    { origin: "https://attacker.invalid" },
    { marker: false },
  ]) {
    await call(`${path}/discard-draft`, options.token === null ? 401 : 403, {
      method: "POST",
      ...options,
    });
  }
  assert.deepEqual(await call(path, 200), preDiscard);
  await call(`${path}/discard-draft`, 200, { method: "POST" });
  const discarded = await call(path, 200);
  assert.equal(discarded.data.item.draftRevisionId, null);
  assert.deepEqual(discarded.data.item.data, preDiscard.data.item.liveData);
  assert.equal(discarded.data.item.status, preDiscard.data.item.status);
  assert.equal(discarded.data.item.authorId, preDiscard.data.item.authorId);
  assert.deepEqual((await call(`${path}/compare`, 200)).data, {
    hasChanges: false,
    live: comparisonBeforeDiscard.data.live,
    draft: null,
  });
  assert.deepEqual(await call(`${path}/revisions`, 200), historyBeforeDiscard);
  // Repeating discard is harmless; discarded revisions remain restorable.
  await call(`${path}/discard-draft`, 200, { method: "POST" });
  assert.deepEqual(await call(path, 200), discarded);
  await call(restorePath, 200, { method: "POST" });
  assert.deepEqual((await call(path, 200)).data.item.data, restoreTarget.data);
  await call(`${root}/00000000000000000000000000/compare`, 404);
  await call(`${root}/00000000000000000000000000/discard-draft`, 404, {
    method: "POST",
  });
  const missing = await call(`${root}/00000000000000000000000000`, 404);
  // Upstream includes the ID in its message. This static envelope verifies
  // that the request-local wrapper actually ran, not just the upstream reader.
  assert.equal(missing.error.message, "Content not found");
  await call("/_emdash/api/revisions/00000000000000000000000000", 404);
  await call(root, 401, { token: null });
  await call(root, 403, { token: tokens.charity });
  await call(root, 403, { origin: "https://attacker.invalid" });
  await call(root, 503, {
    extra: { Authorization: "Bearer synthetic-denied" },
  });
  for (const method of ["POST", "PUT", "DELETE", "HEAD", "OPTIONS"]) {
    await call(root, 503, { method });
  }
}
console.log(
  `campaign-runtime: ${guardUnavailable ? "disabled binding guard fails closed" : revoked ? "revocation" : process.argv.includes("--late-write-failure") ? "late-write rollback" : "real Core session, TLS, list/item/revision routes, attribution and denied actors"} passed`,
);
