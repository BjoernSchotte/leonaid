import { describe, expect, it } from "vitest";
import {
  resolveModuleRoute,
  validateUiModules,
  type UiModule,
} from "../../../packages/features/src/modules";
import { registeredModules } from "../../../packages/features/src/registered-modules";

import { registeredPwaModules } from "../../../packages/features/src/pwa-modules";

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

  it("registers the shared task feature in both shipped shells", () => {
    for (const suffix of ["", "/10000000-0000-4000-8000-000000000001"]) {
      expect(
        resolveModuleRoute(registeredModules, "web", `/admin/tasks${suffix}`)
          ?.moduleId,
      ).toBe("tasks");
      expect(
        resolveModuleRoute(registeredPwaModules, "pwa", `/app/tasks${suffix}`)
          ?.moduleId,
      ).toBe("tasks");
    }
    expect(
      resolveModuleRoute(registeredPwaModules, "pwa", "/app/tasks/nope"),
    ).toBeNull();
    expect(registeredPwaModules.some((module) => module.id === "surveys")).toBe(
      false,
    );
  });

  it("registers knowledge in both shipped shells", () => {
    expect(
      resolveModuleRoute(registeredModules, "web", "/admin/knowledge")
        ?.moduleId,
    ).toBe("knowledge");
    expect(
      resolveModuleRoute(registeredPwaModules, "pwa", "/app/knowledge")
        ?.moduleId,
    ).toBe("knowledge");
  });

  it("resolves knowledge editors without catching malformed page IDs", () => {
    const id = "10000000-0000-4000-8000-000000000001";
    expect(
      resolveModuleRoute(registeredModules, "web", `/admin/knowledge/${id}`)
        ?.moduleId,
    ).toBe("knowledge");
    expect(
      resolveModuleRoute(registeredPwaModules, "pwa", `/app/knowledge/${id}`)
        ?.moduleId,
    ).toBe("knowledge");
    expect(
      resolveModuleRoute(registeredModules, "web", "/admin/knowledge/invalid"),
    ).toBeNull();
  });

  it("resolves materials and version management in both shells", () => {
    const id = "10000000-0000-4000-8000-000000000001";
    expect(
      resolveModuleRoute(registeredModules, "web", "/admin/materials")
        ?.moduleId,
    ).toBe("materials");
    expect(
      resolveModuleRoute(registeredPwaModules, "pwa", `/app/materials/${id}`)
        ?.moduleId,
    ).toBe("materials");
    expect(
      resolveModuleRoute(registeredModules, "web", "/admin/materials/invalid"),
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
