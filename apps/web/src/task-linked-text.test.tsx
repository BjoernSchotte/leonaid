import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkedText } from "../../../packages/features/src/tasks/task-detail";

describe("LinkedText", () => {
  it("links in-app paths and nothing else", () => {
    const { container } = render(
      <p>
        <LinkedText
          text={
            "Nicht geliefert.\nBestellung öffnen: /admin/orders?action=a&view=all&open=b\nSiehe https://evil.example/x und javascript:alert(1)"
          }
        />
      </p>,
    );
    const links = [...container.querySelectorAll("a")];
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/orders?action=a&view=all&open=b",
    ]);
    expect(container.textContent).toContain("Nicht geliefert.");
    expect(container.textContent).toContain("javascript:alert(1)");
  });
});
