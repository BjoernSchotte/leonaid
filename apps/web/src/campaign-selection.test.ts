import {
  CAMPAIGN_SCOPED_NAV_KEYS,
  CAMPAIGN_STORAGE_KEY,
  readStoredCampaign,
  selectCampaign,
  storeCampaign,
  withCampaign,
} from "@leonaid/features";

const campaigns = [
  { id: "a1", name: "Krapfentaxi" },
  { id: "a2", name: "Weihnachtsmarkt" },
];

describe("campaign selection", () => {
  afterEach(() => window.sessionStorage.clear());

  it("carries the campaign into the money areas", () => {
    expect(CAMPAIGN_SCOPED_NAV_KEYS.has("invoices")).toBe(true);
    expect(CAMPAIGN_SCOPED_NAV_KEYS.has("donations")).toBe(true);
    expect(CAMPAIGN_SCOPED_NAV_KEYS.has("members")).toBe(false);
  });

  it("lets the URL win on pages that read it", () => {
    expect(
      selectCampaign({
        campaigns,
        scoped: true,
        urlActionId: "a2",
        storedActionId: "a1",
      }),
    ).toBe("a2");
  });

  it("keeps the stored choice on pages that ignore the campaign", () => {
    expect(
      selectCampaign({
        campaigns,
        scoped: false,
        urlActionId: "a1",
        storedActionId: "a2",
      }),
    ).toBe("a2");
  });

  it("never selects a campaign the admin pages reject", () => {
    expect(
      selectCampaign({
        campaigns,
        scoped: true,
        urlActionId: "pwa-only",
        storedActionId: "gone",
        fallbackActionId: "a2",
      }),
    ).toBe("a2");
  });

  it("shows no campaign on the management page of a foreign campaign", () => {
    expect(
      selectCampaign({
        campaigns,
        scoped: false,
        managedActionId: "foreign",
        urlActionId: "",
        storedActionId: "a1",
      }),
    ).toBe("");
    expect(
      selectCampaign({
        campaigns,
        scoped: false,
        managedActionId: "a2",
        urlActionId: "",
        storedActionId: "a1",
      }),
    ).toBe("a2");
  });

  it("stores the choice per tab", () => {
    storeCampaign("a2");
    expect(window.sessionStorage.getItem(CAMPAIGN_STORAGE_KEY)).toBe("a2");
    expect(readStoredCampaign()).toBe("a2");
  });

  it("adds the campaign to links and keeps other parameters", () => {
    expect(withCampaign("/admin/orders", "a1")).toBe("/admin/orders?action=a1");
    expect(withCampaign("/admin/invoices?status=open", "a2")).toBe(
      "/admin/invoices?status=open&action=a2",
    );
    expect(withCampaign("/admin/orders?action=a1", "a2")).toBe(
      "/admin/orders?action=a2",
    );
    expect(withCampaign("/admin/orders", "")).toBe("/admin/orders");
  });
});
