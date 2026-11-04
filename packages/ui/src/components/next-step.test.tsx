import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NextStep, ReadOnlyNotice } from "./next-step";

describe("NextStep", () => {
  it("leads with the bold label, the consequence and the actions", () => {
    const markup = renderToStaticMarkup(
      <NextStep
        action={<button type="button">Planen</button>}
        alternatives={<button type="button">Später</button>}
        consequence="Danach ist die Aktion öffentlich angekündigt."
        data-testid="step"
      />,
    );
    expect(markup).toContain('class="next-step"');
    expect(markup).toContain('data-testid="step"');
    expect(markup).toContain(
      "<p><strong>Nächster Schritt:</strong> Danach ist die Aktion öffentlich angekündigt.</p>",
    );
    expect(markup).toMatch(
      /class="next-step-actions"><button[^>]*>Planen<\/button><button[^>]*>Später<\/button>/,
    );
  });

  it("takes another lead", () => {
    expect(
      renderToStaticMarkup(
        <NextStep action={null} consequence="x" lead="Überfällig." />,
      ),
    ).toContain("<strong>Überfällig.</strong>");
  });
});

describe("ReadOnlyNotice", () => {
  it("is a note that starts with Nur lesen.", () => {
    const markup = renderToStaticMarkup(
      <ReadOnlyNotice>Ihre Rolle zeigt die Aktion.</ReadOnlyNotice>,
    );
    expect(markup).toContain('class="callout"');
    expect(markup).toContain('role="note"');
    expect(markup).toContain(
      "<strong>Nur lesen.</strong> Ihre Rolle zeigt die Aktion.",
    );
  });
});
