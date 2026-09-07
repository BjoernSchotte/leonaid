import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

const ca = await readFile("/proof/root.crt");
const down = process.argv.includes("--down");
for (const method of ["GET", "HEAD"]) {
  const result = await new Promise((resolve, reject) => {
    const req = request(
      "https://proxy:8443/outage-redirect",
      { ca, method },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", reject);
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.on("error", reject);
    req.setTimeout(15000, () =>
      req.destroy(new Error("redirect probe timed out")),
    );
    req.end();
  });
  assert.equal(result.status, down ? 503 : 302);
  assert.equal(result.headers["cache-control"], "no-store");
  assert.equal(result.headers["set-cookie"], undefined);
  assert.equal(
    result.headers.location,
    down ? undefined : "/campaigns/krapfentaxi-2026/",
  );
  if (down) assert.ok(!result.body.includes("/campaigns/krapfentaxi-2026/"));
}
console.log(
  `redirect-outage: actual CA-verified GET/HEAD ${down ? "503 with no cached target" : "302 canonical target"} passed`,
);
