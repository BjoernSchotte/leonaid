import { test, expect } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL,
  token = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !token) throw new Error("Survey member fixture required");
for (const scenario of ["Krapfentaxi", "Golf"])
  test(`nontechnical author creates previews and publishes ${scenario}`, async ({
    browser,
  }) => {
    test.setTimeout(90000);
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 1000 },
    });
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: token,
        url: baseURL,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const page = await context.newPage();
    await page.goto(`${baseURL}/admin/surveys/new`);
    await page
      .getByLabel("Titel der Umfrage", { exact: true })
      .fill(`${scenario} – Ihre Rückmeldung`);
    await page
      .getByRole("button", { name: "Umfrage erstellen", exact: true })
      .click();
    const editor = page.getByRole("region", { name: "Fragebogen bearbeiten" });
    await expect(editor).toBeVisible();
    const props = editor.getByRole("complementary", {
      name: "Frageeigenschaften",
    });
    const saved = () =>
      expect(page.locator("[data-draft-state]")).toHaveAttribute(
        "data-draft-state",
        "saved",
      );
    const add = async (type, title) => {
      await editor
        .getByRole("combobox", { name: "Fragetyp", exact: true })
        .selectOption(type);
      await editor
        .getByRole("button", { name: "Frage hinzufügen", exact: true })
        .click();
      await props.getByLabel("Fragetitel", { exact: true }).fill(title);
    };
    const nextPage = async (title) => {
      await editor
        .getByRole("button", { name: "Seite hinzufügen", exact: true })
        .click();
      await editor.getByLabel("Seitentitel", { exact: true }).fill(title);
    };
    const options = async (group, labels) => {
      const controls = props.getByRole("group", { name: group, exact: true });
      for (let i = 0; i < labels.length; i++) {
        if (
          (await controls
            .getByLabel(`Eintrag ${i + 1}`, { exact: true })
            .count()) === 0
        )
          await controls
            .getByRole("button", { name: "Eintrag hinzufügen", exact: true })
            .click();
        await controls
          .getByLabel(`Eintrag ${i + 1}`, { exact: true })
          .fill(labels[i]);
      }
    };
    const condition = async (source, operator, value) => {
      const rules = props.getByRole("group", {
        name: "Sichtbarkeit",
        exact: true,
      });
      await rules
        .getByRole("button", { name: "Regel hinzufügen", exact: true })
        .click();
      await rules
        .getByRole("combobox", { name: "Vorherige Frage 1", exact: true })
        .selectOption({ label: source });
      await rules
        .getByRole("combobox", { name: "Vergleich 1", exact: true })
        .selectOption(operator);
      if (operator === "contains")
        await rules
          .getByRole("combobox", { name: "Antwortwert 1", exact: true })
          .selectOption({ label: value });
      else
        await rules.getByLabel("Vergleichswert 1", { exact: true }).fill(value);
    };
    await editor
      .getByRole("button", {
        name: "Kurzer Text Was möchten Sie uns mitteilen?",
        exact: true,
      })
      .click();
    await props
      .getByRole("button", { name: "Frage entfernen", exact: true })
      .click();
    await editor
      .getByRole("combobox", { name: "Fortschritt anzeigen", exact: true })
      .selectOption("top");
    await editor
      .getByLabel("Text nach dem Abschluss", { exact: true })
      .fill("Danke für Ihre Rückmeldung.");
    if (scenario === "Krapfentaxi") {
      await add("rating", "Wie war die Lieferung?");
      await props.getByLabel("Skalenanfang", { exact: true }).fill("1");
      await props.getByLabel("Skalenende", { exact: true }).fill("5");
      await props.getByLabel("Schrittweite", { exact: true }).fill("1");
      await props
        .getByRole("checkbox", { name: "Antwort erforderlich", exact: true })
        .check();
      await add("comment", "Was können wir verbessern?");
      await props.getByLabel("Höchstlänge", { exact: true }).fill("1000");
      await condition("Wie war die Lieferung?", "<=", "2");
      await nextPage("Ihre Erfahrung");
      await add("radiogroup", "Wie frisch waren die Krapfen?");
      await options("Antwortmöglichkeiten", [
        "Frisch",
        "In Ordnung",
        "Nicht frisch",
      ]);
      await props
        .getByRole("checkbox", { name: "Antwort erforderlich", exact: true })
        .check();
      await add("comment", "Ihre Hinweise");
      await props.getByLabel("Höchstlänge", { exact: true }).fill("2000");
      await nextPage("Weiterempfehlung");
      await add("rating", "Wie wahrscheinlich empfehlen Sie uns weiter?");
      await props.getByLabel("Skalenanfang", { exact: true }).fill("0");
      await props.getByLabel("Skalenende", { exact: true }).fill("10");
      await props.getByLabel("Schrittweite", { exact: true }).fill("1");
      await props
        .getByRole("checkbox", { name: "Antwort erforderlich", exact: true })
        .check();
      await add("text", "Optionaler Name");
      await props.getByLabel("Höchstlänge", { exact: true }).fill("80");
    } else {
      await add("matrix", "Wie bewerten Sie das Turnier?");
      await options("Zeilen", ["Organisation", "Golfplatz", "Verpflegung"]);
      await options("Spalten", ["Schlecht", "Mittel", "Gut"]);
      await props
        .getByRole("checkbox", {
          name: "Alle Zeilen erforderlich",
          exact: true,
        })
        .check();
      await props
        .getByRole("checkbox", { name: "Antwort erforderlich", exact: true })
        .check();
      await nextPage("Verbesserungen");
      await add("checkbox", "Was sollen wir verbessern?");
      await options("Antwortmöglichkeiten", [
        "Zeitplan",
        "Essen",
        "Kommunikation",
      ]);
      await props.getByLabel("Höchstens auswählen", { exact: true }).fill("2");
      await add("comment", "Was wünschen Sie sich beim Essen?");
      await props.getByLabel("Höchstlänge", { exact: true }).fill("1000");
      await condition("Was sollen wir verbessern?", "contains", "Essen");
      await nextPage("Nächstes Mal");
      await add("dropdown", "Nehmen Sie wieder teil?");
      await options("Antwortmöglichkeiten", ["Ja", "Nein", "Vielleicht"]);
      await add("text", "Optionales Handicap");
      await props
        .getByRole("combobox", { name: "Eingabe", exact: true })
        .selectOption("number");
      await props.getByLabel("Minimum", { exact: true }).fill("-10");
      await props.getByLabel("Maximum", { exact: true }).fill("54");
      await add("text", "Wunschtermin");
      await props
        .getByRole("combobox", { name: "Eingabe", exact: true })
        .selectOption("date");
      await props.getByLabel("Minimum", { exact: true }).fill("2026-01-01");
      await props.getByLabel("Maximum", { exact: true }).fill("2027-12-31");
    }
    await saved();
    // Malformed presentation is stored as draft but cannot reach the renderer.
    await editor
      .getByRole("textbox", { name: "Beschreibung", exact: true })
      .fill("<img src=https://invalid.example/image>");
    await saved();
    await editor.getByRole("button", { name: "Vorschau", exact: true }).click();
    await expect(editor.getByRole("alert")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Fragebogen-Vorschau" }),
    ).toHaveCount(0);
    await editor
      .getByRole("textbox", { name: "Beschreibung", exact: true })
      .fill("Ihre Meinung hilft uns bei der nächsten Aktion.");
    await saved();
    let participationRequests = 0;
    page.on("request", (request) => {
      if (request.url().includes("/participations")) participationRequests++;
    });
    await editor.getByRole("button", { name: "Vorschau", exact: true }).click();
    const preview = page.getByRole("region", { name: "Fragebogen-Vorschau" });
    await expect(preview).toBeVisible();
    await expect(
      preview.getByText(`${scenario} – Ihre Rückmeldung`, { exact: true }),
    ).toBeVisible();
    if (scenario === "Krapfentaxi") {
      await preview.getByRole("radio").first().press("Space");
      await expect(
        preview.getByText("Was können wir verbessern?", { exact: true }),
      ).toBeVisible();
      await preview
        .getByRole("button", { name: "Weiter", exact: true })
        .click();
      await preview.getByRole("radio").first().press("Space");
      await preview
        .getByRole("button", { name: "Weiter", exact: true })
        .click();
      await preview.getByRole("radio").last().press("Space");
    } else {
      await expect(preview.getByRole("radio")).toHaveCount(9);
      for (const index of [0, 3, 6])
        await preview.getByRole("radio").nth(index).press("Space");
      await preview
        .getByRole("button", { name: "Weiter", exact: true })
        .click();
      await preview
        .getByRole("checkbox", { name: "Essen", exact: true })
        .press("Space");
      await expect(
        preview.getByRole("checkbox", { name: "Essen", exact: true }),
      ).toBeChecked();
      await expect(
        preview.getByText("Was wünschen Sie sich beim Essen?", { exact: true }),
      ).toBeVisible();
      await preview
        .getByRole("button", { name: "Weiter", exact: true })
        .click();
    }
    await preview
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(
      preview.getByText("Danke für Ihre Rückmeldung.", { exact: true }),
    ).toBeVisible();
    expect(participationRequests).toBe(0);
    await preview
      .getByRole("button", { name: "Zurück zum Editor", exact: true })
      .click();
    if (scenario === "Krapfentaxi") {
      let lost = false;
      await page.route("**/api/v1/surveys/*/publish", async (route) => {
        if (!lost) {
          lost = true;
          await route.fetch();
          await route.abort("failed");
        } else await route.continue();
      });
      await editor
        .getByRole("button", { name: "Veröffentlichen", exact: true })
        .click();
      await expect(editor.getByRole("alert")).toContainText(
        "Veröffentlichung noch nicht bestätigt",
      );
      await editor
        .getByRole("button", {
          name: "Veröffentlichung erneut prüfen",
          exact: true,
        })
        .click();
    } else
      await editor
        .getByRole("button", { name: "Veröffentlichen", exact: true })
        .click();
    await expect(
      editor.getByText("Version 1 ist veröffentlicht.", { exact: true }),
    ).toBeVisible();
    const id = page.url().split("/").at(-1);
    const published = await page.evaluate(
      async (id) => (await fetch(`/api/v1/public/surveys/${id}`)).json(),
      id,
    );
    expect(published.number).toBe(1);
    expect(published.definition.pages).toHaveLength(3);
    const questions = published.definition.pages.flatMap((p) => p.elements);
    expect(questions).toHaveLength(6);
    if (scenario === "Krapfentaxi") {
      expect(questions.filter((q) => q.isRequired)).toHaveLength(3);
      expect(
        questions.find((q) => q.title === "Optionaler Name").maxLength,
      ).toBe(80);
      expect(questions.find((q) => q.title === "Ihre Hinweise").maxLength).toBe(
        2000,
      );
    } else {
      expect(questions[0].rows).toHaveLength(3);
      expect(questions[0].columns.map((c) => c.value)).toEqual([1, 2, 3]);
      expect(
        questions.find((q) => q.type === "checkbox").maxSelectedChoices,
      ).toBe(2);
    }
    expect(published.definition.title).toBe(`${scenario} – Ihre Rückmeldung`);
    await page.reload();
    await expect(editor).toBeVisible();
    await expect(
      editor.getByLabel("Titel des Fragebogens", { exact: true }),
    ).toHaveValue(`${scenario} – Ihre Rückmeldung`);
    await page.screenshot({
      path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-authoring-${scenario}.png`,
      fullPage: true,
    });
    await context.close();
  });
