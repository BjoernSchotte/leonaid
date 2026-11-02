import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

vi.mock("./surveys", () => ({
  SurveysPage: (props: { createNew?: boolean; surveyId?: string }) => (
    <p>surveys:{props.createNew ? "new" : (props.surveyId ?? "list")}</p>
  ),
}));

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

  it("keeps the existing survey URLs", async () => {
    expect(webModules.map((module) => module.id)).toEqual(["surveys"]);
    const surveyId = "0b8a3c1e-2f4d-4e5a-9b6c-7d8e9f0a1b2c";
    const cases = [
      ["/surveys", "surveys:list"],
      ["/surveys/new", "surveys:new"],
      [`/surveys/${surveyId}`, `surveys:${surveyId}`],
    ] as const;
    for (const [path, text] of cases) {
      const route = resolveModuleRoute(webModules, "web", path);
      expect(route?.label).toBe("Umfragen");
      const view = render(<>{route?.render(context)}</>);
      expect(await screen.findByText(text)).toBeTruthy();
      view.unmount();
    }
    expect(resolveModuleRoute(webModules, "web", "/surveys/edit")).toBeNull();
    expect(resolveModuleRoute(webModules, "web", "/")).toBeNull();
  });
});
