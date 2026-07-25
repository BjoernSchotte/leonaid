import http from "node:http";

const appName = process.env.APP_NAME ?? "LeonAid";
const appKind = process.env.APP_KIND ?? "service";
const port = Number(process.env.PORT ?? "3000");

const page = `<!doctype html>
<html lang="de">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
    <title>${appName}</title></head>
  <body><main><h1>${appName}</h1><p>LeonAid ${appKind} ist bereit.</p></main></body>
</html>`;

http
  .createServer((request, response) => {
    if (request.url === "/health/live" || request.url === "/health/ready") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ service: appKind, status: "ready" }));
      return;
    }
    response.writeHead(200, {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
    });
    response.end(page);
  })
  .listen(port, "0.0.0.0");
