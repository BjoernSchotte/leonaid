import { Plus } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Icon } from "./icon";

describe("Icon", () => {
  it("is decorative without a label", () => {
    const markup = renderToStaticMarkup(<Icon icon={Plus} />);
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).not.toContain("role=");
    expect(markup).toContain('width="16"');
  });

  it("becomes a labelled image with a label", () => {
    const markup = renderToStaticMarkup(
      <Icon icon={Plus} label="Hinzufügen" size={20} />,
    );
    expect(markup).toContain('role="img"');
    expect(markup).toContain('aria-label="Hinzufügen"');
    expect(markup).not.toContain("aria-hidden");
    expect(markup).toContain('width="20"');
  });
});
