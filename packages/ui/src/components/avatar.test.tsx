import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Avatar, avatarHueBucket, initialsFor } from "./avatar";

describe("Avatar", () => {
  it("derives initials from the name", () => {
    expect(initialsFor("Anna Akquise")).toBe("AA");
    expect(initialsFor("  simone   von system ")).toBe("SS");
    expect(initialsFor("Özlem")).toBe("ÖZ");
    expect(initialsFor("")).toBe("?");
  });

  it("picks a stable hue bucket from the name", () => {
    const bucket = avatarHueBucket("Anna Akquise");
    expect(bucket).toBe(avatarHueBucket("Anna Akquise"));
    expect(bucket).toBeGreaterThanOrEqual(0);
    expect(bucket).toBeLessThan(24);
    const buckets = new Set(
      ["Anna", "Bernd", "Clara", "Dieter", "Emil", "Frida"].map(
        avatarHueBucket,
      ),
    );
    expect(buckets.size).toBeGreaterThan(1);
  });

  it("is decorative by default and uses class buckets, never style", () => {
    const markup = renderToStaticMarkup(<Avatar name="Anna Akquise" />);
    expect(markup).toMatch(/class="avatar avatar-sm avatar-h\d{1,2}"/);
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toMatch(/>AA<\/span>$/);
    expect(markup).not.toContain("style=");
  });

  it("becomes an image with a label", () => {
    const markup = renderToStaticMarkup(
      <Avatar label="Anna Akquise" name="Anna Akquise" size="md" />,
    );
    expect(markup).toContain("avatar-md");
    expect(markup).toContain('role="img"');
    expect(markup).toContain('aria-label="Anna Akquise"');
    expect(markup).not.toContain("aria-hidden");
  });
});
