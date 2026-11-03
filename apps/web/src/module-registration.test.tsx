import { isValidElement, type ReactElement, type ReactNode } from "react";
import { describe, expect, it } from "vitest";

import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  resolveModuleRoute,
  validateUiModules,
  type UiModule,
} from "@leonaid/features";

import { webModules } from "./modules";

const context = {
  client: {} as LeonAidApiClient,
  identity: {} as CurrentIdentityResponse,
};

function page(id: string): UiModule {
  return {
    id,
    label: id,
    surfaces: ["web"],
    routes: [{ pattern: new RegExp(`^/${id}$`), render: () => id }],
  };
}

describe("UI module registration", () => {
  it("rejects invalid and duplicate IDs", () => {
    expect(() => validateUiModules([page("Tasks")])).toThrow(/Invalid/);
    expect(() => validateUiModules([page("tasks"), page("tasks")])).toThrow(
      /duplicate/,
    );
  });

  it("rejects stateful patterns and duplicate routes per surface", () => {
    const stateful: UiModule = {
      ...page("tasks"),
      routes: [{ pattern: /^\/tasks$/g, render: () => null }],
    };
    expect(() => validateUiModules([stateful])).toThrow(/Stateful/);
    const twin: UiModule = { ...page("tasks"), id: "lists" };
    expect(() => validateUiModules([page("tasks"), twin])).toThrow(
      /Duplicate UI module route/,
    );
  });

  it("rejects modules without a surface", () => {
    expect(() =>
      validateUiModules([{ ...page("tasks"), surfaces: [] }]),
    ).toThrow(/without surface/);
  });

  it("resolves only routes of the requested surface", () => {
    const pwaOnly: UiModule = { ...page("tasks"), surfaces: ["pwa"] };
    expect(resolveModuleRoute([pwaOnly], "web", "/tasks")).toBeNull();
    expect(resolveModuleRoute([pwaOnly], "pwa", "/tasks")?.moduleId).toBe(
      "tasks",
    );
  });

  it("fails loudly on ambiguous routes", () => {
    const overlapping: UiModule = {
      ...page("lists"),
      routes: [{ pattern: /^\/t.*$/, render: () => null }],
    };
    expect(() =>
      resolveModuleRoute([page("tasks"), overlapping], "web", "/tasks"),
    ).toThrow(/Ambiguous/);
  });

  it("keeps the existing survey URLs", () => {
    expect(webModules.map((module) => module.id)).toEqual([
      "surveys",
      "tasks",
      "materials",
      "knowledge",
    ]);
    const surveyId = "0b8a3c1e-2f4d-4e5a-9b6c-7d8e9f0a1b2c";
    const cases = [
      ["/surveys", { createNew: false, surveyId: undefined }],
      ["/surveys/new", { createNew: true, surveyId: undefined }],
      [`/surveys/${surveyId}`, { createNew: false, surveyId }],
    ] as const;
    for (const [path, expected] of cases) {
      const route = resolveModuleRoute(webModules, "web", path);
      expect(route?.label).toBe("Umfragen");
      // The page is lazy; its element props carry the parsed route.
      const page = pageElement(route?.render(context));
      expect(page.props).toMatchObject({ ...expected, client: context.client });
    }
    expect(resolveModuleRoute(webModules, "web", "/surveys/edit")).toBeNull();
    expect(resolveModuleRoute(webModules, "web", "/")).toBeNull();
  });
});

function pageElement(node: ReactNode): ReactElement<Record<string, unknown>> {
  if (!isValidElement<{ children?: ReactNode }>(node)) {
    throw new Error("Module route did not render an element");
  }
  const child = node.props.children;
  if (!isValidElement<Record<string, unknown>>(child)) {
    throw new Error("Module route did not render a page");
  }
  return child;
}
