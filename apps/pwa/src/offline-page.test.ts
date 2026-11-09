// @vitest-environment jsdom
/*
 * The offline page (public/offline.html, offline.js): with offline start
 * on it names what still works offline for this user, an acquirer's
 * sponsors, a driver's tour (krapfentaxi-touren §9, Ruling 22) or both.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

const BASE = "/app/";
const html = readFileSync(
  resolve(__dirname, "../public/offline.html"),
  "utf8",
).replaceAll("__LEONAID_PWA_BASE__", BASE);
const script = readFileSync(resolve(__dirname, "../public/offline.js"), "utf8");

async function render(settings: Record<string, string>) {
  document.body.innerHTML = html.slice(
    html.indexOf("<body>") + 6,
    html.indexOf("</body>"),
  );
  vi.stubGlobal("caches", {
    open: async () => ({
      match: async (key: string) =>
        key in settings ? new Response(settings[key]) : undefined,
    }),
  });
  new Function(script)();
  await vi.waitFor(() => undefined);
  await new Promise((done) => setTimeout(done, 0));
  return [...document.querySelectorAll<HTMLElement>("[data-offline-copy]")]
    .filter((copy) => !copy.hidden)
    .map((copy) => copy.textContent?.replace(/\s+/g, " ").trim() ?? "");
}

afterEach(() => vi.unstubAllGlobals());

describe("offline page copy", () => {
  it("says only that forms stay online while offline start is off", async () => {
    const shown = await render({});
    expect(shown).toHaveLength(1);
    expect(shown[0]).toContain("speichert bewusst keine Formulare");
  });

  it("points an acquirer to the sponsors, a driver to the tour", async () => {
    const on = { [`${BASE}offline-start`]: "true" };
    const acquirer = await render(on);
    expect(acquirer).toHaveLength(1);
    expect(acquirer[0]).toContain("Zu den Sponsoren");

    const driver = await render({
      ...on,
      [`${BASE}offline-audience`]: "driver",
    });
    expect(driver).toHaveLength(1);
    expect(driver[0]).toContain("Zu meiner Tour");
    expect(driver[0]).not.toMatch(/Sponsoren|Kontakte|Bestellungen/);

    const both = await render({ ...on, [`${BASE}offline-audience`]: "both" });
    expect(both[0]).toContain("Zu den Sponsoren");
    expect(both[0]).toContain("Zu meiner Tour");
  });
});
