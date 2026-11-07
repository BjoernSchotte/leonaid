import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
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
  type LegalConfigurationStateResponse,
  type LegalConfigurationValuesResponse,
  type LegalConfigurationVersionResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  LegalConfigurationPage,
  legalPart,
  resetCommandPaletteState,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const simoneId = "10000000-0000-4000-8000-000000000001";
const klaraId = "10000000-0000-4000-8000-000000000002";

beforeAll(() => {
  installDialogPolyfill();
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
  cleanup();
  resetCommandPaletteState();
  window.history.replaceState(null, "", "/admin/legal");
  vi.restoreAllMocks();
});

function values(
  overrides: Partial<LegalConfigurationValuesResponse> = {},
): LegalConfigurationValuesResponse {
  return {
    activationBlockers: [],
    bankAccountHolder: "Förderverein Lions Club Musterstadt e. V.",
    bic: null,
    consentTextVersion: "public-order-v1",
    eInvoiceDecision: "pending",
    eInvoiceEvidenceId: null,
    iban: "DE02120300000000202051",
    imprintPhone: "+49 821 123456",
    imprintRepresentatives: "Vorstand: Erika Muster (Präsidentin)",
    issuer: {
      city: "Augsburg",
      countryCode: "DE",
      email: "rechnung@verein.invalid",
      legalName: "Förderverein Lions Club Musterstadt e. V.",
      postalCode: "86150",
      streetLine1: "Musterstraße 12",
      taxIdentifier: "103/123/45678",
    },
    numberPrefix: "KT",
    numberWidth: 5,
    paymentTermsDays: 14,
    privacyContactEmail: "datenschutz@verein.invalid",
    privacyEvidenceId: "DATENSCHUTZ-2026-01",
    publicOrderLegalBasis: "Vertragserfüllung",
    publicOrderNoticeText: "Wir verarbeiten Ihre Bestellung.",
    retention: {
      auditDays: 3650,
      commitmentDays: 3650,
      consentEvidenceDays: 3650,
      contactDays: 730,
      invoiceDays: 3650,
    },
    taxEvidenceId: "STEUER-2026-01",
    taxNote: "Steuerbefreit.",
    taxRateBasisPoints: 0,
    taxTreatment: "tax_exempt",
    ...overrides,
  };
}

function version(
  number: number,
  by: { id: string; name: string },
  overrides: Partial<LegalConfigurationValuesResponse> = {},
): LegalConfigurationVersionResponse {
  return {
    createdAt: "2026-11-03T09:00:00Z",
    createdByDisplayName: by.name,
    createdByUserId: by.id,
    id: `00000000-0000-4000-8000-00000000000${number}`,
    values: values(overrides),
    version: number,
  };
}

const klara = { id: klaraId, name: "Klara Kern" };
const simone = { id: simoneId, name: "Simone System" };

const active = version(1, simone);
const pendingDraft = version(2, klara, {
  eInvoiceDecision: "not_required",
  eInvoiceEvidenceId: "ERECHNUNG-1",
});

function stateWith(
  overrides: Partial<LegalConfigurationStateResponse> = {},
): LegalConfigurationStateResponse {
  return {
    active,
    draft: pendingDraft,
    draftApproval: null,
    production: false,
    revision: 4,
    ...overrides,
  };
}

const approval = {
  approvedAt: "2026-11-03T10:00:00Z",
  approvedByDisplayName: "Simone System",
  approvedByUserId: simoneId,
  evidenceId: "FREIGABE-1",
};

function identity(userId: string, displayName: string) {
  return {
    actionMemberships: [],
    displayName,
    globalRoles: ["system_admin"],
    navigation: [],
    roleLabels: [],
    userId,
  } as unknown as CurrentIdentityResponse;
}

function fakeClient(initial: LegalConfigurationStateResponse) {
  return {
    getLegalConfiguration: vi.fn(async () => initial),
    saveLegalConfigurationDraft: vi.fn(),
    approveLegalConfigurationDraft: vi.fn(async () =>
      stateWith({ draftApproval: approval, revision: 5 }),
    ),
    activateLegalConfigurationDraft: vi.fn(async () =>
      stateWith({
        active: pendingDraft,
        draft: null,
        draftApproval: null,
        revision: 6,
      }),
    ),
  };
}

function renderPage(
  client: ReturnType<typeof fakeClient>,
  viewer = identity(simoneId, "Simone System"),
  url = "/admin/legal/e-invoice",
) {
  window.history.replaceState(null, "", url);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ToastProvider>
        <HotkeyProvider>
          <LegalConfigurationPage
            client={client as unknown as LeonAidApiClient}
            identity={viewer}
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("legalPart", () => {
  it("reads the part from the path and falls back to the first", () => {
    expect(legalPart("/admin/legal/e-invoice")).toBe("e-invoice");
    expect(legalPart("/admin/legal/imprint")).toBe("imprint");
    expect(legalPart("/admin/legal/privacy-page")).toBe("privacy-page");
    expect(legalPart("/admin/legal/")).toBe("carrier");
    expect(legalPart("/admin/legal/unknown")).toBe("carrier");
  });
});

describe("LegalConfigurationPage four-eyes flow", () => {
  it("never offers the author the approval", async () => {
    const client = fakeClient(stateWith());
    renderPage(client, identity(klaraId, "Klara Kern"));

    expect(
      (await screen.findByTestId("legal-author-lock")).textContent,
    ).toContain(
      "Klara Kern, Sie haben diesen Entwurf erstellt. Freigeben muss eine andere Person",
    );
    expect(
      screen.queryByRole("button", { name: "Entwurf freigeben" }),
    ).toBeNull();
    expect(screen.queryByLabelText(/Nachweis-ID der Freigabe/)).toBeNull();
    expect(screen.queryByTestId("legal-next-step")).toBeNull();
    // Nor the activation: the draft is not approved yet.
    expect(screen.queryByRole("button", { name: /aktivieren/ })).toBeNull();
  });

  it("lets a second admin approve and then activate after confirming", async () => {
    const client = fakeClient(stateWith());
    renderPage(client);

    const draft = await screen.findByTestId("legal-draft");
    expect(within(draft).getByText(/Wartet auf zweite Freigabe/)).toBeTruthy();
    // The diff shows the e-invoice change against the active version.
    expect(within(draft).getByText(/Noch zu prüfen/)).toBeTruthy();
    expect(within(draft).getByText(/Nicht erforderlich/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /aktivieren/ })).toBeNull();

    const approve = screen.getByRole("button", { name: "Entwurf freigeben" });
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Nachweis-ID der Freigabe/), {
      target: { value: "freigabe-1" },
    });
    fireEvent.click(approve);
    await waitFor(() =>
      expect(client.approveLegalConfigurationDraft).toHaveBeenCalledWith(
        pendingDraft.id,
        { evidenceId: "FREIGABE-1", expectedRevision: 4 },
      ),
    );

    expect(
      await screen.findByText(
        /Freigegeben von Simone System .* Nachweis FREIGABE-1/,
      ),
    ).toBeTruthy();
    fireEvent.click(
      await screen.findByRole("button", { name: "Version 2 aktivieren" }),
    );
    const dialog = await screen.findByRole("alertdialog", {
      name: "Version 2 aktivieren?",
    });
    expect(client.activateLegalConfigurationDraft).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Jetzt aktivieren" }),
    );
    await waitFor(() =>
      expect(client.activateLegalConfigurationDraft).toHaveBeenCalledWith(
        pendingDraft.id,
        { expectedRevision: 5 },
      ),
    );
    expect(await screen.findByText("Version 2 aktiv")).toBeTruthy();
    expect(screen.getByText("Kein offener Entwurf")).toBeTruthy();
  });

  it("shows the server's four-eyes refusal", async () => {
    const client = fakeClient(stateWith());
    client.approveLegalConfigurationDraft.mockRejectedValueOnce(
      new ApiError(409, {
        code: "legal_configuration_four_eyes_required",
        message: "Der Ersteller kann den eigenen Entwurf nicht freigeben.",
        requestId: "req-legal-1",
      }),
    );
    renderPage(client);

    fireEvent.change(await screen.findByLabelText(/Nachweis-ID der Freigabe/), {
      target: { value: "FREIGABE-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entwurf freigeben" }));
    expect(
      await screen.findByText(
        /Der Ersteller kann den eigenen Entwurf nicht freigeben\..*req-legal-1/,
      ),
    ).toBeTruthy();
    // Still waiting for the second approval.
    expect(screen.getByText(/Wartet auf zweite Freigabe/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /aktivieren/ })).toBeNull();
  });

  it("blocks the activation while blockers remain", async () => {
    const client = fakeClient(
      stateWith({
        draft: version(2, klara, {
          activationBlockers: ["e_invoice_decision_pending"],
        }),
        draftApproval: approval,
      }),
    );
    renderPage(client);

    expect((await screen.findByTestId("legal-blockers")).textContent).toContain(
      "Die E-Rechnungs-Pflicht ist noch nicht entschieden.",
    );
    expect(screen.queryByRole("button", { name: /aktivieren/ })).toBeNull();
    expect(
      within(screen.getByTestId("legal-next-step")).getByRole("button", {
        name: "Entwurf bearbeiten",
      }),
    ).toBeTruthy();
  });

  it("saves an edited draft with the current revision", async () => {
    const client = fakeClient(stateWith({ draft: null }));
    client.saveLegalConfigurationDraft.mockResolvedValueOnce(stateWith());
    renderPage(client);

    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    const editor = screen.getByTestId("legal-editor");
    fireEvent.change(within(editor).getByLabelText(/^E-Rechnung/), {
      target: { value: "not_required" },
    });
    fireEvent.change(
      within(editor).getByLabelText(/Nachweis-ID der Entscheidung/),
      { target: { value: "erechnung-1" } },
    );
    expect(within(editor).getByText("Nicht gespeichert")).toBeTruthy();
    fireEvent.click(
      within(editor).getByRole("button", { name: "Als Entwurf speichern" }),
    );
    await waitFor(() =>
      expect(client.saveLegalConfigurationDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          eInvoiceDecision: "not_required",
          eInvoiceEvidenceId: "ERECHNUNG-1",
          expectedRevision: 4,
          issuer: expect.objectContaining({
            legalName: active.values.issuer.legalName,
          }),
        }),
      ),
    );
    expect(await screen.findByTestId("legal-draft")).toBeTruthy();
  });

  it("opens the part with the first empty required field instead of saving", async () => {
    const client = fakeClient(stateWith({ active: null, draft: null }));
    renderPage(
      client,
      identity(simoneId, "Simone System"),
      "/admin/legal/e-invoice",
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Als Entwurf speichern" }),
    );
    expect(
      await screen.findByText(
        "Bitte füllen Sie „Name des Trägers“ im Bereich Träger & Anschrift aus.",
      ),
    ).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/legal/carrier");
    expect(client.saveLegalConfigurationDraft).not.toHaveBeenCalled();
  });

  it("names the blockers when the server refuses the activation", async () => {
    const approved = stateWith({ draftApproval: approval });
    const client = fakeClient(approved);
    client.activateLegalConfigurationDraft.mockRejectedValueOnce(
      new ApiError(409, {
        code: "legal_configuration_activation_blocked",
        message:
          "Die Konfiguration ist noch nicht produktionsreif: e_invoice_decision_pending.",
        requestId: "req-legal-2",
      }),
    );
    renderPage(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Version 2 aktivieren" }),
    );
    // Meanwhile someone else reopened the e-invoice decision.
    client.getLegalConfiguration.mockResolvedValue(
      stateWith({
        draft: version(2, klara, {
          activationBlockers: ["e_invoice_decision_pending"],
        }),
        draftApproval: approval,
      }),
    );
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Jetzt aktivieren" }),
    );
    expect(
      await screen.findByText(
        "Noch nicht aktivierbar: Die E-Rechnungs-Pflicht ist noch nicht entschieden.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/e_invoice_decision_pending/)).toBeNull();
  });

  it("does not call never-active versions replaced", async () => {
    const client = fakeClient(
      stateWith({ active: version(3, simone), draft: null }),
    );
    renderPage(client);
    const versions = await screen.findByTestId("legal-versions");
    expect(versions.textContent).toContain("Version 3 · aktiv");
    expect(versions.textContent).toContain("Version 1 bis 2");
    expect(versions.textContent).not.toContain("ersetzt");
  });

  it("trims and upper-cases evidence IDs before saving", async () => {
    const client = fakeClient(stateWith({ draft: null }));
    client.saveLegalConfigurationDraft.mockResolvedValueOnce(stateWith());
    renderPage(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    const editor = screen.getByTestId("legal-editor");
    fireEvent.change(
      within(editor).getByLabelText(/Nachweis-ID der Entscheidung/),
      { target: { value: "  erechnung-2 " } },
    );
    fireEvent.click(
      within(editor).getByRole("button", { name: "Als Entwurf speichern" }),
    );
    await waitFor(() =>
      expect(client.saveLegalConfigurationDraft).toHaveBeenCalledWith(
        expect.objectContaining({ eInvoiceEvidenceId: "ERECHNUNG-2" }),
      ),
    );
  });

  it("saves the Impressum fields; empty optional ones go out as null", async () => {
    const client = fakeClient(stateWith({ draft: null }));
    client.saveLegalConfigurationDraft.mockResolvedValueOnce(stateWith());
    renderPage(
      client,
      identity(simoneId, "Simone System"),
      "/admin/legal/imprint",
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    const editor = screen.getByTestId("legal-editor");
    expect(
      (within(editor).getByLabelText(/^Telefon/) as HTMLInputElement).type,
    ).toBe("tel");
    fireEvent.change(within(editor).getByLabelText(/^Registergericht/), {
      target: { value: "Amtsgericht Augsburg" },
    });
    fireEvent.change(within(editor).getByLabelText(/^Registernummer/), {
      target: { value: "VR 1234" },
    });
    fireEvent.change(within(editor).getByLabelText(/^Umsatzsteuer-ID/), {
      target: { value: " de123456789 " },
    });
    fireEvent.click(
      within(editor).getByRole("button", { name: "Als Entwurf speichern" }),
    );
    await waitFor(() =>
      expect(client.saveLegalConfigurationDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          imprintContentResponsibleAddress: null,
          imprintContentResponsibleName: null,
          imprintPhone: "+49 821 123456",
          imprintRegisterCourt: "Amtsgericht Augsburg",
          imprintRegisterNumber: "VR 1234",
          imprintRepresentatives: "Vorstand: Erika Muster (Präsidentin)",
          imprintVatId: "DE123456789",
        }),
      ),
    );
  });

  it("requires the representatives before saving", async () => {
    const client = fakeClient(
      stateWith({
        active: version(1, simone, { imprintRepresentatives: null }),
        draft: null,
      }),
    );
    renderPage(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Als Entwurf speichern" }),
    );
    expect(
      await screen.findByText(
        "Bitte füllen Sie „Vertretungsberechtigte“ im Bereich Impressum aus.",
      ),
    ).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/legal/imprint");
    expect(client.saveLegalConfigurationDraft).not.toHaveBeenCalled();
  });

  it("starts the privacy texts from the template, incl. device storage", async () => {
    const client = fakeClient(stateWith({ draft: null }));
    client.saveLegalConfigurationDraft.mockResolvedValueOnce(stateWith());
    renderPage(
      client,
      identity(simoneId, "Simone System"),
      "/admin/legal/privacy-page",
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    const editor = screen.getByTestId("legal-editor");
    const notice = within(editor).getByLabelText(
      /^Datenschutzhinweis für Mitglieder/,
    ) as HTMLTextAreaElement;
    expect(notice.value).toContain("## Speicherung auf deinem Gerät");
    expect(notice.value).toContain("Telefonnummer und E-Mail-Adresse");
    expect(notice.value).toContain("14 Tage");
    expect(notice.value).toContain("Wenn du dich abmeldest, löscht die App");
    const policy = within(editor).getByLabelText(
      /^Datenschutzerklärung/,
    ) as HTMLTextAreaElement;
    // Club facts stay placeholders for the club to fill in.
    expect(policy.value).toContain("[[");
    fireEvent.click(
      within(editor).getByRole("button", { name: "Als Entwurf speichern" }),
    );
    await waitFor(() =>
      expect(client.saveLegalConfigurationDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          memberPrivacyNoticeText: notice.value,
          privacyPolicyText: policy.value,
        }),
      ),
    );
  });

  it("keeps a stored privacy text instead of the template", async () => {
    const stored = "## Eigener Text\n\nDer Club hat diesen Text geschrieben.";
    const client = fakeClient(
      stateWith({
        active: version(1, simone, { privacyPolicyText: stored }),
        draft: null,
      }),
    );
    renderPage(
      client,
      identity(simoneId, "Simone System"),
      "/admin/legal/privacy-page",
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Neuen Entwurf beginnen" }),
    );
    expect(
      (
        within(screen.getByTestId("legal-editor")).getByLabelText(
          /^Datenschutzerklärung/,
        ) as HTMLTextAreaElement
      ).value,
    ).toBe(stored);
  });

  it("labels the Impressum and privacy blockers", async () => {
    const client = fakeClient(
      stateWith({
        draft: version(2, klara, {
          activationBlockers: [
            "imprint_representatives_missing",
            "imprint_phone_missing",
            "imprint_register_missing",
            "privacy_policy_missing",
            "member_privacy_notice_missing",
            "template_placeholder_open",
          ],
        }),
      }),
    );
    renderPage(client);
    const blockers = (await screen.findByTestId("legal-blockers")).textContent;
    for (const label of [
      "Im Impressum fehlen die vertretungsberechtigten Personen.",
      "Im Impressum fehlt die Telefonnummer.",
      "Im Impressum fehlt der Eintrag im Vereinsregister",
      "Die Datenschutzerklärung fehlt.",
      "Der Datenschutzhinweis für Mitglieder fehlt.",
      "offene Vorlagen-Platzhalter",
    ]) {
      expect(blockers).toContain(label);
    }
    expect(blockers).not.toContain("_missing");
  });
});
