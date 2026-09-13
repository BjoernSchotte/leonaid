import { describe, expect, it } from "vitest";
import {
  resolveModuleRoute,
  validateUiModules,
  type UiModule,
} from "../../../packages/features/src/modules";
import { registeredModules } from "../../../packages/features/src/registered-modules";

describe("explicit UI modules", () => {
  it.each([
    "/admin/surveys",
    "/admin/surveys/",
    "/admin/surveys/new",
    "/admin/surveys/10000000-0000-4000-8000-000000000001",
  ])("resolves the existing survey URL %s", (path) => {
    expect(resolveModuleRoute(registeredModules, "web", path)?.moduleId).toBe(
      "surveys",
    );
  });

  it("does not capture unrelated, public, invalid or PWA routes", () => {
    for (const path of [
      "/admin/actions",
      "/surveys/123",
      "/admin/surveys/nope",
    ])
      expect(resolveModuleRoute(registeredModules, "web", path)).toBeNull();
    // Surveys retain the cross-surface link to the web authoring app.
    expect(
      resolveModuleRoute(registeredModules, "pwa", "/app/surveys"),
    ).toBeNull();
  });

  it("rejects duplicate IDs and overlapping routes", () => {
    const surveys = registeredModules[0];
    expect(() => validateUiModules([surveys, surveys])).toThrow("duplicate");
    const other = { ...surveys, id: "other" };
    expect(() => validateUiModules([surveys, other])).toThrow("Duplicate");
    const overlapping: UiModule = {
      ...other,
      routes: [{ ...other.routes[0], pattern: /^\/admin\/surveys/ }],
    };
    expect(() =>
      resolveModuleRoute([surveys, overlapping], "web", "/admin/surveys"),
    ).toThrow("Ambiguous");
  });
});
