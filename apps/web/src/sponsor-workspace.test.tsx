import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  type CurrentIdentityResponse,
  LeonAidApiClient,
  type SponsorMatchResponse,
} from "@leonaid/api-client";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { SponsorWorkspace } from "../../../packages/features/src/acquisition/sponsor-workspace";

const actionId = "20000000-0000-4000-8000-000000000001";
const identity = {
  userId: "00000000-0000-4000-8000-0000000000aa",
  displayName: "Anna Akquise",
  globalRoles: [],
  actionMemberships: [
    { actionId, actionName: "Krapfentaxi 2026", role: "acquirer" },
  ],
  navigation: [],
} as unknown as CurrentIdentityResponse;

const bernd = { displayName: "Bernd Binder", userId: "bernd" };

function candidate(name: string, twentyId: string, shared = false) {
  return {
    assignedAcquirers: shared ? [bernd] : [],
    city: "Berlin",
    displayName: name,
    email: null,
    partyKind: "company" as const,
    postalCode: "10243",
    twentyId,
  };
}

function match(
  status: SponsorMatchResponse["status"],
  candidates: ReturnType<typeof candidate>[],
): SponsorMatchResponse {
  return {
    candidates,
    input: {} as SponsorMatchResponse["input"],
    normalizedKey: "key",
    partyKind: "company",
    status,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

/** A real API client whose transport answers like the matching endpoints. */
function matchingClient(resolves: Record<string, unknown>[]) {
  let previews = 0;
  return new LeonAidApiClient("", async (input, init = {}) => {
    const url = String(input);
    if (url.endsWith("/sponsor-match/resolve")) {
      resolves.push(JSON.parse(String(init.body)));
      return json(
        {
          assignmentCreated: true,
          assignmentId: "assignment",
          contactTwentyId: null,
          displayName: "Bäckerei Sonnenseite KG",
          normalizedKey: "key",
          outcome: "reused",
          partyKind: "company",
          priorAssignees: [bernd],
          replayed: false,
          twentyId: "t-shared",
        },
        201,
      );
    }
    if (url.endsWith("/sponsor-match")) {
      previews += 1;
      return json(
        previews === 1
          ? match("ambiguous_match", [
              candidate("Max Mustermann", "t1"),
              candidate("Max Mustermann", "t2"),
            ])
          : match("single_match", [
              candidate("Bäckerei Sonnenseite KG", "t-shared", true),
            ]),
      );
    }
    return json({ actionId, generatedAt: "", workItems: [], activities: [] });
  });
}

function type(id: string, value: string) {
  fireEvent.input(document.getElementById(id)!, { target: { value } });
}

describe("sponsor matching", () => {
  it("sends nothing on abort and asks before leaving until resolved", async () => {
    window.history.replaceState(null, "", "/app/sponsors?view=new");
    const resolves: Record<string, unknown>[] = [];
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <HotkeyProvider>
          <ToastProvider>
            <SponsorWorkspace
              client={matchingClient(resolves)}
              identity={identity}
            />
          </ToastProvider>
        </HotkeyProvider>
      </QueryClientProvider>,
    );
    const form = document.getElementById("sponsor-form")!;

    fireEvent.click(screen.getByRole("button", { name: "Privatperson" }));
    type("sponsor-given-name", "MAX");
    type("sponsor-family-name", "mustermann");
    fireEvent.click(screen.getByTestId("sponsor-preview"));
    await screen.findByRole("heading", { name: "Mehrere mögliche Treffer" });
    expect(
      (screen.getByTestId("sponsor-resolve") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByTestId("sponsor-cancel"));
    expect(
      screen.getByRole("region", { name: "Ergebnis der CRM-Prüfung" })
        .textContent,
    ).toContain("Noch keine CRM-Prüfung.");
    expect(
      (document.getElementById("sponsor-given-name") as HTMLInputElement)
        .disabled,
    ).toBe(false);
    expect(resolves).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Firma" }));
    type("sponsor-company", "Baeckerei  Sonnenseite K.G.");
    fireEvent.click(screen.getByTestId("sponsor-preview"));
    await screen.findByRole("heading", { name: "Ein eindeutiger Treffer" });
    const resolve = screen.getByTestId("sponsor-resolve") as HTMLButtonElement;
    expect(resolve.textContent).toContain("Als weitere Akquise eintragen");
    // The acquirer confirms the shared care themselves.
    expect(resolve.disabled).toBe(true);
    // In review nothing is saved: the shell's leave guard still counts it.
    expect(form.getAttribute("data-leave-guard")).toBeNull();
    fireEvent.click(screen.getByTestId("sponsor-confirm-shared"));
    expect(resolve.disabled).toBe(false);
    fireEvent.click(resolve);
    await waitFor(() => expect(resolves).toHaveLength(1));
    expect(resolves[0]).toMatchObject({
      confirmExistingAssignments: true,
      expectedStatus: "single_match",
      selectedTwentyId: "t-shared",
    });
    expect(resolves[0]!.commandId).toMatch(/^[0-9a-f-]{36}$/);
    // Saved: a tab just leaves.
    await waitFor(() =>
      expect(form.getAttribute("data-leave-guard")).toBe("off"),
    );
  });
});
