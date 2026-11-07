/*
 * Device storage rules of specs/pwa-offline-queue §8.2–§8.5 that hold
 * without a browser: minimization, freshness, the identity summary and the
 * sealing of values. IndexedDB itself runs in the browser specs.
 */
import { describe, expect, it } from "vitest";

import type {
  AcquisitionActivityBoardResponse,
  CurrentIdentityResponse,
} from "@leonaid/api-client";
import {
  cacheFreshness,
  createDeviceKey,
  databaseName,
  identityFromSummary,
  minimizeBoard,
  seal,
  sessionEnded,
  summarizeIdentity,
  unseal,
} from "@leonaid/features/offline";

const NOW = new Date("2026-11-07T12:00:00Z");
const DAY = 86_400_000;

const board: AcquisitionActivityBoardResponse = {
  actionId: "20000000-0000-4000-8000-000000000001",
  generatedAt: NOW.toISOString(),
  activities: [
    {
      actionId: "20000000-0000-4000-8000-000000000001",
      actorDisplayName: "Tom Kollege",
      actorUserId: "10000000-0000-4000-8000-000000000009",
      assignmentId: "30000000-0000-4000-8000-000000000001",
      assignmentRevision: 3,
      channel: "phone",
      dueAt: null,
      id: "60000000-0000-4000-8000-000000000001",
      nextAction: null,
      note: "Chefin im Urlaub",
      occurredAt: NOW.toISOString(),
      outcome: "no_answer",
      partyDisplayName: "Bäckerei Kern",
      partyId: "40000000-0000-4000-8000-000000000001",
      partyKind: "company",
    },
  ],
  workItems: [
    {
      assignedAcquirers: [
        {
          displayName: "Tom Kollege",
          userId: "10000000-0000-4000-8000-000000000009",
        },
      ],
      assignmentId: "30000000-0000-4000-8000-000000000001",
      city: "Augsburg",
      contactName: "Klara Kern",
      dueAt: null,
      email: "klara@kern.example",
      nextAction: "Angebot schicken",
      partyDisplayName: "Bäckerei Kern",
      partyId: "40000000-0000-4000-8000-000000000001",
      partyKind: "company",
      phone: "+49 821 1234",
      postalCode: "86150",
      priority: 2,
      revision: 3,
      status: "contacted",
      suppressedChannels: ["email"],
      urgency: "none",
    },
    {
      assignedAcquirers: [],
      assignmentId: "30000000-0000-4000-8000-000000000002",
      city: null,
      contactName: null,
      dueAt: null,
      email: null,
      nextAction: null,
      partyDisplayName: "Übergeben GmbH",
      partyId: "40000000-0000-4000-8000-000000000002",
      partyKind: "company",
      phone: null,
      postalCode: null,
      priority: 1,
      revision: 1,
      status: "handed_over",
      suppressedChannels: [],
      urgency: "none",
    },
  ],
};

const identity: CurrentIdentityResponse = {
  actionMemberships: [
    {
      actionId: "20000000-0000-4000-8000-000000000001",
      actionName: "Krapfentaxi 2026",
      role: "acquirer",
      roleLabel: "Akquise",
    },
    {
      actionId: "20000000-0000-4000-8000-000000000002",
      actionName: "Lions Open",
      role: "charity_admin",
      roleLabel: "Charity-Admin",
    },
  ],
  displayName: "Anna Akquise",
  email: "anna@leonaid.invalid",
  freshLoginAt: NOW.toISOString(),
  freshUntil: NOW.toISOString(),
  globalRoles: ["finance_reader"],
  installation: { clubName: "Lions Club Augsburg" },
  landingPath: "/app/",
  navigation: [
    {
      href: "/app/sponsors",
      key: "sponsors",
      label: "Sponsoren",
      surface: "pwa",
    },
    { href: "/admin/", key: "overview", label: "Übersicht", surface: "web" },
  ],
  preferredSurface: "pwa",
  roleLabels: ["Akquise"],
  sessionExpiresAt: new Date(NOW.getTime() + 30 * DAY).toISOString(),
  sessionLastSeenAt: NOW.toISOString(),
  userId: "10000000-0000-4000-8000-000000000004",
};

describe("read cache minimization (§8.2)", () => {
  it("keeps own sponsors with contact data, no address, feed or colleagues", () => {
    const kept = minimizeBoard(board);
    expect(kept.activities).toEqual([]);
    expect(kept.workItems).toHaveLength(1);
    const [item] = kept.workItems;
    expect(item).toMatchObject({
      city: "Augsburg",
      contactName: "Klara Kern",
      email: "klara@kern.example",
      phone: "+49 821 1234",
      postalCode: null,
      assignedAcquirers: [],
      suppressedChannels: ["email"],
      revision: 3,
    });
    const serialized = JSON.stringify(kept);
    expect(serialized).not.toContain("86150");
    expect(serialized).not.toContain("Tom Kollege");
    expect(serialized).not.toContain("Chefin im Urlaub");
  });
});

describe("freshness (D3, §8.5)", () => {
  it("shows 7 days, blocks after that and deletes after 14", () => {
    const at = (days: number) =>
      new Date(NOW.getTime() - days * DAY).toISOString();
    expect(cacheFreshness(at(6.9), NOW)).toBe("fresh");
    expect(cacheFreshness(at(7.1), NOW)).toBe("stale");
    expect(cacheFreshness(at(13.9), NOW)).toBe("stale");
    expect(cacheFreshness(at(14.1), NOW)).toBe("expired");
    // A fetch time in the future means the clock moved: refresh first.
    expect(cacheFreshness(at(-1), NOW)).toBe("stale");
    expect(cacheFreshness("not a date", NOW)).toBe("stale");
  });
});

describe("identity summary (§8.1)", () => {
  it("keeps acquirer memberships and PWA navigation, not the e-mail", () => {
    const summary = summarizeIdentity(identity, NOW);
    expect(JSON.stringify(summary)).not.toContain("anna@leonaid.invalid");
    expect(summary.memberships.map((item) => item.role)).toEqual(["acquirer"]);
    expect(summary.navigation.map((item) => item.surface)).toEqual(["pwa"]);
    const restored = identityFromSummary(summary);
    expect(restored.userId).toBe(identity.userId);
    expect(restored.email).toBe("");
    expect(restored.globalRoles).toEqual([]);
    expect(restored.displayName).toBe("Anna Akquise");
  });

  it("refuses an offline start on an ended session", () => {
    const summary = summarizeIdentity(identity, NOW);
    expect(sessionEnded(summary, NOW)).toBe(false);
    expect(sessionEnded(summary, new Date(NOW.getTime() + 31 * DAY))).toBe(
      true,
    );
  });
});

describe("encryption at rest (§8.4)", () => {
  it("uses a non-extractable key and binds a value to its record", async () => {
    const key = await createDeviceKey();
    expect(key.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw", key)).rejects.toThrow();
    const sealed = await seal(key, "cache:board:1", { name: "Bäckerei Kern" });
    expect(new TextDecoder().decode(sealed.data)).not.toContain("Kern");
    await expect(unseal(key, "cache:board:1", sealed)).resolves.toEqual({
      name: "Bäckerei Kern",
    });
    // Copied under another record id, the value does not open.
    await expect(unseal(key, "cache:board:2", sealed)).rejects.toThrow();
    // Another device key cannot open it either.
    await expect(
      unseal(await createDeviceKey(), "cache:board:1", sealed),
    ).rejects.toThrow();
  });

  it("names the database by user id only", () => {
    expect(databaseName(identity.userId)).toBe(
      "leonaid-pwa-v1-10000000-0000-4000-8000-000000000004",
    );
    expect(() => databaseName("anna@leonaid.invalid")).toThrow();
  });
});
