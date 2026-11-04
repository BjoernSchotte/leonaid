import { CircleAlert } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Badge } from "./badge";

describe("Badge", () => {
  it("defaults to the neutral tone", () => {
    expect(renderToStaticMarkup(<Badge>Entwurf</Badge>)).toBe(
      '<span class="badge tone-neutral">Entwurf</span>',
    );
  });

  it("renders the tone and a decorative 12 px icon", () => {
    const markup = renderToStaticMarkup(
      <Badge icon={CircleAlert} tone="danger">
        Versand fehlgeschlagen
      </Badge>,
    );
    expect(markup).toMatch(/^<span class="badge tone-danger"><svg/);
    expect(markup).toContain('width="12"');
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain("Versand fehlgeschlagen");
  });
});
