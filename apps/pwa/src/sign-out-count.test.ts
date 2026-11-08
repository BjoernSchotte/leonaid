// @vitest-environment jsdom
/*
 * The sign-out count (specs/pwa-offline-queue §12.5, #132 N3): it covers
 * every user sign-out deletes and fails closed when the store cannot be
 * read. IndexedDB itself runs in the browser specs; here it is a stub.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  databaseName,
  pendingDeviceEntries,
  setActiveDeviceUser,
} from "@leonaid/features/offline";

const SIGNED_IN = "10000000-0000-4000-8000-000000000004";
const ACTIVE = "10000000-0000-4000-8000-000000000005";

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function stubIndexedDb(names: string[]) {
  const open = vi.fn(() => {
    throw new Error("storage broken");
  });
  vi.stubGlobal("indexedDB", {
    databases: async () => names.map((name) => ({ name, version: 1 })),
    open,
  });
  return open;
}

describe("sign-out count (§12.5)", () => {
  it("is 0 without a database, and never creates one to count", async () => {
    const open = stubIndexedDb([]);
    setActiveDeviceUser(ACTIVE);
    expect(await pendingDeviceEntries(SIGNED_IN)).toBe(0);
    expect(open).not.toHaveBeenCalled();
  });

  it("is unknown (null) when a database of a deleted user cannot be read", async () => {
    // The active device user is not the signed-in one; sign-out deletes
    // both, so both are counted.
    const open = stubIndexedDb([databaseName(ACTIVE)]);
    setActiveDeviceUser(ACTIVE);
    expect(await pendingDeviceEntries(SIGNED_IN)).toBeNull();
    expect(open).toHaveBeenCalledWith(databaseName(ACTIVE), expect.anything());
  });

  it("is unknown (null) when the device cannot list its databases", async () => {
    vi.stubGlobal("indexedDB", {
      databases: async () => {
        throw new Error("blocked");
      },
    });
    expect(await pendingDeviceEntries(SIGNED_IN)).toBeNull();
  });
});
