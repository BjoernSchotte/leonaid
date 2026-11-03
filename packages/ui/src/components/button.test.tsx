import { Plus } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Button, IconButton } from "./button";

describe("Button", () => {
  it("keeps primary as the product default at md size", () => {
    const markup = renderToStaticMarkup(<Button>Speichern</Button>);
    expect(markup).toContain('class="btn btn-primary btn-md"');
    expect(markup).toContain('type="button"');
    expect(markup).toContain('<span class="btn-label">Speichern</span>');
  });

  it.each(["primary", "secondary", "ghost", "danger", "zone"] as const)(
    "renders the %s variant",
    (variant) => {
      expect(
        renderToStaticMarkup(<Button variant={variant}>x</Button>),
      ).toContain(`class="btn btn-${variant} btn-md"`);
    },
  );

  it("renders a Lucide icon at 14 px for sm and 16 px otherwise", () => {
    const small = renderToStaticMarkup(
      <Button icon={Plus} size="sm">
        Neu
      </Button>,
    );
    expect(small).toContain("btn-sm");
    expect(small).toMatch(/<svg[^>]*width="14"[^>]*aria-hidden="true"/);
    const medium = renderToStaticMarkup(<Button icon={Plus}>Neu</Button>);
    expect(medium).toMatch(/<svg[^>]*width="16"/);
  });

  it("passes an icon element through unchanged", () => {
    const markup = renderToStaticMarkup(
      <Button icon={<svg data-testid="legacy" />}>Alt</Button>,
    );
    expect(markup).toContain('<svg data-testid="legacy"></svg>');
  });

  it("renders subtle keycaps for a shortcut", () => {
    const markup = renderToStaticMarkup(<Button shortcut="c">Neu</Button>);
    expect(markup).toContain('class="kbd-group is-subtle"');
    expect(markup).toContain('<kbd class="kbd">C</kbd>');
    // The label names the action; keycaps must not change the accessible name.
    expect(markup).not.toContain("kbd-text");
  });

  it("swaps the icon for a spinner while loading", () => {
    const markup = renderToStaticMarkup(
      <Button icon={Plus} loading>
        Wird gesendet
      </Button>,
    );
    expect(markup).toContain("disabled");
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toMatch(/<span[^>]*class="spinner"[^>]*><\/span>/);
    expect(markup).toMatch(/<span aria-hidden="true" class="spinner">/);
    expect(markup).not.toContain("<svg");
  });

  it("keeps native button props", () => {
    const markup = renderToStaticMarkup(
      <Button className="extra" name="save" type="submit">
        Senden
      </Button>,
    );
    expect(markup).toContain('type="submit"');
    expect(markup).toContain('name="save"');
    expect(markup).toContain("btn btn-primary btn-md extra");
  });
});

describe("IconButton", () => {
  it("is square and labelled", () => {
    const markup = renderToStaticMarkup(<IconButton icon={Plus} label="Neu" />);
    expect(markup).toContain('class="btn btn-icon btn-ghost btn-md"');
    expect(markup).toContain('aria-label="Neu"');
    expect(markup).toContain('title="Neu"');
    expect(markup).toMatch(/<svg[^>]*width="18"[^>]*aria-hidden="true"/);
  });
});
