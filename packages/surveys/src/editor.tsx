import { formatEditorMessage, type EditorTranslator } from "./editor-i18n";
import {
  useEffect,
  useMemo,
  useState,
  useRef,
  useLayoutEffect,
  useId,
} from "react";
import type {
  AuthoringAdapter,
  Draft,
  Mutation,
  PublishedVersion,
} from "./contracts";
import {
  EditorHistory,
  type EditorQuestion,
  type QuestionKind,
  readEditorDefinition,
} from "./editor-model";
import { DraftCoordinator } from "./editor-saves";
import { ConditionBuilder } from "./conditions";
import { compatibilityIssues, questionIssues } from "./editor-compatibility";
import { createSurveyModel } from "./model";
import { Survey } from "survey-react-ui";
import type { Model } from "survey-core";
import "survey-core/i18n/german";
import "./styles.css";

const kinds: [QuestionKind, string][] = [
  ["text", "Kurzer Text"],
  ["comment", "Langer Text"],
  ["radiogroup", "Einfachauswahl"],
  ["dropdown", "Auswahlliste"],
  ["checkbox", "Mehrfachauswahl"],
  ["rating", "Bewertung"],
  ["matrix", "Matrix"],
];
function focusEditorTarget(target: HTMLElement | null | undefined) {
  if (!target) return;
  // Programmatic recovery targets need a visible indicator until focus moves away.
  target.setAttribute("data-editor-focus", "");
  target.focus();
  target.addEventListener(
    "blur",
    () => target.removeAttribute("data-editor-focus"),
    { once: true },
  );
}
export { formatEditorMessage, type EditorTranslator } from "./editor-i18n";

export interface SurveyEditorProps {
  translate?: EditorTranslator;
  locale?: string;
  draft: Draft;
  adapter: AuthoringAdapter;
  onPublished?: (version: PublishedVersion) => void;
  canPublish?: boolean;
  onSaveStateChange?: (state: string) => void;
}
export function SurveyEditor({
  draft,
  adapter,
  translate: t = formatEditorMessage,
  locale = "de",
  onPublished,
  canPublish = true,
  onSaveStateChange,
}: SurveyEditorProps) {
  const translator = useRef(t);
  translator.current = t;
  const [, render] = useState(0);
  const root = useRef<HTMLElement>(null);
  const pendingFocus = useRef<string | null>(null);
  const previewWasOpen = useRef(false);
  const jsonErrorId = useId();
  const [loadedDraft, setLoadedDraft] = useState(draft);
  const [jsonInput, setJsonInput] = useState("");
  const [jsonError, setJsonError] = useState("");
  useEffect(() => setLoadedDraft(draft), [draft]);
  const [pageId, selectPage] = useState<string | null>(null);
  const [questionId, selectQuestion] = useState<string | null>(null);
  const [kind, setKind] = useState<QuestionKind>("text");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Model | null>(null);
  const publication = useRef<Mutation | null>(null);
  const { history, saves } = useMemo(() => {
    const history = new EditorHistory(
      loadedDraft.definition,
      (message, values) => translator.current(message, values),
    );
    return {
      history,
      saves: new DraftCoordinator(loadedDraft, history, adapter, () =>
        render((n) => n + 1),
      ),
    };
  }, [loadedDraft, adapter]);
  useEffect(
    () => onSaveStateChange?.(saves.state),
    [saves.state, onSaveStateChange],
  );
  const doc = history.document;
  const issues = compatibilityIssues(doc);
  const page = doc.pages.find((p) => p.name === pageId) ?? doc.pages[0];
  const question = page?.elements.find((q) => q.name === questionId);
  useLayoutEffect(() => {
    if (pendingFocus.current) {
      const target = root.current?.querySelector<HTMLElement>(
        pendingFocus.current,
      );
      pendingFocus.current = null;
      focusEditorTarget(target);
    }
  });
  useEffect(() => {
    if (error)
      focusEditorTarget(
        root.current?.querySelector<HTMLElement>("[data-editor-error]"),
      );
  }, [error]);
  useEffect(() => {
    if (jsonError)
      focusEditorTarget(
        root.current?.querySelector<HTMLElement>("[data-json-error]"),
      );
  }, [jsonError]);
  useEffect(() => {
    if (preview) {
      previewWasOpen.current = true;
      focusEditorTarget(
        root.current?.querySelector<HTMLElement>("[data-preview-heading]"),
      );
    } else if (previewWasOpen.current) {
      previewWasOpen.current = false;
      focusEditorTarget(
        root.current?.querySelector<HTMLElement>("[data-preview-trigger]"),
      );
    }
    return () => preview?.dispose();
  }, [preview]);
  function movePage(name: string, position: number) {
    pendingFocus.current = `[data-page-id="${CSS.escape(name)}"]`;
    edit(() => history.movePage(name, position));
  }
  function moveQuestion(name: string, pageName: string, position: number) {
    pendingFocus.current = `[data-question-id="${CSS.escape(name)}"]`;
    edit(() => history.moveQuestion(name, pageName, position));
  }
  function edit(change: () => void) {
    if (busy || publication.current) return;
    try {
      change();
      setError("");
      saves.changed();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Änderung nicht möglich.",
      );
    }
  }
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (saves.state !== "saved") {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    const online = () => void saves.flush();
    window.addEventListener("beforeunload", warn);
    window.addEventListener("online", online);
    return () => {
      saves.cancelTimer();
      window.removeEventListener("beforeunload", warn);
      window.removeEventListener("online", online);
    };
  }, [saves]);
  function exportJson() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(history.document, null, 2)], {
        type: "application/json",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "survey-draft.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function importJson() {
    try {
      if (new TextEncoder().encode(jsonInput).length > 262144)
        throw new Error("Die JSON-Datei darf höchstens 256 KiB groß sein.");
      const definition = readEditorDefinition(JSON.parse(jsonInput));
      edit(() => history.replace(definition));
      selectPage(null);
      selectQuestion(null);
      setJsonError("");
    } catch (error) {
      setJsonError(
        error instanceof SyntaxError
          ? "Das JSON ist ungültig. Prüfen Sie Klammern, Kommas und Anführungszeichen."
          : error instanceof Error
            ? error.message
            : "Import nicht möglich.",
      );
    }
  }
  async function reloadDraft() {
    setBusy(true);
    setError("");
    try {
      const result = await adapter.loadDraft(draft.surveyId);
      if (!result.ok) {
        setError(result.error.message);
        return;
      }
      readEditorDefinition(result.value.definition);
      saves.cancelTimer();
      setLoadedDraft(result.value);
      selectPage(null);
      selectQuestion(null);
      setNotice(t("Der aktuelle Serverstand wurde geladen."));
    } catch {
      setError(
        "Der Serverstand konnte nicht geladen werden. Ihre lokalen Änderungen bleiben erhalten.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function inspect() {
    if (publication.current) return;
    setBusy(true);
    setError("");
    try {
      if (!(await saves.flush())) return;
      const result = await adapter.validateDraft(
        draft.surveyId,
        saves.revision,
      );
      if (!result.ok) {
        setError(result.error.message);
        return;
      }
      const model = createSurveyModel(result.value.definition);
      model.locale = locale;
      model.focusFirstQuestionAutomatic = false;
      model.onGetTitleTagName.add((_, options) => {
        options.tagName =
          options.element === model
            ? "h2"
            : options.element.getType() === "page"
              ? "h3"
              : "h4";
      });
      setPreview(model);
    } catch {
      setError(
        "Die Vorschau konnte nicht geprüft werden. Bitte erneut versuchen.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    setBusy(true);
    setError("");
    try {
      if (!publication.current) {
        if (!(await saves.flush())) return;
        publication.current = {
          operationId: crypto.randomUUID(),
          expectedRevision: saves.revision,
        };
      }
      const result = await adapter.publish(draft.surveyId, publication.current);
      if (!result.ok) {
        if (result.error.code !== "temporarily_unavailable")
          publication.current = null;
        setError(result.error.message);
        return;
      }
      saves.revision = publication.current.expectedRevision + 1;
      publication.current = null;
      setNotice(
        t("Version {number} ist veröffentlicht.", {
          number: result.value.number,
        }),
      );
      onPublished?.(result.value);
    } catch {
      setError(
        "Veröffentlichung noch nicht bestätigt. Bitte erneut prüfen; der gleiche Auftrag wird wiederholt.",
      );
    } finally {
      setBusy(false);
    }
  }
  const precedingPages = doc.pages
    .slice(0, doc.pages.indexOf(page))
    .flatMap((p) => p.elements);
  const precedingQuestions = question
    ? [
        ...precedingPages,
        ...page.elements.slice(0, page.elements.indexOf(question)),
      ]
    : [];
  function update(properties: Parameters<EditorHistory["updateQuestion"]>[1]) {
    if (question) edit(() => history.updateQuestion(question.name, properties));
  }
  function choices(
    field: "choices" | "rows" | "columns",
    item: EditorQuestion,
  ) {
    const values = Array.isArray(item[field]) ? item[field] : [];
    return (
      <fieldset>
        <legend>
          {field === "rows"
            ? t("Zeilen")
            : field === "columns"
              ? t("Spalten")
              : t("Antwortmöglichkeiten")}
        </legend>
        {values.map((value, index) => {
          const option =
            value && typeof value === "object" && !Array.isArray(value)
              ? value
              : { value, text: String(value) };
          return (
            <div key={String(option.value)}>
              <label>
                {t("Eintrag {number}", { number: index + 1 })}
                <input
                  value={String(option.text ?? option.value)}
                  onChange={(event) => {
                    const next = structuredClone(values);
                    next[index] = { ...option, text: event.target.value };
                    update({ [field]: next });
                  }}
                />
              </label>
              <button
                type="button"
                onClick={() =>
                  update({ [field]: values.filter((_, i) => i !== index) })
                }
              >
                {t("Eintrag {number} entfernen", { number: index + 1 })}
              </button>
              <button
                type="button"
                disabled={index === 0}
                onClick={() => {
                  const next = structuredClone(values);
                  next.splice(index - 1, 0, next.splice(index, 1)[0]);
                  update({ [field]: next });
                }}
              >
                {t("Eintrag {number} nach oben", { number: index + 1 })}
              </button>
              <button
                type="button"
                disabled={index === values.length - 1}
                onClick={() => {
                  const next = structuredClone(values);
                  next.splice(index + 1, 0, next.splice(index, 1)[0]);
                  update({ [field]: next });
                }}
              >
                {t("Eintrag {number} nach unten", { number: index + 1 })}
              </button>
            </div>
          );
        })}
        <button
          type="button"
          onClick={() =>
            update({
              [field]: [
                ...values,
                {
                  value:
                    field === "columns" &&
                    values.every(
                      (v) =>
                        typeof (v && typeof v === "object" && !Array.isArray(v)
                          ? v.value
                          : v) === "number",
                    )
                      ? Math.max(
                          0,
                          ...values.map((v) =>
                            Number(
                              v && typeof v === "object" && !Array.isArray(v)
                                ? v.value
                                : v,
                            ),
                          ),
                        ) + 1
                      : `option_${crypto.randomUUID().replaceAll("-", "")}`,
                  text: t("Neue Antwort"),
                },
              ],
            })
          }
        >
          {t("Eintrag hinzufügen")}
        </button>
      </fieldset>
    );
  }
  if (preview)
    return (
      <section
        ref={root}
        className="survey-editor survey-preview"
        aria-label={t("Fragebogen-Vorschau")}
      >
        <header className="se-toolbar">
          <h2 tabIndex={-1} data-preview-heading>
            {t("Vorschau · Antworten werden nicht gespeichert")}
          </h2>
          <button type="button" onClick={() => setPreview(null)}>
            {t("Zurück zum Editor")}
          </button>
        </header>
        <div className="survey-runner">
          <Survey model={preview} />
        </div>
      </section>
    );
  return (
    <section
      ref={root}
      className="survey-editor"
      aria-label={t("Fragebogen bearbeiten")}
    >
      <header className="se-toolbar">
        <div role="status" data-draft-state={saves.state}>
          {t(saves.message)}
        </div>
        <button
          type="button"
          disabled={!history.canUndo || busy || !!publication.current}
          onClick={() => edit(() => history.undo())}
        >
          {t("Rückgängig")}
        </button>
        <button
          type="button"
          disabled={!history.canRedo || busy || !!publication.current}
          onClick={() => edit(() => history.redo())}
        >
          {t("Wiederholen")}
        </button>
        <button type="button" onClick={() => void saves.flush()}>
          {t("Jetzt speichern")}
        </button>
        <button
          type="button"
          disabled={busy || !!publication.current}
          data-preview-trigger
          onClick={() => void inspect()}
        >
          {t("Vorschau")}
        </button>
        {canPublish && (
          <button type="button" disabled={busy} onClick={() => void publish()}>
            {publication.current
              ? t("Veröffentlichung erneut prüfen")
              : t("Veröffentlichen")}
          </button>
        )}
      </header>
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" tabIndex={-1} data-editor-error>
          {t(error)}
        </p>
      )}
      {saves.state === "conflict" && (
        <div role="alert">
          <p>
            {t(
              "Ein anderes Fenster hat den Entwurf geändert. Exportieren Sie Ihre lokalen Änderungen, bevor Sie den Serverstand laden.",
            )}
          </p>
          <button type="button" onClick={exportJson}>
            {t("Lokale Änderungen als JSON exportieren")}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void reloadDraft()}
          >
            {t("Serverstand laden und lokale Änderungen verwerfen")}
          </button>
        </div>
      )}
      <fieldset className="se-editing" disabled={busy || !!publication.current}>
        <details>
          <summary>{t("JSON importieren / exportieren")}</summary>
          <p>
            {t(
              "Für fortgeschrittene Nutzer: Ein Import ersetzt den lokalen Fragebogen und wird als Entwurf gespeichert. Rückgängig stellt den vorherigen Stand wieder her. Der Export enthält den aktuellen lokalen Stand, auch noch nicht gespeicherte Änderungen.",
            )}
          </p>
          <button type="button" onClick={exportJson}>
            {t("Fragebogen als JSON exportieren")}
          </button>
          <label>
            {t("JSON-Datei öffnen")}
            <input
              type="file"
              accept=".json,application/json"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                if (file.size > 262144) {
                  setJsonError(
                    "Die JSON-Datei darf höchstens 256 KiB groß sein.",
                  );
                  return;
                }
                try {
                  setJsonInput(await file.text());
                  setJsonError("");
                } catch {
                  setJsonError("Die Datei konnte nicht gelesen werden.");
                }
              }}
            />
          </label>
          <label>
            {t("Fragebogen-JSON")}
            <textarea
              rows={10}
              aria-invalid={!!jsonError}
              aria-describedby={jsonError ? jsonErrorId : undefined}
              value={jsonInput}
              onChange={(event) => setJsonInput(event.target.value)}
              spellCheck={false}
            />
          </label>
          {jsonError && (
            <p role="alert" id={jsonErrorId} tabIndex={-1} data-json-error>
              {t(jsonError)}
            </p>
          )}
          <button type="button" onClick={importJson}>
            {t("JSON übernehmen")}
          </button>
        </details>
        {issues.length > 0 && (
          <section aria-label={t("Kompatibilitätshinweise")}>
            <h2>{t("Nicht unterstützte Eigenschaften")}</h2>
            <p>
              {t(
                "Diese Bereiche bleiben unverändert erhalten und werden nicht ausgeführt. Betroffene Fragen sind schreibgeschützt. Vorschau und Veröffentlichung werden zusätzlich vom Server geprüft.",
              )}
            </p>
            <ul>
              {issues.map((path) => (
                <li key={path}>
                  <code>{path}</code>
                </li>
              ))}
            </ul>
          </section>
        )}
        <label className="se-title">
          {t("Titel des Fragebogens")}
          <input
            value={String(doc.title ?? "")}
            onChange={(event) =>
              edit(() =>
                history.change((next) => {
                  next.title = event.target.value;
                }),
              )
            }
          />
        </label>
        <label>
          {t("Beschreibung")}
          <textarea
            value={String(doc.description ?? "")}
            onChange={(event) =>
              edit(() =>
                history.change((next) => {
                  next.description = event.target.value;
                }),
              )
            }
          />
        </label>
        <label>
          {t("Fortschritt anzeigen")}
          <select
            value={String(doc.showProgressBar ?? "off")}
            onChange={(event) =>
              edit(() =>
                history.change((next) => {
                  next.showProgressBar = event.target.value;
                }),
              )
            }
          >
            <option value="off">{t("Aus")}</option>
            <option value="top">{t("Oben")}</option>
            <option value="bottom">{t("Unten")}</option>
            <option value="both">{t("Oben und unten")}</option>
          </select>
        </label>
        <label>
          {t("Text nach dem Abschluss")}
          <textarea
            value={String(doc.completedHtml ?? "")}
            onChange={(event) =>
              edit(() =>
                history.change((next) => {
                  next.completedHtml = event.target.value;
                }),
              )
            }
          />
        </label>
        <div className="se-workspace">
          <nav aria-label={t("Fragebogenseiten")}>
            <h2>{t("Seiten")}</h2>
            <ol>
              {doc.pages.map((p, index) => (
                <li
                  key={p.name}
                  draggable
                  onDragStart={(event) =>
                    event.dataTransfer.setData(
                      "application/x-survey-page",
                      p.name,
                    )
                  }
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    const name = event.dataTransfer.getData(
                      "application/x-survey-page",
                    );
                    if (name) edit(() => history.movePage(name, index));
                  }}
                >
                  <button
                    type="button"
                    data-page-id={p.name}
                    aria-current={page?.name === p.name ? "step" : undefined}
                    onClick={() => {
                      selectPage(p.name);
                      selectQuestion(null);
                    }}
                  >
                    {index + 1}. {String(p.title ?? t("Seite"))}
                  </button>
                  <div className="se-move">
                    <button
                      type="button"
                      disabled={index === 0}
                      aria-label={t("Seite {number} nach oben", {
                        number: index + 1,
                      })}
                      onClick={() => movePage(p.name, index - 1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      disabled={index === doc.pages.length - 1}
                      aria-label={t("Seite {number} nach unten", {
                        number: index + 1,
                      })}
                      onClick={() => movePage(p.name, index + 1)}
                    >
                      ↓
                    </button>
                  </div>
                </li>
              ))}
            </ol>
            <button
              type="button"
              onClick={() =>
                edit(() => {
                  selectPage(history.addPage());
                  selectQuestion(null);
                })
              }
            >
              {t("Seite hinzufügen")}
            </button>
          </nav>
          <div className="se-canvas">
            {page ? (
              <>
                <label>
                  {t("Seitentitel")}
                  <input
                    value={String(page.title ?? "")}
                    onChange={(event) =>
                      edit(() =>
                        history.change((next) => {
                          next.pages.find((p) => p.name === page.name)!.title =
                            event.target.value;
                        }),
                      )
                    }
                  />
                </label>
                <ConditionBuilder
                  translate={t}
                  expression={String(page.visibleIf ?? "")}
                  questions={precedingPages}
                  onChange={(value) =>
                    edit(() =>
                      history.change((next) => {
                        const current = next.pages.find(
                          (p) => p.name === page.name,
                        )!;
                        if (value === undefined) delete current.visibleIf;
                        else current.visibleIf = value;
                      }),
                    )
                  }
                />
                <div className="se-actions">
                  <button
                    type="button"
                    onClick={() =>
                      edit(() => selectPage(history.duplicatePage(page.name)))
                    }
                  >
                    {t("Seite duplizieren")}
                  </button>
                  <button
                    type="button"
                    onClick={() => edit(() => history.removePage(page.name))}
                  >
                    {t("Seite entfernen")}
                  </button>
                </div>
                <ol aria-label={t("Fragen auf dieser Seite")}>
                  {page.elements.map((q, index) => (
                    <li
                      key={q.name}
                      draggable
                      onDragStart={(event) =>
                        event.dataTransfer.setData(
                          "application/x-survey-question",
                          q.name,
                        )
                      }
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => {
                        event.preventDefault();
                        const name = event.dataTransfer.getData(
                          "application/x-survey-question",
                        );
                        if (name)
                          edit(() =>
                            history.moveQuestion(name, page.name, index),
                          );
                      }}
                    >
                      <button
                        type="button"
                        data-question-id={q.name}
                        aria-pressed={question?.name === q.name}
                        onClick={() => selectQuestion(q.name)}
                      >
                        <small>
                          {t(
                            kinds.find(([type]) => type === q.type)?.[1] ??
                              "Nicht unterstützte Frage",
                          )}
                        </small>
                        <strong>
                          {String(q.title ?? t("Frage ohne Titel"))}
                        </strong>
                      </button>
                      <div className="se-move">
                        <button
                          type="button"
                          disabled={index === 0}
                          aria-label={t("Frage {number} nach oben", {
                            number: index + 1,
                          })}
                          onClick={() =>
                            moveQuestion(q.name, page.name, index - 1)
                          }
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          disabled={index === page.elements.length - 1}
                          aria-label={t("Frage {number} nach unten", {
                            number: index + 1,
                          })}
                          onClick={() =>
                            moveQuestion(q.name, page.name, index + 1)
                          }
                        >
                          ↓
                        </button>
                      </div>
                    </li>
                  ))}
                </ol>
                <div className="se-add">
                  <label>
                    {t("Fragetyp")}
                    <select
                      value={kind}
                      onChange={(event) =>
                        setKind(event.target.value as QuestionKind)
                      }
                    >
                      {kinds.map(([value, label]) => (
                        <option key={value} value={value}>
                          {t(label)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      edit(() =>
                        selectQuestion(history.addQuestion(page.name, kind)),
                      )
                    }
                  >
                    {t("Frage hinzufügen")}
                  </button>
                </div>
              </>
            ) : (
              <p>{t("Fügen Sie eine erste Seite hinzu.")}</p>
            )}
          </div>
          <aside aria-label={t("Frageeigenschaften")}>
            <h2>{t("Eigenschaften")}</h2>
            {question && questionIssues(question).length === 0 ? (
              <>
                <label>
                  {t("Fragetitel")}
                  <input
                    value={String(question.title ?? "")}
                    onChange={(event) => update({ title: event.target.value })}
                  />
                </label>
                <label>
                  {t("Hinweis")}
                  <textarea
                    value={String(question.description ?? "")}
                    onChange={(event) =>
                      update({ description: event.target.value })
                    }
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={question.isRequired === true}
                    onChange={(event) =>
                      update({ isRequired: event.target.checked })
                    }
                  />
                  {t("Antwort erforderlich")}
                </label>
                {question.type === "text" && (
                  <label>
                    {t("Eingabe")}
                    <select
                      value={String(question.inputType ?? "text")}
                      onChange={(event) =>
                        update({
                          inputType: event.target.value,
                          min: undefined,
                          max: undefined,
                          minLength: undefined,
                          maxLength: undefined,
                        })
                      }
                    >
                      <option value="text">{t("Text")}</option>
                      <option value="number">{t("Zahl")}</option>
                      <option value="date">{t("Datum")}</option>
                    </select>
                  </label>
                )}
                {((question.type === "text" &&
                  (!question.inputType || question.inputType === "text")) ||
                  question.type === "comment") && (
                  <>
                    {["minLength", "maxLength"].map((property) => (
                      <label key={property}>
                        {property === "minLength"
                          ? t("Mindestlänge")
                          : t("Höchstlänge")}
                        <input
                          type="number"
                          min="0"
                          value={String(question[property] ?? "")}
                          onChange={(event) =>
                            update({
                              [property]:
                                event.target.value === ""
                                  ? undefined
                                  : Number(event.target.value),
                            })
                          }
                        />
                      </label>
                    ))}
                  </>
                )}
                {["radiogroup", "dropdown", "checkbox"].includes(
                  question.type,
                ) && choices("choices", question)}
                {question.type === "matrix" && (
                  <>
                    {choices("rows", question)}
                    {choices("columns", question)}
                    <label>
                      <input
                        type="checkbox"
                        checked={question.isAllRowRequired === true}
                        onChange={(event) =>
                          update({ isAllRowRequired: event.target.checked })
                        }
                      />
                      {t("Alle Zeilen erforderlich")}
                    </label>
                  </>
                )}
                {((question.type === "text" &&
                  ["number", "date"].includes(String(question.inputType))) ||
                  question.type === "rating" ||
                  question.type === "checkbox") && (
                  <fieldset>
                    <legend>{t("Grenzen")}</legend>
                    {(question.type === "rating"
                      ? [
                          ["rateMin", "Skalenanfang"],
                          ["rateMax", "Skalenende"],
                          ["rateStep", "Schrittweite"],
                        ]
                      : question.type === "checkbox"
                        ? [
                            ["minSelectedChoices", "Mindestens auswählen"],
                            ["maxSelectedChoices", "Höchstens auswählen"],
                          ]
                        : [
                            ["min", "Minimum"],
                            ["max", "Maximum"],
                          ]
                    ).map(([property, label]) => (
                      <label key={property}>
                        {t(label)}
                        <input
                          type={
                            question.inputType === "date" ? "date" : "number"
                          }
                          step="any"
                          value={String(question[property] ?? "")}
                          onChange={(event) =>
                            update({
                              [property]:
                                event.target.value === ""
                                  ? undefined
                                  : question.inputType === "date"
                                    ? event.target.value
                                    : Number(event.target.value),
                            })
                          }
                        />
                      </label>
                    ))}
                  </fieldset>
                )}
                <ConditionBuilder
                  translate={t}
                  expression={String(question.visibleIf ?? "")}
                  questions={precedingQuestions}
                  onChange={(visibleIf) => update({ visibleIf })}
                />
                <label>
                  {t("Auf Seite verschieben")}
                  <select
                    value={page.name}
                    onChange={(event) =>
                      edit(() => {
                        history.moveQuestion(
                          question.name,
                          event.target.value,
                          0,
                        );
                        selectPage(event.target.value);
                      })
                    }
                  >
                    {doc.pages.map((p, index) => (
                      <option key={p.name} value={p.name}>
                        {index + 1}. {String(p.title ?? t("Seite"))}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() =>
                    edit(() =>
                      selectQuestion(history.duplicateQuestion(question.name)),
                    )
                  }
                >
                  {t("Frage duplizieren")}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    edit(() => history.removeQuestion(question.name))
                  }
                >
                  {t("Frage entfernen")}
                </button>
              </>
            ) : (
              <p>
                {question
                  ? t(
                      "Diese Frage enthält nicht unterstützte Eigenschaften und bleibt unverändert erhalten. Korrigieren Sie die angezeigten Felder über den JSON-Import.",
                    )
                  : t(
                      "Wählen Sie eine Frage, um Titel und Antworten zu bearbeiten.",
                    )}
              </p>
            )}
          </aside>
        </div>
      </fieldset>
    </section>
  );
}

/** Local simulation for a host's publication review; never persists responses. */
export function SurveyPublicationPreview({
  definition,
  locale = "de",
}: {
  definition: Record<string, unknown>;
  locale?: "de" | "en";
}) {
  const model = useMemo(
    () => createSurveyModel(definition, locale),
    [definition, locale],
  );
  useEffect(() => () => model.dispose(), [model]);
  return (
    <div className="survey-editor survey-preview">
      <Survey model={model} />
    </div>
  );
}
