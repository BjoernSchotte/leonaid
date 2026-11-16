import { describe, expect, it } from "vitest";
import {
  campaignImageSources,
  mediaVersion,
  publicMediaPath,
  publicMediaSrcset,
} from "./published-media.mjs";

const ID = "01M7GMYTRPMC0Y4CZHJ7RXP14C";
const HASH = "0123456789abcdef".repeat(4);
const SLUG = "krapfentaxi-2027";
const base = `/campaigns/${SLUG}/media/${ID}`;

describe("versioned campaign media URLs (E-067)", () => {
  it("names the first 64 bits of the content hash", () => {
    expect(mediaVersion(HASH)).toBe("0123456789abcdef");
    expect(() => mediaVersion("abc")).toThrow("invalid_public_media_hash");
  });

  it("keeps the plain path without a hash and adds version and width", () => {
    expect(publicMediaPath(SLUG, ID)).toBe(base);
    expect(publicMediaPath(SLUG, ID, { contentHash: HASH })).toBe(
      `${base}?v=0123456789abcdef`,
    );
    expect(publicMediaPath(SLUG, ID, { contentHash: HASH, width: 960 })).toBe(
      `${base}?v=0123456789abcdef&w=960`,
    );
    expect(() =>
      publicMediaPath(SLUG, ID, { contentHash: HASH, width: 1000 }),
    ).toThrow("invalid_public_media_width");
    expect(() => publicMediaPath("Bad Slug", ID)).toThrow(
      "invalid_public_media_path",
    );
  });

  it("offers every smaller width plus the original, never an enlargement", () => {
    expect(
      publicMediaSrcset(SLUG, ID, { contentHash: HASH, width: 1600 }),
    ).toBe(
      [
        `${base}?v=0123456789abcdef&w=480 480w`,
        `${base}?v=0123456789abcdef&w=960 960w`,
        `${base}?v=0123456789abcdef&w=1440 1440w`,
        `${base}?v=0123456789abcdef 1600w`,
      ].join(", "),
    );
    expect(
      publicMediaSrcset(SLUG, ID, { contentHash: HASH, width: 480 }),
    ).toBeNull();
  });

  it("falls back to the unversioned path without media facts", () => {
    expect(campaignImageSources(SLUG, ID, {})).toEqual({
      src: base,
      srcset: undefined,
    });
    expect(
      campaignImageSources(SLUG, ID, {
        [ID]: { contentHash: HASH, width: 300 },
      }),
    ).toEqual({ src: `${base}?v=0123456789abcdef`, srcset: undefined });
  });
});
