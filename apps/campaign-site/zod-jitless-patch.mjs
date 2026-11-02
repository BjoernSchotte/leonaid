import assert from "node:assert/strict";

// Zod 4 probes `Function("")` once to decide whether it may compile parsers
// with eval. Under the strict CSP (no 'unsafe-eval') the probe in the EmDash
// admin bundle raises a script-src violation on every page load before Zod
// falls back to its interpreter. Starting the browser bundle in jitless mode
// skips the probe; server-side Zod is unchanged.
const INITIALIZER =
  "(_a = globalThis).__zod_globalConfig ?? (_a.__zod_globalConfig = {});";
const JITLESS =
  "(_a = globalThis).__zod_globalConfig ?? (_a.__zod_globalConfig = { jitless: true });";

export function patchZodGlobalConfig(source) {
  assert.equal(
    source.split(INITIALIZER).length,
    2,
    "Zod global configuration initializer changed; re-review the CSP patch",
  );
  return source.replace(INITIALIZER, JITLESS);
}

export default function zodJitlessPatch() {
  let transformed = false;
  return {
    name: "leonaid-zod-jitless-client",
    hooks: {
      "astro:config:setup": ({ updateConfig }) => {
        updateConfig({
          vite: {
            plugins: [
              {
                name: "leonaid-zod-jitless-client",
                enforce: "pre",
                transform(source, id, options) {
                  if (options?.ssr) return;
                  if (!id.split("?")[0].endsWith("/zod/v4/core/core.js")) {
                    return;
                  }
                  transformed = true;
                  return { code: patchZodGlobalConfig(source), map: null };
                },
              },
            ],
          },
        });
      },
      "astro:build:done": () => {
        assert.ok(
          transformed,
          "Zod jitless patch was not applied to the client build",
        );
      },
    },
  };
}
