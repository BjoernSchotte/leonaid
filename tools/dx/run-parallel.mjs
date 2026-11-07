#!/usr/bin/env bun
// Run root package scripts concurrently (`bun run <script>` each), at most
// LEONAID_PARALLEL_JOBS (default 4) at a time to bound memory. A failed
// script's output is printed as one block; any failure fails the run.
// Usage: bun tools/dx/run-parallel.mjs typecheck:web typecheck:pwa ...
import { spawn } from "node:child_process";

const scripts = process.argv.slice(2);
const jobs = Number.parseInt(process.env.LEONAID_PARALLEL_JOBS ?? "4", 10);
if (scripts.length === 0 || !(jobs >= 1)) {
  console.error(
    "run-parallel: usage: run-parallel.mjs SCRIPT... (LEONAID_PARALLEL_JOBS >= 1)",
  );
  process.exit(2);
}

function run(script) {
  return new Promise((resolve) => {
    const started = Date.now();
    const child = spawn("bun", ["run", script], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    const chunks = [];
    child.stdout.on("data", (chunk) => chunks.push(chunk));
    child.stderr.on("data", (chunk) => chunks.push(chunk));
    child.on("error", (error) => chunks.push(Buffer.from(`${error}\n`)));
    child.on("close", (code, signal) => {
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      const ok = code === 0;
      process.stdout.write(
        `-- ${script}: ${ok ? "OK" : `FAILED (${signal ?? code})`} in ${seconds}s\n`,
      );
      // Successful scripts only report their duration.
      if (!ok) process.stdout.write(Buffer.concat(chunks));
      resolve(ok);
    });
  });
}

const failed = [];
const queue = [...scripts];
async function worker() {
  while (queue.length > 0) {
    const script = queue.shift();
    if (!(await run(script))) failed.push(script);
  }
}
await Promise.all(
  Array.from({ length: Math.min(jobs, scripts.length) }, worker),
);
if (failed.length > 0) {
  console.error(`run-parallel: failed: ${failed.join(", ")}`);
  process.exit(1);
}
