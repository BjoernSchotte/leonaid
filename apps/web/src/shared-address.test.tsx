import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";

import { TaskFromPage } from "../../../packages/features/src/knowledge/task-from-page";
import {
  AccessMembersPanel,
  type AccessMemberSource,
} from "../../../packages/features/src/shared/access-members";

function wrap(node: ReactNode) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {node}
    </QueryClientProvider>
  );
}

function source(): AccessMemberSource {
  return {
    queryKey: "test-members",
    label: "Freigaben",
    accessLabel: "Zugriff",
    subject: "diese Seite",
    list: async () => ({ items: [], nextOffset: null, revision: 1 }),
    change: vi.fn(async () => {
      throw new ApiError(409, {
        code: "conflict",
        message: "Konflikt",
        requestId: "req-1",
      });
    }),
    dependentQueryKeys: [],
  };
}

async function refuseAccessChange(address: "Sie" | "du") {
  render(
    wrap(
      <AccessMembersPanel
        actionScoped={false}
        address={address}
        objectId="page-1"
        source={source()}
      />,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Freigaben" }));
  fireEvent.change(await screen.findByLabelText("E-Mail-Adresse"), {
    target: { value: "anna@example.invalid" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zugriff speichern" }));
  return screen.findByText(/Die Zugriffsrechte wurden inzwischen geändert/);
}

describe("shared panels follow the page's address", () => {
  it("say Sie on admin pages", async () => {
    const message = await refuseAccessChange("Sie");
    expect(message.textContent).toContain(
      "Laden Sie die Zugriffe neu und prüfen Sie Ihre Eingabe.",
    );
  });

  it("say du in the app", async () => {
    const message = await refuseAccessChange("du");
    expect(message.textContent).toContain(
      "Lade die Zugriffe neu und prüfe deine Eingabe.",
    );
  });

  it("asks admins to pick a task list with Sie", async () => {
    const client = {
      listTaskLists: vi.fn(async () => ({ items: [], nextOffset: null })),
    } as unknown as LeonAidApiClient;
    render(
      wrap(
        <TaskFromPage
          address="Sie"
          client={client}
          createTask={vi.fn()}
          onClose={vi.fn()}
          userId="u1"
        />,
      ),
    );
    expect(
      await screen.findByText(
        "Wählen Sie eine Liste, in der Sie Aufgaben anlegen dürfen.",
      ),
    ).toBeTruthy();
    expect(screen.getByText(/Legen Sie bei Bedarf/)).toBeTruthy();
  });
});
