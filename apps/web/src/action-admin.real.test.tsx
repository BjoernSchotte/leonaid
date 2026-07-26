import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LeonAidApiClient, type FetchLike } from "@leonaid/api-client";
import { ManageActionPage } from "@leonaid/features";

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value)
    throw new Error(`${name} ist für den echten Komponententest nötig`);
  return value;
}

const apiBaseUrl = requiredEnvironment("LEONAID_COMPONENT_API_BASE_URL");
const actionId = requiredEnvironment("LEONAID_COMPONENT_ACTION_ID");
const session = requiredEnvironment("LEONAID_COMPONENT_SESSION");

const authenticatedFetch: FetchLike = (input, init = {}) => {
  const headers = new Headers(init.headers);
  headers.set("Cookie", `__Host-leonaid_session=${session}`);
  return fetch(input, { ...init, headers });
};

function renderManagement(client: LeonAidApiClient) {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { refetchOnWindowFocus: false, retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ManageActionPage actionId={actionId} client={client} />
    </QueryClientProvider>,
  );
}

describe("Charity-Admin-Aktionsverwaltung mit echtem Core", () => {
  test("lädt Golden Data, speichert real und bewahrt Eingaben bei Revisionskonflikt", async () => {
    expect(globalThis.fetch).toBeTypeOf("function");
    expect("mock" in globalThis.fetch).toBe(false);
    const client = new LeonAidApiClient(apiBaseUrl, authenticatedFetch);
    const initial = await client.getCharityActionManagement(actionId);
    const view = renderManagement(client);
    const user = userEvent.setup();

    expect(
      (await screen.findByTestId("management-title")).textContent,
    ).toContain(initial.action.name);
    expect((screen.getByTestId("manage-goal") as HTMLInputElement).value).toBe(
      initial.action.goal.goalValue ?? "",
    );
    expect(screen.getByText("Verantwortliche Admins")).toBeTruthy();
    expect(screen.getByText("Veröffentlichung")).toBeTruthy();

    const actual = screen.getByTestId("manage-actual");
    await user.clear(actual);
    await user.type(actual, "90500");
    await user.click(screen.getByTestId("save-goal"));
    expect(
      await screen.findByText(
        "Aktionsziel und Fortschritt wurden gespeichert.",
      ),
    ).toBeTruthy();

    const afterSuccess = await client.getCharityActionManagement(actionId);
    expect(afterSuccess.action.goal.actualValue).toBe("90500");

    await waitFor(() => {
      expect(
        (screen.getByTestId("manage-actual") as HTMLInputElement).value,
      ).toBe("90500");
    });
    await user.clear(actual);
    await user.type(actual, "92000");

    await client.setCharityActionGoal(actionId, {
      actualValue: "91500",
      currency: afterSuccess.action.goal.currency,
      goalValue: afterSuccess.action.goal.goalValue,
      revision: afterSuccess.action.revision,
      unit: afterSuccess.action.goal.unit,
    });
    await user.click(screen.getByTestId("save-goal"));

    expect(
      await screen.findByText(/zwischenzeitlich von jemand anderem geändert/),
    ).toBeTruthy();
    expect(
      (screen.getByTestId("manage-actual") as HTMLInputElement).value,
    ).toBe("92000");
    const persisted = await client.getCharityActionManagement(actionId);
    expect(persisted.action.goal.actualValue).toBe("91500");

    view.unmount();
  }, 30_000);
});
