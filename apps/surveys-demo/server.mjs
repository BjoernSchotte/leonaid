import { Database } from "bun:sqlite";
import { createHash, randomUUID } from "node:crypto";

const db = new Database("/data/demo.sqlite", { create: true });
db.exec(
  "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS participation(id TEXT PRIMARY KEY, secret TEXT NOT NULL, value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS operation(pid TEXT, id TEXT, input TEXT, result TEXT, PRIMARY KEY(pid,id));",
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
Bun.serve({
  port: 8080,
  hostname: "0.0.0.0",
  maxRequestBodySize: 16384,
  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/health") return new Response("ok");
    if (path === "/")
      return new Response(
        `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Independent surveys consumer</title><link rel="stylesheet" href="/client.css"><div id="app"></div><script type="module" src="/client.js"></script></html>`,
        { headers: { "Content-Type": "text/html" } },
      );
    if (path === "/client.js" || path === "/client.css")
      return new Response(Bun.file(`/consumer/dist${path}`));
    try {
      let row = current(request);
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
