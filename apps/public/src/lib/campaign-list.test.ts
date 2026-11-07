import type { PublicCampaignListItemResponse } from "@leonaid/api-client";
import { describe, expect, it } from "vitest";
import {
  createCampaignListReader,
  lastKnownMaxAgeMilliseconds,
} from "./campaign-list";

const campaign = (slug: string): PublicCampaignListItemResponse => ({
  archiveSlug: slug,
  name: slug,
  purpose: "Zweck",
  carrierName: "Lions Club",
  presentationTheme: null,
  startsOn: "2026-11-01",
  endsOn: "2026-12-01",
  canonicalPath: `/${slug}`,
  canonicalUrl: `https://club.org/${slug}`,
});

describe("cached home campaign list", () => {
  it("serves one Core read for 60 s and shares concurrent renders", async () => {
    let now = 0;
    let calls = 0;
    const read = createCampaignListReader(
      async () => {
        calls += 1;
        return [campaign(`a${calls}`)];
      },
      () => now,
    );
    const [first, second] = await Promise.all([read(), read()]);
    expect(calls).toBe(1);
    expect(first).toBe(second);
    now = 59_999;
    expect((await read())[0].archiveSlug).toBe("a1");
    now = 60_000;
    expect((await read())[0].archiveSlug).toBe("a2");
    expect(calls).toBe(2);
  });

  it("keeps the last list on a failure and retries after 10 s", async () => {
    let now = 0;
    let fail = false;
    let calls = 0;
    const read = createCampaignListReader(
      async () => {
        calls += 1;
        if (fail) throw new Error("core down");
        return [campaign("a")];
      },
      () => now,
    );
    await read();
    fail = true;
    now = 60_000;
    expect((await read()).map((item) => item.archiveSlug)).toEqual(["a"]);
    now = 69_999;
    await read();
    expect(calls).toBe(2);
    now = 70_000;
    fail = false;
    await read();
    expect(calls).toBe(3);
  });

  it("drops the last list once it is older than 15 minutes", async () => {
    let now = 0;
    let fail = false;
    const read = createCampaignListReader(
      async () => {
        if (fail) throw new Error("core down");
        return [campaign("a")];
      },
      () => now,
    );
    await read();
    fail = true;
    now = lastKnownMaxAgeMilliseconds;
    expect((await read()).map((item) => item.archiveSlug)).toEqual(["a"]);
    now = lastKnownMaxAgeMilliseconds + 10_001;
    expect(await read()).toEqual([]);
    // Core back: the list returns.
    fail = false;
    now += 10_000;
    expect((await read()).map((item) => item.archiveSlug)).toEqual(["a"]);
  });

  it("yields an empty list when Core was never reachable", async () => {
    const read = createCampaignListReader(async () => {
      throw new Error("core down");
    });
    expect(await read()).toEqual([]);
  });
});
