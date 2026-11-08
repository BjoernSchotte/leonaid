import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type MemberDirectoryActionResponse,
  type MemberDirectoryMemberResponse,
  type MemberDirectoryResponse,
} from "@leonaid/api-client";
import {
  MemberAdministrationPage,
  resetCommandPaletteState,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import {
  familyNameKey,
  loadMemberDirectory,
  migrateLegacyInviteParam,
  roleFilterValues,
} from "../../../packages/features/src/action-admin/member-model";
import {
  INVITE_DRAFT_KEY,
  INVITE_DRAFT_TTL_MS,
  saveInviteDraft,
  takeInviteDraft,
} from "../../../packages/features/src/action-admin/invite-draft";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const ownAction = "20000000-0000-4000-8000-000000000001";
const foreignAction = "20000000-0000-4000-8000-000000000003";
const archivedAction = "20000000-0000-4000-8000-000000000002";
const adminId = "10000000-0000-4000-8000-000000000001";
const annaId = "10000000-0000-4000-8000-000000000004";
const klaraId = "10000000-0000-4000-8000-000000000002";

beforeAll(() => {
  installDialogPolyfill();
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  resetCommandPaletteState();
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/admin/members");
  vi.restoreAllMocks();
});

function member(
  userId: string,
  displayName: string,
  overrides: Partial<MemberDirectoryMemberResponse> = {},
): MemberDirectoryMemberResponse {
  return {
    actionMemberships: [],
    activeSessionCount: 1,
    displayName,
    email: `${displayName.toLowerCase().replace(/\s+/g, ".")}@leonaid.invalid`,
    globalRoleLabels: [],
    globalRoles: [],
    lastLoginAt: "2026-11-01T10:00:00Z",
    revision: 3,
    status: "active",
    statusLabel: "Aktiv",
    userId,
    ...overrides,
  };
}

const members: MemberDirectoryMemberResponse[] = [
  member(adminId, "Simone System", {
    globalRoles: ["system_admin"],
    globalRoleLabels: ["System-Admin"],
  }),
  member(klaraId, "Klara Kern", {
    actionMemberships: [
      {
        actionId: ownAction,
        actionName: "Krapfentaxi 2026",
        role: "charity_admin",
        roleLabel: "Charity-Admin",
      },
      {
        actionId: archivedAction,
        actionName: "Krapfentaxi 2025",
        role: "charity_admin",
        roleLabel: "Charity-Admin",
      },
    ],
  }),
  member(annaId, "Anna Akquise", {
    actionMemberships: [
      {
        actionId: ownAction,
        actionName: "Krapfentaxi 2026",
        role: "acquirer",
        roleLabel: "Akquisiteur",
      },
      {
        actionId: foreignAction,
        actionName: "Krapfentaxi Nord 2026",
        role: "driver",
        roleLabel: "Ausfahrer",
      },
    ],
  }),
  member("10000000-0000-4000-8000-000000000005", "Gesa Gesperrt", {
    status: "suspended",
    statusLabel: "Gesperrt",
    lastLoginAt: null,
  }),
];

const ownActionEntry: MemberDirectoryActionResponse = {
  actionId: ownAction,
  actionName: "Krapfentaxi 2026",
  availableRoles: ["charity_admin", "acquirer", "finance_reader", "driver"],
  leadRequired: true,
};

const archivedActionEntry: MemberDirectoryActionResponse = {
  actionId: archivedAction,
  actionName: "Krapfentaxi 2025",
  availableRoles: ["charity_admin", "acquirer", "finance_reader"],
  leadRequired: false,
};

function identity(systemAdmin: boolean): CurrentIdentityResponse {
  return {
    actionMemberships: [],
    displayName: systemAdmin ? "Simone System" : "Klara Kern",
    email: "x@leonaid.invalid",
    freshLoginAt: "2026-11-03T10:00:00Z",
    freshUntil: "2026-11-03T10:10:00Z",
    globalRoles: systemAdmin ? ["system_admin"] : [],
    navigation: [],
    roleLabels: [],
    sessionExpiresAt: "2026-11-04T10:00:00Z",
    sessionLastSeenAt: "2026-11-03T10:00:00Z",
    landingPath: "/admin/",
    userId: systemAdmin ? adminId : klaraId,
  } as unknown as CurrentIdentityResponse;
}

function fakeClient({
  partial = false,
  pages = [members],
}: {
  readonly partial?: boolean;
  readonly pages?: readonly (readonly MemberDirectoryMemberResponse[])[];
} = {}) {
  return {
    listMembers: vi.fn(
      async ({
        cursor,
      }: {
        cursor?: string;
      }): Promise<MemberDirectoryResponse> => {
        const index = cursor ? Number(cursor) : 0;
        return {
          actions: [ownActionEntry, archivedActionEntry],
          items: [...(pages[index] ?? [])],
          nextCursor: index + 1 < pages.length ? String(index + 1) : null,
          partial,
          total: pages.flat().length,
        };
      },
    ),
    getMember: vi.fn(async (userId: string) => {
      const found = pages.flat().find((item) => item.userId === userId);
      if (!found) throw new Error("unknown member");
      return found;
    }),
    changeMemberActionRole: vi.fn(),
    changeMemberGlobalRole: vi.fn(),
    changeMemberStatus: vi.fn(),
    createMemberEmailChange: vi.fn(),
    getInvitationOptions: vi.fn(async () => ({
      actions: [{ id: ownAction, name: "Krapfentaxi 2026" }],
      roles: [
        { label: "Akquisiteur", value: "acquirer" },
        { label: "Ausfahrer", value: "driver" },
      ],
    })),
    createInvitation: vi.fn(async () => ({
      invitationId: "inv-1",
      status: "queued",
    })),
    listInvitations: vi.fn(async () => ({ items: [] })),
  };
}

async function renderPage(
  options: {
    readonly client?: ReturnType<typeof fakeClient>;
    readonly systemAdmin?: boolean;
    readonly url?: string;
  } = {},
) {
  window.history.replaceState(null, "", options.url ?? "/admin/members");
  const client = options.client ?? fakeClient();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HotkeyProvider>
          <MemberAdministrationPage
            client={client as unknown as LeonAidApiClient}
            identity={identity(options.systemAdmin ?? true)}
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return client;
}

async function openMember(name: string) {
  const link = (await screen.findAllByText(name))
    .find((element) => element.closest(".row-link"))
    ?.closest("a");
  if (!link) throw new Error(`row ${name} not shown`);
  fireEvent.click(link);
  return within(await screen.findByTestId("member-detail"));
}

function confirmDialog() {
  return within(screen.getByRole("alertdialog"));
}

describe("member model", () => {
  it("sorts by family name and keeps both finance scopes apart", () => {
    expect(familyNameKey("Klara Kern")).toBe("Kern Klara");
    expect(
      roleFilterValues(
        member("u", "Fiona Finanz", {
          globalRoles: ["finance_reader"],
          actionMemberships: [
            {
              actionId: ownAction,
              actionName: "A",
              role: "finance_reader",
              roleLabel: "Finanzen lesen",
            },
          ],
        }),
      ),
    ).toEqual(["global:finance_reader", "action:finance_reader"]);
  });

  it("walks every page and keeps a member once", async () => {
    const client = fakeClient({
      pages: [members.slice(0, 2), [members[1]!, ...members.slice(2)]],
    });
    const directory = await loadMemberDirectory(
      client as unknown as LeonAidApiClient,
    );
    expect(client.listMembers).toHaveBeenCalledTimes(2);
    expect(client.listMembers).toHaveBeenLastCalledWith(
      { cursor: "1", limit: 100 },
      {},
    );
    expect(directory.items.map((item) => item.displayName)).toEqual([
      "Simone System",
      "Klara Kern",
      "Anna Akquise",
      "Gesa Gesperrt",
    ]);
    expect(directory.truncated).toBe(false);
  });

  it("turns the old invite tab link into the create request", () => {
    window.history.replaceState(null, "", "/admin/members?view=invite&x=1");
    migrateLegacyInviteParam();
    expect(window.location.search).toBe("?x=1&create=member-invitation");
  });
});

describe("invite draft", () => {
  const draft = {
    email: "neu@leonaid.invalid",
    displayName: "Nora Neu",
    actionId: ownAction,
    role: "acquirer" as const,
  };

  it("returns the draft once to the same account within 15 minutes", () => {
    saveInviteDraft(adminId, draft, 1_000);
    expect(takeInviteDraft(adminId, 1_000 + INVITE_DRAFT_TTL_MS)).toEqual(
      draft,
    );
    expect(window.sessionStorage.getItem(INVITE_DRAFT_KEY)).toBeNull();
    expect(takeInviteDraft(adminId, 2_000)).toBeNull();
  });

  it("drops a draft of another account", () => {
    saveInviteDraft(klaraId, draft, 1_000);
    expect(takeInviteDraft(adminId, 2_000)).toBeNull();
    expect(window.sessionStorage.getItem(INVITE_DRAFT_KEY)).toBeNull();
  });

  it("drops an expired, future-dated or broken draft", () => {
    saveInviteDraft(adminId, draft, 1_000);
    expect(takeInviteDraft(adminId, 1_001 + INVITE_DRAFT_TTL_MS)).toBeNull();
    saveInviteDraft(adminId, draft, 5_000);
    expect(takeInviteDraft(adminId, 1_000)).toBeNull();
    window.sessionStorage.setItem(INVITE_DRAFT_KEY, "{not json");
    expect(takeInviteDraft(adminId)).toBeNull();
    window.sessionStorage.setItem(
      INVITE_DRAFT_KEY,
      JSON.stringify({ ...draft, userId: adminId }),
    );
    expect(takeInviteDraft(adminId)).toBeNull();
  });
});

describe("member list", () => {
  it("lists every member, sorted by family name, with views", async () => {
    await renderPage();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Mitglieder" }),
    ).toBeTruthy();
    await screen.findByText("4 Mitglieder");
    const names = [...document.querySelectorAll(".row-link .row-primary")].map(
      (element) => element.textContent,
    );
    expect(names).toEqual([
      "Anna Akquise",
      "Gesa Gesperrt",
      "Klara Kern",
      "Simone System",
    ]);
    fireEvent.click(
      within(
        screen.getByRole("navigation", { name: "Gespeicherte Ansichten" }),
      ).getByRole("button", { name: "Gesperrt" }),
    );
    await screen.findByText("1 von 4");
    expect(window.location.search).toBe("?view=blocked");
  });

  it("opens the invitation dialog for ?view=invite and sends the invitation", async () => {
    const client = await renderPage({ url: "/admin/members?view=invite" });
    const dialog = within(
      await screen.findByRole("dialog", { name: "Mitglied einladen" }),
    );
    expect(window.location.search).toBe("");
    await dialog.findByTestId("invite-action");
    fireEvent.click(dialog.getByTestId("invite-submit"));
    expect(
      dialog.getByText(
        "Bitte eine gültige E-Mail-Adresse eingeben, z. B. name@beispiel.de.",
      ),
    ).toBeTruthy();
    expect(client.createInvitation).not.toHaveBeenCalled();
    fireEvent.change(dialog.getByLabelText("E-Mail-Adresse"), {
      target: { value: "neu@leonaid.invalid" },
    });
    fireEvent.change(dialog.getByLabelText("Name"), {
      target: { value: "Nora Neu" },
    });
    const directoryLoads = client.listMembers.mock.calls.length;
    fireEvent.click(dialog.getByTestId("invite-submit"));
    // The new "Eingeladen" member is loaded right away.
    await waitFor(() =>
      expect(client.listMembers.mock.calls.length).toBeGreaterThan(
        directoryLoads,
      ),
    );
    await waitFor(() =>
      expect(client.createInvitation).toHaveBeenCalledWith({
        actionId: ownAction,
        displayName: "Nora Neu",
        email: "neu@leonaid.invalid",
        role: "acquirer",
      }),
    );
    expect(
      await screen.findByText("Einladung an neu@leonaid.invalid gesendet."),
    ).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Mitglied einladen" }),
      ).toBeNull(),
    );
  });

  it("reopens the invitation with its draft after the fresh sign-in", async () => {
    const client = await renderPage({
      url: "/admin/members?create=member-invitation",
    });
    client.createInvitation.mockRejectedValueOnce(
      new ApiError(401, {
        code: "fresh_login_required",
        message: "Bitte erneut anmelden.",
        requestId: "req-4",
      }),
    );
    let dialog = within(
      await screen.findByRole("dialog", { name: "Mitglied einladen" }),
    );
    await dialog.findByTestId("invite-action");
    fireEvent.change(dialog.getByLabelText("E-Mail-Adresse"), {
      target: { value: "neu@leonaid.invalid" },
    });
    fireEvent.change(dialog.getByLabelText("Name"), {
      target: { value: "Nora Neu" },
    });
    const assign = vi.fn();
    const { pathname, search } = window.location;
    const location = vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname,
      search,
    } as Location);
    fireEvent.click(dialog.getByTestId("invite-submit"));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        `/fresh-login?returnTo=${encodeURIComponent("/admin/members?create=member-invitation")}`,
      ),
    );
    expect(assign).toHaveBeenCalledTimes(1);
    location.mockRestore();
    cleanup();

    // Back from /fresh-login: the dialog opens with the typed draft.
    await renderPage({ url: "/admin/members?create=member-invitation" });
    dialog = within(
      await screen.findByRole("dialog", { name: "Mitglied einladen" }),
    );
    expect(
      (dialog.getByLabelText("E-Mail-Adresse") as HTMLInputElement).value,
    ).toBe("neu@leonaid.invalid");
    expect((dialog.getByLabelText("Name") as HTMLInputElement).value).toBe(
      "Nora Neu",
    );
    expect(
      window.sessionStorage.getItem("leonaid.member-invite-draft"),
    ).toBeNull();
  });

  it("shows the server's refusal instead of the list", async () => {
    const client = fakeClient();
    client.listMembers.mockRejectedValue(
      new ApiError(403, {
        code: "member_directory_forbidden",
        message: "Keine Berechtigung.",
        requestId: "req-1",
      }),
    );
    await renderPage({ client });
    expect(
      await screen.findByRole("heading", {
        name: "Mitglieder konnten nicht geladen werden",
      }),
    ).toBeTruthy();
    expect(document.querySelector(".listview")).toBeNull();
  });
});

describe("member pane", () => {
  it("grants an action role only after the confirmation, with revision and key", async () => {
    const client = await renderPage();
    client.changeMemberActionRole.mockResolvedValue({
      actionId: ownAction,
      actionName: "Krapfentaxi 2026",
      enabled: true,
      replayed: false,
      revision: 4,
      role: "finance_reader",
      roleLabel: "Finanzen lesen",
      scope: "action",
      userId: annaId,
    });
    const pane = await openMember("Anna Akquise");
    expect(window.location.search).toBe(`?open=${annaId}`);
    fireEvent.change(pane.getByTestId("member-role-add-role"), {
      target: { value: "finance_reader" },
    });
    fireEvent.click(pane.getByTestId("member-role-add-submit"));
    expect(client.changeMemberActionRole).not.toHaveBeenCalled();
    fireEvent.click(
      confirmDialog().getByRole("button", { name: "Rolle zuweisen" }),
    );
    await waitFor(() =>
      expect(client.changeMemberActionRole).toHaveBeenCalledWith(
        annaId,
        ownAction,
        "finance_reader",
        { enabled: true, expectedRevision: 3 },
        {
          headers: {
            "Idempotency-Key": expect.stringMatching(/^pilot012:member-role:/),
          },
        },
      ),
    );
    expect(
      await screen.findByText(
        "Finanzen lesen wurde zugewiesen · Krapfentaxi 2026.",
      ),
    ).toBeTruthy();
  });

  it("offers only roles in actions the account manages", async () => {
    await renderPage();
    const pane = await openMember("Anna Akquise");
    expect(
      pane.getByTestId(`member-revoke-action-${ownAction}-acquirer`),
    ).toBeTruthy();
    expect(
      pane.queryByTestId(`member-revoke-action-${foreignAction}-driver`),
    ).toBeNull();
    const roleOptions = [
      ...pane.getByTestId("member-role-add-role").querySelectorAll("option"),
    ].map((option) => option.value);
    expect(roleOptions).toEqual(["charity_admin", "finance_reader", "driver"]);
  });

  it("sends a role change that needs a fresh sign-in to /fresh-login and back to the pane", async () => {
    const client = await renderPage();
    client.changeMemberActionRole.mockRejectedValue(
      new ApiError(403, {
        code: "fresh_login_required",
        message: "Bitte erneut anmelden.",
        requestId: "req-2",
      }),
    );
    const pane = await openMember("Anna Akquise");
    fireEvent.click(
      pane.getByTestId(`member-revoke-action-${ownAction}-acquirer`),
    );
    const assign = vi.fn();
    const { pathname, search } = window.location;
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname,
      search,
    } as Location);
    fireEvent.click(
      confirmDialog().getByRole("button", { name: "Rolle entziehen" }),
    );
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        `/fresh-login?returnTo=${encodeURIComponent(`/admin/members?open=${annaId}`)}`,
      ),
    );
    expect(assign).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/wurde entzogen/)).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("keeps the last charity admin only where the server requires one", async () => {
    const client = await renderPage();
    client.changeMemberActionRole.mockRejectedValue(
      new ApiError(409, {
        code: "last_charity_admin_role_forbidden",
        message: "Die letzte Charity-Admin-Rolle bleibt.",
        requestId: "req-3",
      }),
    );
    const pane = await openMember("Klara Kern");
    // Running action (leadRequired): blocked with the badge and a toast.
    expect(pane.getAllByText("Letzter Charity-Admin")).toHaveLength(1);
    fireEvent.click(
      pane.getByTestId(`member-revoke-action-${ownAction}-charity_admin`),
    );
    expect(
      await screen.findByText(
        "Klara Kern ist der letzte Charity-Admin von Krapfentaxi 2026.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(client.changeMemberActionRole).not.toHaveBeenCalled();

    // Archived action: the server allows it, so the UI asks and sends it.
    fireEvent.click(
      pane.getByTestId(`member-revoke-action-${archivedAction}-charity_admin`),
    );
    fireEvent.click(
      confirmDialog().getByRole("button", { name: "Rolle entziehen" }),
    );
    await waitFor(() =>
      expect(client.changeMemberActionRole).toHaveBeenCalledWith(
        klaraId,
        archivedAction,
        "charity_admin",
        { enabled: false, expectedRevision: 3 },
        expect.anything(),
      ),
    );
    // A 409 refusal is no revision conflict: no "Aktuellen Stand laden".
    expect(
      await pane.findByText("Der letzte aktive Charity-Admin bleibt"),
    ).toBeTruthy();
    expect(pane.queryByText("Aktuellen Stand laden")).toBeNull();
  });

  it("warns before suspending or archiving the last active lead", async () => {
    await renderPage();
    const pane = await openMember("Klara Kern");
    expect(pane.getByTestId("member-access-guard").textContent).toContain(
      "Letzter aktiver Charity-Admin von Krapfentaxi 2026.",
    );
    expect(
      (pane.getByTestId("member-status-suspend") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (pane.getByTestId("member-status-archive") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("offers a reload when the actor's own rights changed mid-command", async () => {
    const client = await renderPage();
    client.changeMemberActionRole.mockRejectedValue(
      new ApiError(409, {
        code: "role_action_scope_changed",
        message: "Ihre Verwaltungsrolle wurde zwischenzeitlich geändert.",
        requestId: "req-5",
      }),
    );
    const pane = await openMember("Anna Akquise");
    fireEvent.click(
      pane.getByTestId(`member-revoke-action-${ownAction}-acquirer`),
    );
    fireEvent.click(
      confirmDialog().getByRole("button", { name: "Rolle entziehen" }),
    );
    expect(
      await pane.findByText(
        "Ihre Berechtigung wurde zwischenzeitlich geändert",
      ),
    ).toBeTruthy();
    expect(
      pane.getByRole("button", { name: "Aktuellen Stand laden" }),
    ).toBeTruthy();
  });

  it("suspends through the confirmation and reports the ended sessions", async () => {
    const client = await renderPage();
    client.changeMemberStatus.mockResolvedValue({
      displayName: "Anna Akquise",
      previousStatus: "active",
      previousStatusLabel: "Aktiv",
      replayed: false,
      revision: 4,
      revokedSessionCount: 1,
      status: "suspended",
      statusLabel: "Gesperrt",
      userId: annaId,
    });
    const pane = await openMember("Anna Akquise");
    fireEvent.click(pane.getByTestId("member-status-suspend"));
    expect(
      confirmDialog().getByText(
        "Anna Akquise verliert sofort den Zugriff. Die aktive Sitzung wird unwiderruflich beendet.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      confirmDialog().getByRole("button", { name: "Zugang sperren" }),
    );
    expect(await screen.findByText("Anna Akquise ist gesperrt.")).toBeTruthy();
    expect(screen.getByText("1 Sitzung wurde sofort beendet.")).toBeTruthy();
    expect(client.changeMemberStatus).toHaveBeenCalledWith(
      annaId,
      { expectedRevision: 3, status: "suspended" },
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^pilot011:member-status:/),
        },
      },
    );
  });

  it("reactivates through the confirmation and asks for a new sign-in", async () => {
    const client = await renderPage();
    const gesaId = "10000000-0000-4000-8000-000000000005";
    client.changeMemberStatus.mockResolvedValue({
      displayName: "Gesa Gesperrt",
      previousStatus: "suspended",
      previousStatusLabel: "Gesperrt",
      replayed: false,
      revision: 4,
      revokedSessionCount: 0,
      status: "active",
      statusLabel: "Aktiv",
      userId: gesaId,
    });
    const pane = await openMember("Gesa Gesperrt");
    fireEvent.click(pane.getByTestId("member-status-reactivate"));
    expect(
      confirmDialog().getByText(
        "Gesa Gesperrt erhält wieder Zugriff. Alte Sitzungen bleiben beendet; die Person muss sich neu anmelden.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      confirmDialog().getByRole("button", { name: "Zugang reaktivieren" }),
    );
    expect(
      await screen.findByText("Gesa Gesperrt ist wieder aktiv."),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Für den nächsten Zugriff ist eine neue Anmeldung erforderlich.",
      ),
    ).toBeTruthy();
    expect(client.changeMemberStatus).toHaveBeenCalledWith(
      gesaId,
      { expectedRevision: 3, status: "active" },
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^pilot011:member-status:/),
        },
      },
    );
  });

  it("guards the only system admin and the own access", async () => {
    await renderPage();
    const pane = await openMember("Simone System");
    expect(
      pane.getByText(/Einziger aktiver System-Admin\. Diese Rolle/),
    ).toBeTruthy();
    expect(
      (
        pane.getByTestId(
          "member-revoke-global-system_admin",
        ) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(pane.getByTestId("member-status-self")).toBeTruthy();
    expect(pane.queryByTestId("member-status-suspend")).toBeNull();
  });

  it("hides club-wide roles and access controls in the charity admin's scope", async () => {
    await renderPage({
      client: fakeClient({ partial: true }),
      systemAdmin: false,
    });
    expect(await screen.findByTestId("member-scope-note")).toBeTruthy();
    const pane = await openMember("Anna Akquise");
    expect(pane.queryByText("Systemrollen")).toBeNull();
    expect(pane.queryByText("Zugang")).toBeNull();
    expect(pane.queryByTestId("member-email-change-open")).toBeNull();
    expect(pane.getByTestId("member-scope-pane-note")).toBeTruthy();
    // A partial directory leaves the last-lead hint to the server.
    await openMember("Klara Kern");
    await screen.findByRole("heading", { level: 2, name: "Klara Kern" });
    const klara = within(screen.getByTestId("member-detail"));
    expect(klara.getAllByTestId("member-membership").length).toBeGreaterThan(0);
    expect(klara.queryByText("Letzter Charity-Admin")).toBeNull();
  });

  it("keeps the typed login address through the fresh sign-in", async () => {
    const client = await renderPage({ url: `/admin/members?open=${annaId}` });
    client.createMemberEmailChange.mockRejectedValueOnce(
      new ApiError(401, {
        code: "fresh_login_required",
        message: "Bitte erneut anmelden.",
        requestId: "req-7",
      }),
    );
    const pane = within(await screen.findByTestId("member-detail"));
    fireEvent.click(pane.getByTestId("member-email-change-open"));
    const dialog = within(
      await screen.findByRole("dialog", { name: "Anmeldeadresse ändern" }),
    );
    fireEvent.change(dialog.getByTestId("member-email-change-input"), {
      target: { value: "anna.neu@leonaid.invalid" },
    });
    const assign = vi.fn();
    const { pathname, search } = window.location;
    const location = vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname,
      search,
    } as Location);
    fireEvent.click(dialog.getByTestId("member-email-change-submit"));
    await waitFor(() => expect(assign).toHaveBeenCalledTimes(1));
    location.mockRestore();
    cleanup();

    // Back from /fresh-login: the form is open again with the address.
    await renderPage({ url: `/admin/members?open=${annaId}` });
    const restored = within(
      await screen.findByRole("dialog", { name: "Anmeldeadresse ändern" }),
    );
    expect(
      (restored.getByTestId("member-email-change-input") as HTMLInputElement)
        .value,
    ).toBe("anna.neu@leonaid.invalid");
  });

  it("names an invalid login address in the field, not a browser bubble", async () => {
    const client = await renderPage({ url: `/admin/members?open=${annaId}` });
    const pane = within(await screen.findByTestId("member-detail"));
    fireEvent.click(pane.getByTestId("member-email-change-open"));
    const dialog = within(
      await screen.findByRole("dialog", { name: "Anmeldeadresse ändern" }),
    );
    const form = dialog
      .getByTestId("member-email-change-input")
      .closest("form") as HTMLFormElement;
    expect(form.noValidate).toBe(true);
    fireEvent.change(dialog.getByTestId("member-email-change-input"), {
      target: { value: "kein-at" },
    });
    fireEvent.click(dialog.getByTestId("member-email-change-submit"));
    expect(
      await dialog.findByText(/Bitte eine gültige E-Mail-Adresse eingeben/),
    ).toBeTruthy();
    expect(client.createMemberEmailChange).not.toHaveBeenCalled();
  });

  it("keeps the invitation open until the send settles", async () => {
    const client = await renderPage({
      url: "/admin/members?create=member-invitation",
    });
    let finish: (value: unknown) => void = () => {};
    client.createInvitation.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }) as never,
    );
    const dialog = within(
      await screen.findByRole("dialog", { name: "Mitglied einladen" }),
    );
    await dialog.findByTestId("invite-action");
    fireEvent.change(dialog.getByLabelText("E-Mail-Adresse"), {
      target: { value: "neu@leonaid.invalid" },
    });
    fireEvent.change(dialog.getByLabelText("Name"), {
      target: { value: "Nora Neu" },
    });
    fireEvent.click(dialog.getByTestId("invite-submit"));
    await waitFor(() =>
      expect(
        (dialog.getByRole("button", { name: "Abbrechen" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );
    await act(async () => {
      finish({ invitationId: "inv-2", status: "queued" });
    });
  });

  it("reopens the pane from ?open= after the fresh sign-in", async () => {
    await renderPage({ url: `/admin/members?open=${annaId}` });
    const pane = within(await screen.findByTestId("member-detail"));
    expect(pane.getByTestId("member-detail-status").textContent).toBe("Aktiv");
    await act(async () => {});
  });
});
