// Full-stack campaign host proof (specs/multi-domain §7, §9, §14; review of
// #107 I1): the real Caddy with an on-demand certificate, the campaign site's
// host middleware and closed guard, the public app and Core.
//
//   node campaign-host-http-proof.mjs active    krapfentaxi.test is active
//   node campaign-host-http-proof.mjs disabled  the same host has lapsed
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import { connect } from "node:tls";

const phase = process.argv[2];
assert.ok(phase === "active" || phase === "disabled");
const ca = await readFile("/proof/root.crt");
const HOST = "krapfentaxi.test";
const ORIGIN = `https://${HOST}:8443`;

function call(host, pathname, { method = "GET", body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = request(
      {
        host: "proxy",
        port: 8443,
        path: pathname,
        method,
        ca,
        servername: host,
        headers: {
          Host: `${host}:8443`,
          ...headers,
          ...(body === undefined
            ? {}
            : { "Content-Length": Buffer.byteLength(body) }),
        },
      },
      (result) => {
        const chunks = [];
        result.on("data", (chunk) => chunks.push(chunk));
        result.on("end", () =>
          resolve({
            status: result.statusCode,
            headers: result.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(15000, () => req.destroy(new Error(`deadline ${pathname}`)));
    req.on("error", reject);
    req.end(body);
  });
}

function handshake(servername) {
  return new Promise((resolve) => {
    const socket = connect(
      { host: "proxy", port: 8443, servername, ca },
      () => {
        socket.end();
        resolve(true);
      },
    );
    socket.setTimeout(15000, () => {
      socket.destroy();
      resolve(false);
    });
    socket.on("error", () => resolve(false));
  });
}

// The certificate stays valid in both phases: Caddy keeps it.
assert.equal(await handshake(HOST), true, "on-demand certificate for the host");
// A name Core never approved gets no certificate (§9.1).
assert.equal(await handshake("evil.test"), false, "unknown SNI must fail");

if (phase === "active") {
  const root = await call(HOST, "/");
  assert.equal(root.status, 200, `campaign host root: ${root.status}`);
  assert.match(root.body, /data-order-form/);
  // Canonical from Core's canonical function: the host root.
  assert.ok(
    root.body.includes('href="https://krapfentaxi.test/"'),
    "canonical",
  );
  // The edition segment of the running root edition is temporary (§7.7.2).
  const segment = await call(HOST, "/2026/?ref=qr");
  assert.equal(segment.status, 302);
  assert.equal(segment.headers.location, "/?ref=qr");
  // The old CMS path redirects to the canonical URL, also from the public
  // (single) host: one hop.
  const old = await call(HOST, "/campaigns/krapfentaxi-2026/");
  assert.equal(old.status, 302);
  assert.equal(old.headers.location, "https://krapfentaxi.test/");
  const fromSingle = await call("proxy", "/campaigns/krapfentaxi-2026/");
  assert.equal(fromSingle.status, 302);
  assert.equal(fromSingle.headers.location, "https://krapfentaxi.test/");
  const archive = await call("proxy", "/archive/krapfentaxi-2026");
  assert.equal(archive.status, 302);
  assert.equal(archive.headers.location, "https://krapfentaxi.test/");
  // Legal pages and public files are served on every site host.
  assert.equal((await call(HOST, "/impressum")).status, 200);
  assert.equal((await call(HOST, "/favicon.svg")).status, 200);
  const robots = await call(HOST, "/robots.txt");
  assert.equal(robots.status, 200);
  assert.match(
    robots.body,
    /Sitemap: https:\/\/krapfentaxi\.test:8443\/sitemap\.xml/,
  );
  // Native order POST: admitted by the host middleware and the guard (an
  // invalid body is answered by the order form, never 403/404/405).
  const native = await call(HOST, "/?_action=createPublicOrder", {
    method: "POST",
    body: "commandId=00000000-0000-4000-8000-000000000000",
    headers: {
      Origin: ORIGIN,
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });
  assert.ok(
    ![403, 404, 405, 503].includes(native.status),
    `native order POST refused: ${native.status}`,
  );
  const foreign = await call(HOST, "/?_action=createPublicOrder", {
    method: "POST",
    body: "commandId=x",
    headers: {
      Origin: "https://evil.test",
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });
  assert.equal(foreign.status, 403);
  // JS order RPC in the public app: Astro checkOrigin accepts the host.
  const rpc = await call(HOST, "/_actions/createPublicOrder/", {
    method: "POST",
    body: "{}",
    headers: { Origin: ORIGIN, "Content-Type": "application/json" },
  });
  assert.ok(
    ![403, 404].includes(rpc.status),
    `order RPC refused: ${rpc.status}`,
  );
  // Core accepts the active host as public origin (D7).
  const inbox = await call(HOST, "/api/v1/public/inbox-cases", {
    method: "POST",
    body: "{}",
    headers: {
      Origin: ORIGIN,
      "Content-Type": "application/json",
      "Sec-Fetch-Site": "same-origin",
    },
  });
  assert.equal(
    inbox.status,
    422,
    `inbox from the campaign host: ${inbox.status}`,
  );
  // A redirect host redirects as a whole, path kept.
  const www = await call("www.krapfentaxi.test", "/impressum?x=1");
  assert.equal(www.status, 308);
  assert.equal(www.headers.location, "https://krapfentaxi.test/impressum?x=1");
  // Editor and member paths never run on a campaign host.
  assert.equal((await call(HOST, "/_emdash/admin/")).status, 404);
  assert.equal((await call(HOST, "/api/v1/identity/me")).status, 404);
  console.log(
    "campaign-host-http: OK: on-demand TLS, root edition, redirects in one hop, legal pages, native and JS order admission, public origin, redirect host",
  );
} else {
  // Lapsed: Caddy still serves the certificate, the apps refuse the host.
  // Every cache of the host state is at most 30 s old (campaign site,
  // public app, Core origins); wait for all of them, never longer.
  const CACHE_SECONDS = 30;
  const deadline = Date.now() + (CACHE_SECONDS + 5) * 1000;
  for (;;) {
    const states = await Promise.all([
      call(HOST, "/").then((response) => response.status),
      call(HOST, "/impressum").then((response) => response.status),
      call(HOST, "/api/v1/public/inbox-cases", {
        method: "POST",
        body: "{}",
        headers: {
          Origin: ORIGIN,
          "Content-Type": "application/json",
          "Sec-Fetch-Site": "same-origin",
        },
      }).then((response) => response.status),
    ]);
    if (states[0] === 404 && states[1] === 404 && states[2] === 403) break;
    assert.ok(
      Date.now() < deadline,
      `host still served after ${CACHE_SECONDS} s: ${states}`,
    );
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  for (const path of ["/", "/2026/", "/impressum", "/robots.txt"]) {
    const response = await call(HOST, path);
    assert.equal(
      response.status,
      404,
      `${path} on a lapsed host: ${response.status}`,
    );
  }
  const native = await call(HOST, "/?_action=createPublicOrder", {
    method: "POST",
    body: "commandId=x",
    headers: {
      Origin: ORIGIN,
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });
  assert.ok([404, 405].includes(native.status), `order POST: ${native.status}`);
  const inbox = await call(HOST, "/api/v1/public/inbox-cases", {
    method: "POST",
    body: "{}",
    headers: {
      Origin: ORIGIN,
      "Content-Type": "application/json",
      "Sec-Fetch-Site": "same-origin",
    },
  });
  assert.equal(inbox.status, 403, `inbox from a lapsed host: ${inbox.status}`);
  // The public host falls back to its own path again (§7.7.6).
  const fromSingle = await call("proxy", "/campaigns/krapfentaxi-2026/");
  assert.equal(fromSingle.status, 200);
  console.log(
    "campaign-host-http: OK: a lapsed host with a still-valid certificate serves nothing and is no public origin",
  );
}
