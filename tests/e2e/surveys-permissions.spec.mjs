import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
test.describe.configure({ mode: "parallel" });
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
const names = [
  "admin",
  "design",
  "publish",
  "archive",
  "view_aggregates",
  "read_responses",
  "export_raw",
  "export_reports",
  "manage_invitations",
  "delete",
  "owner",
  "manager",
  "member",
  "outsider",
];

for (const mobile of [false, true]) {
  for (const name of names) {
    test(`${name} has scoped active-survey controls on ${mobile ? "mobile" : "desktop"}`, async ({
      browser,
    }) => {
      const fixture = JSON.parse(
        readFileSync(`${proof}/permission-browser-private.json`, "utf8"),
      ).actors[name];
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: mobile
          ? { width: 390, height: 844 }
          : { width: 1440, height: 1000 },
      });
      await context.addCookies([
        {
          name: "__Host-leonaid_session",
          value: fixture.token,
          url: base,
          secure: true,
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
      try {
        const page = await context.newPage();
        await page.goto(`${base}/admin/surveys`);
        const search = page.getByLabel("Umfrage suchen", { exact: true });
        await search.fill("Permission matrix");
        const permitted = fixture.resources.filter(
          (r) => r.capabilities.length,
        );
        await expect(page.locator(".surveys-list li")).toHaveCount(
          permitted.length,
        );
        const links = await page
          .locator(".surveys-list li a")
          .evaluateAll((nodes) =>
            nodes.map((node) => node.getAttribute("href").split("/").at(-1)),
          );
        expect(links.sort()).toEqual(permitted.map((r) => r.id).sort());
        await expect(
          page.getByText("Standard für Teilantworten", { exact: true }),
        ).toHaveCount(name === "admin" ? 1 : 0);
        for (const resource of fixture.resources) {
          const has = (cap) => resource.capabilities.includes(cap);
          // A real response-selection deep link must not unlock protected data.
          await page.goto(
            `${base}/admin/surveys/${resource.id}?responseSelection=${resource.snapshot}`,
          );
          if (!resource.capabilities.length) {
            await expect(page.getByRole("alert")).toContainText(
              "Umfrage nicht gefunden",
            );
            await expect(
              page.getByRole("region", {
                name: "Umfrage verwalten",
                exact: true,
              }),
            ).toHaveCount(0);
            await expect(
              page.getByRole("region", {
                name: "Fragebogen bearbeiten",
                exact: true,
              }),
            ).toHaveCount(0);
          } else {
            await expect(page.locator("[data-survey-status]")).toHaveAttribute(
              "data-survey-status",
              "active",
            );
            for (const [label, allowed] of [
              ["Teilnahme beenden", has("publish")],
              ["In Papierkorb verschieben", has("delete")],
              ["Veröffentlichen", has("design") && has("publish")],
            ])
              await expect(
                page.getByRole("button", { name: label, exact: true }),
              ).toHaveCount(allowed ? 1 : 0);
            for (const [label, allowed] of [
              ["Geplantes Ende", has("publish")],
              ["Teilantworten nach Inaktivität", has("design")],
              ["Antworten auswerten", has("view_aggregates")],
              [
                "Antworten exportieren",
                !has("view_aggregates") &&
                  (has("export_raw") || has("export_reports")),
              ],
              ["Einzelantworten lesen", has("read_responses")],
            ])
              await expect(page.getByText(label, { exact: true })).toHaveCount(
                allowed ? 1 : 0,
              );
            await expect(
              page.getByRole("region", {
                name: "Fragebogen bearbeiten",
                exact: true,
              }),
            ).toHaveCount(has("design") ? 1 : 0);
            await expect(
              page.getByRole("region", {
                name: "Veröffentlichung prüfen",
                exact: true,
              }),
            ).toHaveCount(has("publish") && !has("design") ? 1 : 0);
            // These four fixtures use anonymous access; invitation mode has its own matrix.
            await expect(page.getByText(/^Einladungen \(\d+\)$/)).toHaveCount(
              0,
            );
            if (!has("read_responses"))
              await expect(page.getByRole("alert")).toContainText(
                "Antwortstand ist für Sie nicht zugänglich",
              );
          }
          const draft = await context.request.get(
            `${base}/api/v1/surveys/${resource.id}/draft`,
          );
          expect(draft.status()).toBe(has("design") ? 200 : 404);
          if (!has("publish")) {
            const result = await context.request.post(
              `${base}/api/v1/surveys/${resource.id}/publish`,
              {
                data: {
                  operationId: `browser-denied-${name}-${mobile}`,
                  expectedRevision: 1,
                },
              },
            );
            expect(result.status()).toBe(404);
          }
        }
        writeFileSync(
          `${proof}/permission-browser-${name}-${mobile}.json`,
          JSON.stringify({
            persona: name,
            viewport: mobile ? "mobile" : "desktop",
            resourcePairs: fixture.resources.length,
            scopedControlsAndDirectAccess: true,
          }),
        );
      } finally {
        await context.close();
      }
    });
  }
}
