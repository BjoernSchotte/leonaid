import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { krapfentaxiImportContext } from "./krapfentaxi-import-context.mjs";
import { importKrapfentaxi } from "./krapfentaxi-import.mjs";

// Explicit operator invocation only. Mount the existing Core session as a
// read-only private file; never put session bytes on argv or in the journal.
const [mode, slug, sessionFile, ...extra] = process.argv.slice(2);
let context;
try {
  if (
    extra.length ||
    !["dry-run", "apply"].includes(mode) ||
    !slug ||
    !sessionFile
  )
    throw new Error("usage");
  const file = await open(
    sessionFile,
    constants.O_RDONLY | constants.O_NOFOLLOW,
  );
  let session;
  try {
    const info = await file.stat();
    if (
      !info.isFile() ||
      info.mode & 0o077 ||
      info.size < 32 ||
      info.size > 257
    )
      throw new Error("session_file");
    const bytes = Buffer.alloc(258);
    const { bytesRead } = await file.read(bytes, 0, bytes.length, 0);
    if (bytesRead !== info.size) throw new Error("session_file");
    session = bytes.subarray(0, bytesRead).toString("utf8").trim();
  } finally {
    await file.close();
  }
  context = krapfentaxiImportContext(session, slug);
  const result = await importKrapfentaxi({ ...context, mode });
  console.log(JSON.stringify(result));
} catch {
  console.error(
    "krapfentaxi-import: denied or unavailable; no automatic overwrite or publication; inspect private operator state before retrying",
  );
  process.exitCode = 1;
} finally {
  await context?.database.destroy();
}
