// Serves the built admin web app (APP_KIND=web) or the PWA (APP_KIND=pwa).
// Every non-asset path returns the app's index.html; the client router decides
// what to show. Missing assets return 404 so a stale tab never caches HTML as
// JavaScript after a deploy.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const appKind = process.env.APP_KIND;
const port = Number(process.env.PORT ?? "3000");
const assetDirectories = {
  web: process.env.WEB_ASSET_DIR,
  pwa: process.env.PWA_ASSET_DIR,
};

if (!(appKind in assetDirectories) || !assetDirectories[appKind]) {
  console.error(
    `static-server: APP_KIND must be "web" or "pwa" with its asset directory set`,
  );
  process.exit(78);
}
const assetRoot = path.resolve(assetDirectories[appKind]);

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain; charset=utf-8"],
  [".webmanifest", "application/manifest+json; charset=utf-8"],
  [".woff2", "font/woff2"],
]);

// Files with a content hash in their name may be cached forever. Everything
// else (HTML, service worker, manifest, icons) must be revalidated so changes
// reach users.
const IMMUTABLE = "public, max-age=31536000, immutable";
const REVALIDATE = "no-cache";

const staticFiles = {
  web: new Set(["/favicon.svg"]),
  pwa: new Set(["/manifest.webmanifest", "/sw.js", "/offline.html"]),
};
const staticPrefixes = {
  web: ["/assets/"],
  pwa: ["/assets/", "/icons/"],
};

function resolveInsideRoot(relative) {
  const candidate = path.resolve(assetRoot, relative);
  if (!candidate.startsWith(`${assetRoot}${path.sep}`)) return undefined;
  try {
    return fs.statSync(candidate).isFile() ? candidate : undefined;
  } catch {
    return undefined;
  }
}

/** Returns { file, cacheControl } or { notFound: true }. */
function route(pathname) {
  if (appKind === "pwa" && pathname === "/offline") {
    return {
      file: resolveInsideRoot("offline.html"),
      cacheControl: REVALIDATE,
    };
  }
  const isStatic =
    staticFiles[appKind].has(pathname) ||
    staticPrefixes[appKind].some((prefix) => pathname.startsWith(prefix));
  if (isStatic) {
    const file = resolveInsideRoot(pathname.slice(1));
    if (!file) return { notFound: true };
    return {
      file,
      cacheControl: pathname.startsWith("/assets/") ? IMMUTABLE : REVALIDATE,
    };
  }
  return { file: resolveInsideRoot("index.html"), cacheControl: REVALIDATE };
}

function sendPlain(response, statusCode, message, extraHeaders = {}) {
  response.writeHead(statusCode, {
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-store",
    ...extraHeaders,
  });
  response.end(message);
}

http
  .createServer((request, response) => {
    let pathname;
    try {
      pathname = decodeURIComponent(
        new URL(request.url ?? "/", "http://localhost").pathname,
      );
    } catch {
      sendPlain(response, 400, "Bad request\n");
      return;
    }
    if (pathname === "/health/live" || pathname === "/health/ready") {
      response.writeHead(200, {
        "content-type": "application/json",
        "cache-control": "no-store",
      });
      response.end(JSON.stringify({ service: appKind, status: "ready" }));
      return;
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      sendPlain(response, 405, "Method not allowed\n", { allow: "GET, HEAD" });
      return;
    }
    const target = route(pathname);
    if (target.notFound || !target.file) {
      sendPlain(response, 404, "Not found\n");
      return;
    }
    const serviceWorker = path.basename(target.file) === "sw.js";
    response.writeHead(200, {
      "content-type":
        contentTypes.get(path.extname(target.file)) ??
        "application/octet-stream",
      "cache-control": target.cacheControl,
      "x-content-type-options": "nosniff",
      ...(serviceWorker ? { "service-worker-allowed": "/app/" } : {}),
    });
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    fs.createReadStream(target.file).pipe(response);
  })
  .listen(port, "0.0.0.0");
