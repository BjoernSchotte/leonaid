import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import { campaignManifest } from "../../apps/campaign-site/src/auth/campaign-manifest.mjs";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const root = "/_emdash/api/content/campaign_pages";
const action = (suffix) =>
  `20000000-0000-4000-8000-${String(suffix).padStart(12, "0")}`;
async function call(actor, path, status = 200, method = "GET", body) {
  const encoded = body === undefined ? undefined : JSON.stringify(body);
  const result = await new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          ...(tokens[actor]
            ? { Cookie: `__Host-leonaid_session=${tokens[actor]}` }
            : {}),
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
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            text: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(6000, () =>
      req.destroy(new Error("Isolation HTTP deadline")),
    );
    req.on("error", reject);
    req.end(encoded);
  });
  assert.equal(result.status, status, `${actor} ${method} ${path}`);
  assert.equal(result.headers["cache-control"], "no-store");
  assert.equal(result.headers["set-cookie"], undefined);
  return {
    ...result,
    json: result.headers["content-type"]?.includes("application/json")
      ? JSON.parse(result.text)
      : null,
  };
}
const data = async (actor, path) => (await call(actor, path)).json.data;

if (process.argv.includes("--revoked")) {
  for (const path of [root, "/_emdash/api/auth/me", "/_emdash/api/manifest"])
    await call("charity", path, 403);
  const all = await data("system", root);
  for (const entry of all.items.filter((item) =>
    [action(1), action(2), action(41)].includes(item.data.action_id),
  )) {
    const path = `${root}/${entry.id}`;
    const before = await data("system", path);
    const history = await data("system", `${path}/revisions`);
    for (const suffix of ["", "/revisions", "/compare"])
      await call("charity", path + suffix, 403);
    await call("charity", path, 403, "PUT", {
      _rev: before._rev,
      data: { title: "Revoked write denied" },
    });
    for (const operation of ["publish", "unpublish", "discard-draft"])
      await call("charity", `${path}/${operation}`, 403, "POST");
    for (const revision of history.items) {
      await call("charity", `/_emdash/api/revisions/${revision.id}`, 403);
      await call(
        "charity",
        `/_emdash/api/revisions/${revision.id}/restore`,
        403,
        "POST",
      );
    }
    await call(
      "charity",
      `/_emdash/admin/campaigns/${entry.data.action_id}`,
      403,
    );
    await call(
      "charity",
      `/_emdash/admin/content/campaign_pages/${entry.id}`,
      403,
    );
    assert.deepEqual(await data("system", path), before);
    assert.deepEqual(await data("system", `${path}/revisions`), history);
  }
  await call("charity", root, 403, "POST", {
    data: { action_id: action(41), title: "Revoked create denied" },
  });
  // Removing A's membership does not revoke B's independent Core authority.
  assert.equal((await data("charity_b", root)).total, 2);
  console.log(
    "campaign-isolation: real Core membership withdrawal denies A; B remains authorized",
  );
} else {
  const all = await data("system", root);
  assert.equal(all.total, 3);
  const byAction = new Map(
    all.items.map((item) => [item.data.action_id, item]),
  );
  for (const [actor, owned, foreign, expectedCount, newSuffix] of [
    ["charity", 1, 3, 2, 41],
    ["charity_b", 3, 1, 1, 42],
  ]) {
    const own = byAction.get(action(owned));
    const other = byAction.get(action(foreign));
    const ownPath = `${root}/${own.id}`;
    const foreignPath = `${root}/${other.id}`;
    const identity = await data(actor, "/_emdash/api/auth/me");
    assert.equal(identity.role, 40);
    assert.deepEqual(
      await data(actor, "/_emdash/api/manifest"),
      campaignManifest(),
    );
    await call(actor, "/_emdash/api/dashboard", 403);
    const home = await call(actor, "/_emdash/admin/", 303);
    assert.equal(
      home.headers.location,
      "/_emdash/admin/content/campaign_pages",
    );
    const list = await data(actor, root);
    assert.equal(list.total, expectedCount);
    assert.ok(
      list.items.every((item) => item.data.action_id !== action(foreign)),
    );
    const first = await data(actor, `${root}?limit=1`);
    assert.equal(first.total, expectedCount);
    assert.equal(first.items.length, 1);
    if (expectedCount === 2) {
      assert.ok(first.nextCursor);
      const second = await data(
        actor,
        `${root}?limit=1&cursor=${encodeURIComponent(first.nextCursor)}`,
      );
      assert.equal(second.total, expectedCount);
      assert.notEqual(second.items[0].id, first.items[0].id);
      assert.ok(
        second.items.every((item) => item.data.action_id !== action(foreign)),
      );
    }
    const beforeForeign = await data("system", foreignPath);
    const query = `${root}?q=${encodeURIComponent(beforeForeign.item.liveData?.title ?? beforeForeign.item.data.title)}`;
    assert.ok(
      (await data("system", query)).items.some((item) => item.id === other.id),
      "Search negative requires a matching real foreign record",
    );
    const search = await data(actor, query);
    assert.equal(search.total, 0);
    assert.deepEqual(search.items, []);
    const forgedFilter = await data(
      actor,
      `${root}?fieldFilters=${encodeURIComponent(JSON.stringify({ action_id: action(foreign) }))}`,
    );
    assert.equal(forgedFilter.total, expectedCount);
    assert.ok(
      forgedFilter.items.every(
        (item) => item.data.action_id !== action(foreign),
      ),
    );
    const foreignHistory = await data("system", `${foreignPath}/revisions`);
    const missing = (
      await call(actor, `${root}/00000000000000000000000000`, 404)
    ).json;
    for (const suffix of ["", "/revisions", "/compare"])
      assert.deepEqual(
        (await call(actor, `${foreignPath}${suffix}`, 404)).json,
        missing,
      );
    await call(actor, foreignPath, 404, "PUT", {
      _rev: beforeForeign._rev,
      data: { title: "Foreign overwrite denied" },
    });
    for (const operation of ["publish", "unpublish", "discard-draft"])
      await call(actor, `${foreignPath}/${operation}`, 404, "POST");
    for (const revision of foreignHistory.items) {
      await call(actor, `/_emdash/api/revisions/${revision.id}`, 404);
      await call(
        actor,
        `/_emdash/api/revisions/${revision.id}/restore`,
        404,
        "POST",
      );
    }
    await call(actor, `/_emdash/admin/campaigns/${action(foreign)}`, 403);
    await call(
      actor,
      `/_emdash/admin/content/campaign_pages/new?campaign=${action(foreign)}`,
      403,
    );
    await call(actor, "/_emdash/admin/content/campaign_pages/new", 403);
    await call(actor, root, 403, "POST", {
      data: { action_id: action(foreign), title: "Foreign create denied" },
    });
    assert.deepEqual(await data("system", foreignPath), beforeForeign);
    assert.deepEqual(
      await data("system", `${foreignPath}/revisions`),
      foreignHistory,
    );

    const before = await data(actor, ownPath);
    const history = await data(actor, `${ownPath}/revisions`);
    const target = history.items.find(
      (item) => item.id === before.item.draftRevisionId,
    );
    assert.ok(target);
    const title = `Synthetic ${actor} authorized draft`;
    await call(actor, ownPath, 200, "PUT", {
      _rev: before._rev,
      data: { title },
    });
    const draft = await data(actor, ownPath);
    assert.equal(draft.item.data.title, title);
    assert.deepEqual(draft.item.liveData, before.item.liveData);
    assert.equal(
      (
        await data(
          actor,
          `/_emdash/api/revisions/${draft.item.draftRevisionId}`,
        )
      ).item.authorId,
      identity.id,
    );
    assert.equal(
      (await data(actor, `${ownPath}/revisions`)).total,
      history.total + 1,
    );
    await data(actor, `${ownPath}/compare`);
    await call(
      actor,
      `/_emdash/api/revisions/${target.id}/restore`,
      200,
      "POST",
    );
    assert.deepEqual((await data(actor, ownPath)).item.data, target.data);
    await call(actor, `${ownPath}/discard-draft`, 200, "POST");
    const discarded = await data(actor, ownPath);
    assert.equal(discarded.item.draftRevisionId, null);
    await call(actor, ownPath, 200, "PUT", {
      _rev: discarded._rev,
      data: { title },
    });
    await call(actor, `${ownPath}/publish`, 200, "POST");
    const published = await data(actor, ownPath);
    assert.equal(published.item.status, "published");
    assert.equal(published.item.data.title, title);
    assert.equal(published.item.draftRevisionId, null);
    await call(actor, `${ownPath}/unpublish`, 200, "POST");
    assert.equal((await data(actor, ownPath)).item.status, "draft");
    await call(actor, `${ownPath}/publish`, 200, "POST");
    // Leave an actual draft for the native browser autosave/publish regression.
    const current = await data(actor, ownPath);
    await call(actor, ownPath, 200, "PUT", {
      _rev: current._rev,
      data: { title: `${title} private` },
    });
    const handoff = await call(
      actor,
      `/_emdash/admin/campaigns/${action(newSuffix)}`,
      303,
    );
    assert.equal(
      handoff.headers.location,
      `/_emdash/admin/content/campaign_pages/new?campaign=${action(newSuffix)}`,
    );
    const created = (
      await call(actor, root, 201, "POST", {
        data: { action_id: action(newSuffix), title: "Owned new campaign" },
      })
    ).json.data;
    assert.equal(created.item.status, "draft");
    assert.equal(created.item.authorId, identity.id);
    assert.equal(created.item.data.action_id, action(newSuffix));
    const otherActor = actor === "charity" ? "charity_b" : "charity";
    await call(otherActor, `${root}/${created.item.id}`, 404);
    await call(
      otherActor,
      `/_emdash/admin/campaigns/${action(newSuffix)}`,
      403,
    );
    await call(otherActor, root, 403, "POST", {
      data: { action_id: action(newSuffix), title: "Foreign claim denied" },
    });
    console.log(
      `campaign-isolation: ${actor} real list/search/pagination, content/revision isolation, attributed edit/restore/discard/publish/unpublish/create passed`,
    );
  }
  for (const actor of ["finance", "anonymous"])
    await call(actor, root, actor === "finance" ? 403 : 401);
}
