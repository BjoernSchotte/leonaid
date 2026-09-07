import { Database } from "bun:sqlite";
import { createHash, randomUUID } from "node:crypto";

const db = new Database("/data/demo.sqlite", { create: true });
db.exec(
  "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS participation(id TEXT PRIMARY KEY, secret TEXT NOT NULL, value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS operation(pid TEXT, id TEXT, input TEXT, result TEXT, PRIMARY KEY(pid,id));",
);
db.exec(
  "CREATE TABLE IF NOT EXISTS export_job(id TEXT PRIMARY KEY,pid TEXT NOT NULL,operation_id TEXT NOT NULL,input TEXT NOT NULL,value TEXT NOT NULL,content TEXT NOT NULL,UNIQUE(pid,operation_id));",
);
// Synthetic isolated editor fixture, not a production authoring/authentication service.
db.exec(
  "CREATE TABLE IF NOT EXISTS editor_draft(singleton INTEGER PRIMARY KEY CHECK(singleton=1),value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS editor_operation(id TEXT PRIMARY KEY,input TEXT NOT NULL,result TEXT NOT NULL)",
);
db.query("INSERT OR IGNORE INTO editor_draft VALUES(1,?)").run(
  JSON.stringify({
    surveyId: "editor-demo",
    revision: 1,
    definition: {
      title: "Author supplied title",
      pages: [
        {
          name: "page",
          title: "Author supplied page",
          elements: [
            { name: "source", type: "text", title: "Author supplied question" },
            {
              name: "follow",
              type: "comment",
              title: "Author supplied followup",
              visibleIf: "{source} notempty",
            },
          ],
        },
      ],
    },
  }),
);
const definition = {
  title: "Your community event",
  pages: [
    {
      name: "visit",
      elements: [
        {
          type: "text",
          name: "name",
          title: "Your name",
          isRequired: true,
          maxLength: 200,
        },
      ],
    },
    {
      name: "feedback",
      elements: [
        {
          type: "comment",
          name: "feedback",
          title: "What should we improve?",
          maxLength: 1000,
        },
      ],
    },
  ],
};
const fail = (code, message) => {
  throw { code, message, diagnostics: [] };
};
const hash = (value) => createHash("sha256").update(value).digest("hex");
function current(request) {
  const secret = request.headers
    .get("cookie")
    ?.match(/(?:^|;\s*)demo_session=([^;]+)/)?.[1];
  if (!secret) return null;
  return db
    .query("SELECT * FROM participation WHERE secret=?")
    .get(hash(secret));
}
const result = (value, headers = {}) =>
  Response.json(
    { ok: true, value },
    { headers: { "Cache-Control": "no-store", ...headers } },
  );
function exportRequest(request, row, input) {
  if (!row) fail("not_found", "No participation");
  if (
    !input ||
    typeof input.operationId !== "string" ||
    !input.operationId.length ||
    input.operationId.length > 128 ||
    input.product !== "responses_csv"
  )
    fail("invalid_response", "This host supports response CSV only");
  return db.transaction(() => {
    const signature = JSON.stringify([input.snapshotId, input.product]);
    const prior = db
      .query("SELECT * FROM export_job WHERE pid=? AND operation_id=?")
      .get(row.id, input.operationId);
    if (prior) {
      if (prior.input !== signature)
        fail("idempotency_conflict", "Export request changed");
      return result(JSON.parse(prior.value));
    }
    const response = JSON.parse(row.value).response;
    if (input.snapshotId !== `${row.id}:${response.revision}`)
      fail(
        "revision_conflict",
        "Feedback changed; reload to select its saved revision",
      );
    const id = randomUUID();
    const value = {
      id,
      snapshotId: input.snapshotId,
      product: input.product,
      status: "completed",
      filename: "my-feedback.csv",
      error: null,
    };
    const cell = (v) => {
      const text = String(v ?? "");
      const safe = /^[\s]*[=+\-@']/.test(text) ? "'" + text : text;
      return '"' + safe.replaceAll('"', '""') + '"';
    };
    const content =
      [
        ["snapshot_id", "status", "name", "feedback"],
        [
          input.snapshotId,
          response.status,
          response.answers.name,
          response.answers.feedback,
        ],
      ]
        .map((r) => r.map(cell).join(","))
        .join("\r\n") + "\r\n";
    db.query("INSERT INTO export_job VALUES(?,?,?,?,?,?)").run(
      id,
      row.id,
      input.operationId,
      signature,
      JSON.stringify(value),
      content,
    );
    return result(value);
  })();
}
Bun.serve({
  port: 8080,
  hostname: "0.0.0.0",
  maxRequestBodySize: 16384,
  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/health") return new Response("ok");
    if (path === "/" || path === "/exports" || path === "/editor")
      return new Response(
        `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Independent surveys consumer</title><link rel="stylesheet" href="/${path === "/editor" ? "editor" : path === "/exports" ? "exports" : "client"}.css"><div id="app"></div><script type="module" src="/${path === "/editor" ? "editor" : path === "/exports" ? "exports" : "client"}.js"></script></html>`,
        { headers: { "Content-Type": "text/html" } },
      );
    if (
      [
        "/client.js",
        "/client.css",
        "/exports.js",
        "/exports.css",
        "/editor.js",
        "/editor.css",
      ].includes(path)
    )
      return new Response(Bun.file(`/consumer/dist${path}`));
    try {
      if (path === "/api/editor") {
        if (request.method === "GET")
          return result(
            JSON.parse(
              db.query("SELECT value FROM editor_draft WHERE singleton=1").get()
                .value,
            ),
          );
        const input = await request.json();
        return db.transaction(() => {
          const draft = JSON.parse(
            db.query("SELECT value FROM editor_draft WHERE singleton=1").get()
              .value,
          );
          if (request.method === "PUT") {
            const prior = db
              .query("SELECT * FROM editor_operation WHERE id=?")
              .get(input.operationId);
            if (prior) {
              if (prior.input !== JSON.stringify(input))
                fail("idempotency_conflict", "Editor request changed");
              return result(JSON.parse(prior.result));
            }
          }
          if (input.expectedRevision !== draft.revision)
            fail("revision_conflict", "Editor revision changed");
          if (request.method === "POST") return result(draft);
          if (
            request.method !== "PUT" ||
            typeof input.operationId !== "string" ||
            !Array.isArray(input.definition?.pages)
          )
            fail("invalid_response", "Invalid editor fixture request");
          const next = {
            ...draft,
            revision: draft.revision + 1,
            definition: input.definition,
          };
          db.query("UPDATE editor_draft SET value=? WHERE singleton=1").run(
            JSON.stringify(next),
          );
          db.query("INSERT INTO editor_operation VALUES(?,?,?)").run(
            input.operationId,
            JSON.stringify(input),
            JSON.stringify(next),
          );
          return result(next);
        })();
      }
      let row = current(request);
      if (path === "/api/export-source" && request.method === "GET") {
        if (!row) fail("not_found", "Start feedback first");
        return result({
          snapshotId: `${row.id}:${JSON.parse(row.value).response.revision}`,
        });
      }
      if (path === "/api/exports" && request.method === "POST")
        return exportRequest(request, row, await request.json());
      if (path.startsWith("/api/exports/") && request.method === "GET") {
        if (!row) fail("not_found", "Export not found");
        const match = path.match(/^\/api\/exports\/([^/]+)(\/download)?$/);
        const job =
          match &&
          db
            .query("SELECT * FROM export_job WHERE id=? AND pid=?")
            .get(match[1], row.id);
        if (!job) fail("not_found", "Export not found");
        return match[2]
          ? new Response(job.content, {
              headers: {
                "Content-Type": "text/csv; charset=utf-8",
                "Content-Disposition": 'attachment; filename="my-feedback.csv"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
              },
            })
          : result(JSON.parse(job.value));
      }
      if (path === "/api/diagnostics" && request.method === "GET") {
        if (!row) fail("not_found", "No participation");
        return result({
          participations: db
            .query("SELECT count(*) AS n FROM participation")
            .get().n,
          writes: db
            .query("SELECT count(*) AS n FROM operation WHERE pid=?")
            .get(row.id).n,
        });
      }
      if (path !== "/api/participation") fail("not_found", "Unknown route");
      if (request.method === "GET") {
        if (!row) fail("not_found", "No participation");
        return result(JSON.parse(row.value));
      }
      const input = await request.json();
      if (
        !input ||
        typeof input.operationId !== "string" ||
        input.operationId.length > 100
      )
        fail("invalid_response", "Operation ID required");
      if (request.method === "POST") {
        if (row) return result(JSON.parse(row.value));
        const id = randomUUID(),
          secret = randomUUID() + randomUUID();
        const value = {
          id,
          inactivityTimeoutSeconds: 1800,
          version: {
            id: "community-v1",
            surveyId: "community",
            number: 1,
            definition,
            rendererVersion: "3.0.3",
            capabilityProfile: "demo-v1",
            publishedAt: "2026-09-06T00:00:00Z",
          },
          response: {
            participationId: id,
            versionId: "community-v1",
            revision: 1,
            status: "in_progress",
            answers: {},
            currentPage: null,
            lastAnswerChangedAt: null,
            completedAt: null,
            diagnostics: [],
          },
        };
        db.query("INSERT INTO participation VALUES(?,?,?)").run(
          id,
          hash(secret),
          JSON.stringify(value),
        );
        return result(value, {
          "Set-Cookie": `demo_session=${secret}; HttpOnly; SameSite=Strict; Path=/`,
        });
      }
      if (!row) fail("not_found", "No participation");
      if (!["PUT", "PATCH"].includes(request.method))
        fail("invalid_response", "Unsupported operation");
      return db.transaction(() => {
        row = db.query("SELECT * FROM participation WHERE id=?").get(row.id);
        const signature = JSON.stringify([request.method, input]);
        const prior = db
          .query("SELECT * FROM operation WHERE pid=? AND id=?")
          .get(row.id, input.operationId);
        if (prior) {
          if (prior.input !== signature)
            fail("idempotency_conflict", "Operation changed");
          return result(JSON.parse(prior.result));
        }
        const value = JSON.parse(row.value),
          response = value.response;
        if (response.status === "completed")
          fail("closed", "Response already completed");
        if (input.expectedRevision !== response.revision)
          fail("revision_conflict", "Newer response exists");
        const answers =
          request.method === "PUT" ? input.answers : response.answers;
        if (
          !answers ||
          typeof answers !== "object" ||
          Array.isArray(answers) ||
          Object.keys(answers).some(
            (key) => !["name", "feedback"].includes(key),
          )
        )
          fail("invalid_response", "Invalid answers");
        for (const [key, value] of Object.entries(answers)) {
          if (
            typeof value !== "string" ||
            value.length > (key === "name" ? 200 : 1000)
          )
            fail("invalid_response", "Invalid answer");
        }
        if (request.method === "PATCH" && !answers.name)
          fail("invalid_response", "Please enter your name");
        if (
          request.method === "PUT" &&
          input.currentPage !== null &&
          !["visit", "feedback"].includes(input.currentPage)
        )
          fail("invalid_response", "Unknown page");
        if (JSON.stringify(response.answers) !== JSON.stringify(answers))
          response.lastAnswerChangedAt = new Date().toISOString();
        response.answers = answers;
        response.revision++;
        if (request.method === "PUT") response.currentPage = input.currentPage;
        else {
          response.status = "completed";
          response.completedAt = new Date().toISOString();
        }
        db.query("UPDATE participation SET value=? WHERE id=?").run(
          JSON.stringify(value),
          row.id,
        );
        db.query("INSERT INTO operation VALUES(?,?,?,?)").run(
          row.id,
          input.operationId,
          signature,
          JSON.stringify(response),
        );
        return result(response);
      })();
    } catch (error) {
      const safe = error?.code
        ? error
        : {
            code: "temporarily_unavailable",
            message: "Demo request unavailable",
            diagnostics: [],
          };
      return Response.json(
        { ok: false, error: safe },
        {
          status: safe.code === "not_found" ? 404 : 422,
          headers: { "Cache-Control": "no-store" },
        },
      );
    }
  },
});
