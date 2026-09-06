import { evaluateApprovedSurvey } from "../../packages/surveys/src/validation-candidate.ts";
import { aggregateApprovedSurvey } from "../../packages/surveys/src/analysis.ts";

// SurveyJS diagnostics can include answer contents. This private worker emits
// only generic HTTP outcomes; never forward SDK diagnostics into service logs.
console.warn = console.error = console.log = () => {};
const error = (status) =>
  Response.json({ error: "validation_unavailable" }, { status });
Bun.serve({
  hostname: "0.0.0.0",
  port: 8080,
  maxRequestBodySize: 600_000,
  idleTimeout: 5,
  fetch: async (request) => {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health")
      return Response.json({
        status: "ok",
        profile: "initial-v1",
        renderer: "3.0.3",
      });
    if (request.method !== "POST" || !["/validate", "/aggregate"].includes(url.pathname))
      return error(404);
    try {
      const body = await request.json();
      if (
        !body ||
        body.profile !== "initial-v1" ||
        !body.definition ||
        !Array.isArray(body.definition.pages) ||
        body.definition.pages.length > 25
      )
        return error(400);
      if (url.pathname === "/aggregate") {
        if (!Array.isArray(body.responses) || body.responses.length > 100 ||
          body.responses.some((answers) => !answers || typeof answers !== "object" || Array.isArray(answers)))
          return error(400);
        return Response.json({
          profile: "initial-v1", renderer: "3.0.3",
          questions: aggregateApprovedSurvey(body.definition, body.responses),
        });
      }
      if (!body.answers || typeof body.answers !== "object" || Array.isArray(body.answers))
        return error(400);
      // Host validates the full capability allowlist against the stored version
      // before this private call. No respondent can choose this definition.
      return Response.json({
        profile: "initial-v1",
        renderer: "3.0.3",
        ...evaluateApprovedSurvey(body.definition, body.answers),
      });
    } catch {
      return error(400);
    }
  },
  error: () => error(503),
});
