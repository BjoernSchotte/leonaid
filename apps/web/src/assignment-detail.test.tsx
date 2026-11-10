import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  type AcquisitionActivityWorkItemResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";

import {
  AssignmentDetail,
  CRM_PARTY_GONE_LABEL,
} from "../../../packages/features/src/acquisition/assignment-detail";

const actionId = "20000000-0000-4000-8000-000000000001";
const assignmentId = "60000000-0000-4000-8000-000000000001";

function workItem(
  values: Partial<AcquisitionActivityWorkItemResponse> = {},
): AcquisitionActivityWorkItemResponse {
  return {
    assignedAcquirers: [{ displayName: "Anna Akquise", userId: "anna" }],
    assignmentId,
    city: null,
    contactName: null,
    dueAt: "2026-12-05T08:00:00+00:00",
    email: null,
    nextAction: "Anrufen",
    partyDisplayName: CRM_PARTY_GONE_LABEL,
    partyId: "40000000-0000-4000-8000-000000000001",
    partyKind: "company",
    phone: null,
    postalCode: null,
    priority: 2,
    revision: 7,
    status: "contacted",
    suppressedChannels: [],
    urgency: "upcoming",
    ...values,
  };
}

/** A real API client; the transport answers like the assignment endpoints. */
function assignmentClient(updates: Record<string, unknown>[]) {
  return new LeonAidApiClient("", async (input, init = {}) => {
    if (init.method === "PATCH") {
      updates.push({ body: JSON.parse(String(init.body)), url: String(input) });
    }
    const assignment = {
      acquirerDisplayName: "Anna Akquise",
      acquirerUserId: "anna",
      actionId,
      createdAt: "2026-07-01T08:00:00+00:00",
      dueAt: null,
      id: assignmentId,
      nextAction: null,
      partyId: "40000000-0000-4000-8000-000000000001",
      partyKind: "company",
      priority: 2,
      revision: 8,
      status: "declined",
      updatedAt: "2026-11-10T08:00:00+00:00",
    };
    return new Response(
      JSON.stringify(
        init.method === "PATCH" ? assignment : { assignment, history: [] },
      ),
      { headers: { "Content-Type": "application/json" }, status: 200 },
    );
  });
}

function show(
  item: AcquisitionActivityWorkItemResponse,
  updates: Record<string, unknown>[] = [],
) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AssignmentDetail
        actionId={actionId}
        client={assignmentClient(updates)}
        item={item}
      />
    </QueryClientProvider>,
  );
}

describe("assignment of a sponsor the CRM no longer has", () => {
  it("uses the label of the server", () => {
    const server = readFileSync(
      new URL(
        "../../../src/leonaid/application/activities.py",
        import.meta.url,
      ),
      "utf8",
    );
    expect(server).toContain(
      `CRM_PARTY_GONE_LABEL = "${CRM_PARTY_GONE_LABEL}"`,
    );
  });

  it("says so and ends the assignment as declined", async () => {
    const updates: Record<string, unknown>[] = [];
    show(workItem(), updates);

    expect(
      screen.getByText("Sponsor im CRM nicht mehr vorhanden"),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Zuordnung abschließen" }),
    );

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0]).toEqual({
      body: {
        dueAt: null,
        nextAction: null,
        priority: 2,
        revision: 7,
        status: "declined",
      },
      url: `/api/v1/actions/${actionId}/acquisition/assignments/${assignmentId}`,
    });
  });

  it.each(["declined", "handed_over"] as const)(
    "offers nothing to end when it is %s",
    (status) => {
      show(workItem({ status }));
      expect(
        screen.getByText("Sponsor im CRM nicht mehr vorhanden"),
      ).toBeTruthy();
      expect(
        screen.queryByRole("button", { name: "Zuordnung abschließen" }),
      ).toBeNull();
    },
  );

  it("shows no notice for a sponsor the CRM has", () => {
    show(workItem({ partyDisplayName: "Musterwerk GmbH" }));
    expect(
      screen.queryByText("Sponsor im CRM nicht mehr vorhanden"),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Zuordnung abschließen" }),
    ).toBeNull();
  });
});
