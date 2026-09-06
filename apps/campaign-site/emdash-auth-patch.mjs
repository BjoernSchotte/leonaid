import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";

export const upstreamAuthSha256 =
  "37ca9a59ddebdce5cf597e7115dd2684e74ed131b4a9151a5b6ab37c5f822094";
const anchor = "\t\tlet user = await adapter.getUserByEmail(authResult.email);";
const errorAnchor = '\t\tconsole.error("[external-auth] Auth error:", error);';
const branch = `		// LeonAid spike seam: resolve the verified mapped ID, never link by email.
		if (authMode.providerType === "leonaid-core") {
			const id = authResult.metadata?.cmsUserId;
			if (externalConfig.autoProvision !== false ||
				!/^[0-9A-HJKMNP-TV-Z]{26}$/.test(id ?? "") ||
				!authResult.subject) throw new Error("Invalid stable identity contract");
			const mappedUser = await adapter.getUserById(id);
			// Reject a concurrently changed profile instead of using a stale role.
			if (!mappedUser || mappedUser.disabled ||
				mappedUser.role !== authResult.role || mappedUser.email !== authResult.email ||
				mappedUser.name !== authResult.name) throw new Error("Identity changed during authentication");
			locals.user = mappedUser;
			// No independent EmDash session is created. Core is checked per request.
			return next();
		}
`;
const errorBranch = `		if (authMode.providerType === "leonaid-core") {
			const status = [401, 403, 503].includes(error?.status) ? error.status : 503;
			return apiError("CORE_IDENTITY_DENIED", "Core identity could not be verified", status);
		}
`;

// Pure source transform, not a copied middleware or a general-purpose override.
// Runs only in this Astro application; other workspace packages stay untouched.
export function patchAuthSource(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    upstreamAuthSha256,
    "EmDash auth source changed; re-review the stable-ID patch",
  );
  assert.equal(source.split(anchor).length, 2);
  assert.equal(source.split(errorAnchor).length, 2);
  return source
    .replace(anchor, branch + anchor)
    .replace(errorAnchor, errorBranch + errorAnchor);
}

export default function stableIdentityPatch() {
  let transformed = false;
  const require = createRequire(import.meta.url);
  const entry = require.resolve("emdash/middleware/auth");
  return {
    name: "leonaid-pinned-identity-seam",
    hooks: {
      "astro:config:setup": async ({ updateConfig }) => {
        patchAuthSource(await readFile(entry, "utf8"));
        updateConfig({
          vite: {
            plugins: [
              {
                name: "leonaid-emdash-stable-identity",
                enforce: "pre",
                transform(source, id) {
                  if (id.split("?")[0] !== entry) return;
                  transformed = true;
                  return { code: patchAuthSource(source), map: null };
                },
              },
            ],
          },
        });
      },
      "astro:build:done": () => {
        assert.ok(
          transformed,
          "Stable identity patch was not applied to the production build",
        );
      },
    },
  };
}
