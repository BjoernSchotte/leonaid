// Test-only child: stop at a durable importer boundary until the parent kills
// this process. No production CLI fault switch and no session bytes on argv.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { krapfentaxiImportContext } from "./krapfentaxi-import-context.mjs";
import { importKrapfentaxi } from "./krapfentaxi-import.mjs";

const phase = process.argv[2];
assert.ok(["reserved", "ready"].includes(phase));
const sessions = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const context = krapfentaxiImportContext(sessions.system, "krapfentaxi-2026");
try {
  await importKrapfentaxi({
    ...context,
    mode: "apply",
    checkpoint: async (current, key) => {
      if (current !== phase || key !== "hero") return;
      process.stdout.write("durable-checkpoint\n");
      await new Promise(() => {
        setInterval(() => {}, 1000);
      });
    },
  });
  throw new Error("kill_probe_unexpected_completion");
} catch {
  process.stderr.write("kill-probe: child failed before termination\n");
  process.exitCode = 1;
} finally {
  await context.database.destroy();
}
