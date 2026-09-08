import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  SurveyEditor,
  formatEditorMessage,
  type EditorTranslator,
} from "@leonaid/surveys/editor";
import type { AuthoringAdapter, Draft } from "@leonaid/surveys/contracts";
import "@leonaid/surveys/editor-styles";
import "./host.css";

const call = async (method: string, body?: unknown) =>
  (
    await fetch("/api/editor", {
      method,
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  ).json();
const adapter: AuthoringAdapter = {
  loadDraft: () => call("GET"),
  saveDraft: (_, input) => call("PUT", input),
  validateDraft: (_, expectedRevision) => call("POST", { expectedRevision }),
  publish: async () => ({
    ok: false,
    error: {
      code: "forbidden",
      message: "This demo does not publish",
      diagnostics: [],
    },
  }),
};
const catalogue: Record<string, string> = {
  "Fragebogen bearbeiten": "Edit questionnaire",
  "Titel des Fragebogens": "Questionnaire title",
  Seitentitel: "Page title",
  Fragetitel: "Question title",
  "Neue Seite": "New page",
  "Neue Frage": "New question",
  "Seite hinzufügen": "Add page",
  "Frage hinzufügen": "Add question",
  "Entwurf gespeichert": "Draft saved",
  Rückgängig: "Undo",
  Vorschau: "Preview",
  "Zurück zum Editor": "Back to editor",
  "Vorschau · Antworten werden nicht gespeichert":
    "Preview · answers are not saved",
  "Regel hinzufügen": "Add rule",
  Sichtbarkeit: "Visibility",
  "Regel {number} entfernen": "Remove rule {number}",
  "Vorherige Frage {number}": "Previous question {number}",
  "Frage {number} nach oben": "Move up question {number}",
  "JSON importieren / exportieren": "Import or export JSON",
  "Fragebogen-JSON": "Questionnaire JSON",
  "JSON übernehmen": "Import JSON",
  "Das JSON ist ungültig. Prüfen Sie Klammern, Kommas und Anführungszeichen.":
    "Invalid JSON: check punctuation",
};
function App() {
  const [draft, setDraft] = useState<Draft>();
  const [renders, rerender] = useState(0);
  useEffect(() => {
    void call("GET").then((result) => setDraft(result.value));
  }, []);
  // Deliberately fresh callback identity: translation must not reset pending history.
  const translate: EditorTranslator = (message, values) =>
    formatEditorMessage(catalogue[message] ?? `Host · ${message}`, values);
  return (
    <main>
      <h1>Independent questionnaire editor</h1>
      <button type="button" onClick={() => rerender(renders + 1)}>
        Refresh host {renders}
      </button>
      {draft && (
        <SurveyEditor
          draft={draft}
          adapter={adapter}
          translate={translate}
          locale="en"
          canPublish={false}
        />
      )}
    </main>
  );
}
createRoot(document.getElementById("app")!).render(<App />);
