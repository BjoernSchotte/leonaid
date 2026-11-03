import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export function contentHandlerEntry() {
  const require = createRequire(import.meta.url);
  return join(dirname(require.resolve("emdash")), "api--PYoyeTo.mjs");
}

// This exact published bundle is shared by content handlers and revision work.
// Preserve fixed failure signals, never the raw database exception or item IDs.
// 1.x adds the scheduled policy rejection handler with the same raw log.
export function patchContentLogs(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    "be0f86b65e91a6c360a3feae4bd0009df4b98e5f5cc540b07dbff1e4348ed9bb",
    "EmDash content source changed; re-review log sanitization",
  );
  const content =
    /console\.error\(("(?:Content [^"]+|Scheduled policy rejection) error:"), (?:error|err)\);/g;
  assert.equal([...source.matchAll(content)].length, 21);
  const revision =
    "console.error(`[revisions] Failed to prune revisions for ${revision.collection}/${revision.entryId}:`, error);";
  assert.equal(source.split(revision).length, 2);
  return source
    .replace(content, "console.error($1);")
    .replace(
      revision,
      'console.error("[revisions] Failed to prune revisions");',
    );
}

export default function contentLogPatch() {
  const entry = contentHandlerEntry();
  let transformed = false;
  return {
    name: "leonaid-pinned-content-log-sanitization",
    hooks: {
      "astro:config:setup": async ({ updateConfig }) => {
        patchContentLogs(await readFile(entry, "utf8"));
        updateConfig({
          vite: {
            plugins: [
              {
                name: "leonaid-content-log-sanitization",
                enforce: "pre",
                transform(source, id) {
                  if (id.split("?")[0] !== entry) return;
                  transformed = true;
                  return { code: patchContentLogs(source), map: null };
                },
              },
            ],
          },
        });
      },
      "astro:build:done": () => {
        assert.ok(
          transformed,
          "Content log sanitization was not applied to the production build",
        );
      },
    },
  };
}
