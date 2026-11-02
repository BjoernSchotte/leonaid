import assert from "node:assert/strict";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Since Astro 7.3.6 the Node adapter trusts the Host header only when it
// matches `security.allowedDomains`; any other Host falls back to
// `localhost`. Astro.url then points to localhost (wrong canonical and share
// URLs) and `checkOrigin` rejects every form POST from the real site.
//
// The allowed domains are serialized into the server build, but one release
// image serves every installation, each under its own domain. The config
// therefore carries a placeholder pattern, and after the build this
// integration replaces it in the serialized server manifest with the domain
// from an environment variable read at runtime. An unset or empty variable
// adds no domain.
export const RUNTIME_DOMAIN_PLACEHOLDER = "leonaid-runtime-domain.invalid";
const SERIALIZED = JSON.stringify({ hostname: RUNTIME_DOMAIN_PLACEHOLDER });

/** The config entry that the server build replaces at runtime. */
export const runtimeDomainPattern = { hostname: RUNTIME_DOMAIN_PLACEHOLDER };

export function patchRuntimeDomain(source, variable) {
  assert.match(variable, /^[A-Z][A-Z0-9_]*$/);
  assert.equal(
    source.split(SERIALIZED).length,
    2,
    "Serialized allowedDomains changed; re-review the runtime domain patch",
  );
  const runtime =
    `...((domain) => domain ? [{ hostname: domain }] : [])(` +
    `(process.env.${variable} ?? "").trim().toLowerCase())`;
  return source.replace(SERIALIZED, runtime);
}

async function serverModules(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await serverModules(path)));
    else if (entry.name.endsWith(".mjs")) files.push(path);
  }
  return files;
}

export default function runtimeAllowedDomains(variable) {
  let serverDirectory;
  return {
    name: "leonaid-runtime-allowed-domains",
    hooks: {
      "astro:config:done": ({ config }) => {
        assert.ok(
          config.security?.allowedDomains?.some(
            (pattern) => pattern.hostname === RUNTIME_DOMAIN_PLACEHOLDER,
          ),
          "security.allowedDomains must contain runtimeDomainPattern",
        );
        serverDirectory = fileURLToPath(config.build.server);
      },
      // Astro writes the serialized manifest into the server chunk only after
      // bundling, so the replacement happens on the written build output.
      "astro:build:done": async () => {
        let patched = 0;
        for (const path of await serverModules(serverDirectory)) {
          const source = await readFile(path, "utf8");
          if (!source.includes(SERIALIZED)) continue;
          await writeFile(path, patchRuntimeDomain(source, variable));
          patched += 1;
        }
        assert.equal(
          patched,
          1,
          "Runtime domain patch must apply to exactly one server module",
        );
      },
    },
  };
}
