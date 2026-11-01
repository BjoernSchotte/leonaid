import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const BUILD_ID_TOKEN = "__LEONAID_BUILD_ID__";
const ASSETS_TOKEN = "/* __LEONAID_BUILD_ASSETS__ */ []";

function filesBelow(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesBelow(path) : [path];
  });
}

/**
 * Stamps the service worker with a build ID derived from every other output
 * file and with the list of hashed assets to precache. Without this, sw.js
 * stays byte-identical across deploys and browsers never pick up updates.
 */
function serviceWorkerBuild(): Plugin {
  let outDir = "";
  return {
    name: "leonaid-service-worker-build",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      const files = filesBelow(outDir)
        .map((file) => relative(outDir, file).split(sep).join("/"))
        .filter((file) => file !== "sw.js")
        .sort();
      const hash = createHash("sha256");
      for (const file of files) {
        hash
          .update(file)
          .update("\0")
          .update(readFileSync(join(outDir, file)));
      }
      const assets = files
        .filter((file) => file.startsWith("assets/") && !file.endsWith(".map"))
        .map((file) => `/app/${file}`);
      const target = join(outDir, "sw.js");
      const source = readFileSync(target, "utf8");
      if (!source.includes(BUILD_ID_TOKEN) || !source.includes(ASSETS_TOKEN)) {
        throw new Error("sw.js lacks the build placeholders");
      }
      writeFileSync(
        target,
        source
          .replace(BUILD_ID_TOKEN, hash.digest("hex").slice(0, 16))
          .replace(ASSETS_TOKEN, JSON.stringify(assets)),
      );
    },
  };
}

export default defineConfig({
  base: "/app/",
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  plugins: [react(), tailwindcss(), serviceWorkerBuild()],
});
