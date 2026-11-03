// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field, FormField, Input, Select, Textarea } from "./form-field";

afterEach(cleanup);

describe("Field", () => {
  it("links aria-describedby to the hint", () => {
    render(
      <Field
        hint="Wir senden Ihnen einen Anmeldecode."
        id="demo-email"
        label="E-Mail-Adresse"
      >
        <input type="email" />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "E-Mail-Adresse" });
    expect(input.id).toBe("demo-email");
    expect(input.getAttribute("aria-describedby")).toBe("demo-email-hint");
    expect(input.getAttribute("aria-invalid")).toBeNull();
    const hint = document.getElementById("demo-email-hint");
    expect(hint?.className).toBe("field-hint");
    expect(hint?.textContent).toBe("Wir senden Ihnen einen Anmeldecode.");
  });

  it("links aria-describedby to the error, sets aria-invalid and replaces the hint", () => {
    render(
      <Field
        error="Bitte den vollständigen Rechnungsbetrag erfassen: 144,00 €."
        hint="Betrag in Euro"
        id="demo-amount"
        label="Betrag"
      >
        <input aria-describedby="extra" defaultValue="140,00" />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Betrag" });
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe(
      "extra demo-amount-error",
    );
    expect(document.getElementById("demo-amount-hint")).toBeNull();
    const error = document.getElementById("demo-amount-error");
    expect(error?.className).toBe("field-error");
    expect(input.closest(".field")?.className).toBe("field has-error");
  });

  it("renders the prototype label, optional marker and control classes", () => {
    render(
      <>
        <Field id="a" label="Notiz" optional>
          <textarea />
        </Field>
        <Field id="b" label="Vorlage">
          <select>
            <option>Krapfentaxi</option>
          </select>
        </Field>
        <Field id="c" label="Name">
          <input className="extra" />
        </Field>
      </>,
    );
    const label = screen.getByText("Notiz").closest("label");
    expect(label?.className).toBe("field-label");
    expect(label?.getAttribute("for")).toBe("a");
    expect(label?.querySelector(".field-optional")?.textContent).toBe(
      " (optional)",
    );
    expect(document.getElementById("a")?.className).toBe("input textarea");
    expect(document.getElementById("b")?.className).toBe("input select");
    expect(document.getElementById("c")?.className).toBe("input extra");
  });

  it("generates an id when none is given", () => {
    render(
      <Field hint="Hinweis" label="Ort">
        <input />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Ort" });
    expect(input.id).not.toBe("");
    expect(input.getAttribute("aria-describedby")).toBe(`${input.id}-hint`);
  });
});

describe("FormField", () => {
  it("keeps description and required, marked as Pflichtfeld", () => {
    render(
      <FormField description="Kurze Adresse" label="Alias" required>
        <input />
      </FormField>,
    );
    const input = screen.getByRole("textbox", { name: /Alias/ });
    expect(input).toHaveProperty("required", true);
    expect(input.getAttribute("aria-describedby")).toBe(`${input.id}-hint`);
    expect(screen.getByText("(Pflichtfeld)", { exact: false })).toBeTruthy();
  });
});

describe("Input, Textarea, Select", () => {
  it("render the prototype control classes", () => {
    render(
      <>
        <Input aria-label="i" className="x" />
        <Textarea aria-label="t" />
        <Select aria-label="s">
          <option>1</option>
        </Select>
      </>,
    );
    expect(screen.getByRole("textbox", { name: "i" }).className).toBe(
      "input x",
    );
    expect(screen.getByRole("textbox", { name: "t" }).className).toBe(
      "input textarea",
    );
    expect(screen.getByRole("combobox", { name: "s" }).className).toBe(
      "input select",
    );
  });
});
