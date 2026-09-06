import { useEffect, useMemo, useState, useRef } from "react";
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
} from "./editor-model";
import { DraftCoordinator } from "./editor-saves";
import { ConditionBuilder } from "./conditions";
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
export interface SurveyEditorProps {
  draft: Draft;
  adapter: AuthoringAdapter;
  onPublished?: (version: PublishedVersion) => void;
}
export function SurveyEditor({
  draft,
  adapter,
  onPublished,
}: SurveyEditorProps) {
  const [, render] = useState(0);
  const [pageId, selectPage] = useState<string | null>(null);
  const [questionId, selectQuestion] = useState<string | null>(null);
  const [kind, setKind] = useState<QuestionKind>("text");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Model | null>(null);
  const publication = useRef<Mutation | null>(null);
  const { history, saves } = useMemo(() => {
    const history = new EditorHistory(draft.definition);
    return {
      history,
      saves: new DraftCoordinator(draft, history, adapter, () =>
        render((n) => n + 1),
      ),
    };
  }, [draft, adapter]);
  const doc = history.document;
  const page = doc.pages.find((p) => p.name === pageId) ?? doc.pages[0];
  const question = page?.elements.find((q) => q.name === questionId);
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
      model.locale = "de";
      model.clearInvisibleValues = "onHidden";
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
      setNotice(`Version ${result.value.number} ist veröffentlicht.`);
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
            ? "Zeilen"
            : field === "columns"
              ? "Spalten"
              : "Antwortmöglichkeiten"}
        </legend>
        {values.map((value, index) => {
          const option =
            value && typeof value === "object" && !Array.isArray(value)
              ? value
              : { value, text: String(value) };
          return (
            <div key={String(option.value)}>
              <label>
                Eintrag {index + 1}
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
                Eintrag {index + 1} entfernen
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
                Eintrag {index + 1} nach oben
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
                Eintrag {index + 1} nach unten
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
                  text: "Neue Antwort",
                },
              ],
            })
          }
        >
          Eintrag hinzufügen
        </button>
      </fieldset>
    );
  }
  if (preview)
    return (
      <section className="survey-editor" aria-label="Fragebogen-Vorschau">
        <header className="se-toolbar">
          <h2>Vorschau · Antworten werden nicht gespeichert</h2>
          <button type="button" onClick={() => setPreview(null)}>
            Zurück zum Editor
          </button>
        </header>
        <div className="survey-runner">
          <Survey model={preview} />
        </div>
      </section>
    );
  return (
    <section className="survey-editor" aria-label="Fragebogen bearbeiten">
      <header className="se-toolbar">
        <div role="status" data-draft-state={saves.state}>
          {saves.message}
        </div>
        <button
          type="button"
          disabled={!history.canUndo || busy || !!publication.current}
          onClick={() => edit(() => history.undo())}
        >
          Rückgängig
        </button>
        <button
          type="button"
          disabled={!history.canRedo || busy || !!publication.current}
          onClick={() => edit(() => history.redo())}
        >
          Wiederholen
        </button>
        <button type="button" onClick={() => void saves.flush()}>
          Jetzt speichern
        </button>
        <button
          type="button"
          disabled={busy || !!publication.current}
          onClick={() => void inspect()}
        >
          Vorschau
        </button>
        <button type="button" disabled={busy} onClick={() => void publish()}>
          {publication.current
            ? "Veröffentlichung erneut prüfen"
            : "Veröffentlichen"}
        </button>
      </header>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
      {saves.state === "conflict" && (
        <p role="alert">
          Ein anderes Fenster hat den Entwurf geändert. Laden Sie den aktuellen
          Stand neu, bevor Sie weiter speichern.
        </p>
      )}
      <fieldset className="se-editing" disabled={busy || !!publication.current}>
        <label className="se-title">
          Titel des Fragebogens
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
          Beschreibung
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
          Fortschritt anzeigen
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
            <option value="off">Aus</option>
            <option value="top">Oben</option>
            <option value="bottom">Unten</option>
            <option value="both">Oben und unten</option>
          </select>
        </label>
        <label>
          Text nach dem Abschluss
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
          <nav aria-label="Fragebogenseiten">
            <h2>Seiten</h2>
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
                    aria-current={page?.name === p.name ? "step" : undefined}
                    onClick={() => {
                      selectPage(p.name);
                      selectQuestion(null);
                    }}
                  >
                    {index + 1}. {String(p.title ?? "Seite")}
                  </button>
                  <div className="se-move">
                    <button
                      type="button"
                      disabled={index === 0}
                      aria-label={`Seite ${index + 1} nach oben`}
                      onClick={() =>
                        edit(() => history.movePage(p.name, index - 1))
                      }
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      disabled={index === doc.pages.length - 1}
                      aria-label={`Seite ${index + 1} nach unten`}
                      onClick={() =>
                        edit(() => history.movePage(p.name, index + 1))
                      }
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
              Seite hinzufügen
            </button>
          </nav>
          <div className="se-canvas">
            {page ? (
              <>
                <label>
                  Seitentitel
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
                    Seite duplizieren
                  </button>
                  <button
                    type="button"
                    onClick={() => edit(() => history.removePage(page.name))}
                  >
                    Seite entfernen
                  </button>
                </div>
                <ol aria-label="Fragen auf dieser Seite">
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
                        aria-pressed={question?.name === q.name}
                        onClick={() => selectQuestion(q.name)}
                      >
                        <small>
                          {kinds.find(([type]) => type === q.type)?.[1] ??
                            "Nicht unterstützte Frage"}
                        </small>
                        <strong>{String(q.title ?? "Frage ohne Titel")}</strong>
                      </button>
                      <div className="se-move">
                        <button
                          type="button"
                          disabled={index === 0}
                          aria-label={`Frage ${index + 1} nach oben`}
                          onClick={() =>
                            edit(() =>
                              history.moveQuestion(
                                q.name,
                                page.name,
                                index - 1,
                              ),
                            )
                          }
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          disabled={index === page.elements.length - 1}
                          aria-label={`Frage ${index + 1} nach unten`}
                          onClick={() =>
                            edit(() =>
                              history.moveQuestion(
                                q.name,
                                page.name,
                                index + 1,
                              ),
                            )
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
                    Fragetyp
                    <select
                      value={kind}
                      onChange={(event) =>
                        setKind(event.target.value as QuestionKind)
                      }
                    >
                      {kinds.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
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
                    Frage hinzufügen
                  </button>
                </div>
              </>
            ) : (
              <p>Fügen Sie eine erste Seite hinzu.</p>
            )}
          </div>
          <aside aria-label="Frageeigenschaften">
            <h2>Eigenschaften</h2>
            {question && kinds.some(([type]) => type === question.type) ? (
              <>
                <label>
                  Fragetitel
                  <input
                    value={String(question.title ?? "")}
                    onChange={(event) => update({ title: event.target.value })}
                  />
                </label>
                <label>
                  Hinweis
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
                  Antwort erforderlich
                </label>
                {question.type === "text" && (
                  <label>
                    Eingabe
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
                      <option value="text">Text</option>
                      <option value="number">Zahl</option>
                      <option value="date">Datum</option>
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
                          ? "Mindestlänge"
                          : "Höchstlänge"}
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
                      Alle Zeilen erforderlich
                    </label>
                  </>
                )}
                {((question.type === "text" &&
                  ["number", "date"].includes(String(question.inputType))) ||
                  question.type === "rating" ||
                  question.type === "checkbox") && (
                  <fieldset>
                    <legend>Grenzen</legend>
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
                        {label}
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
                  expression={String(question.visibleIf ?? "")}
                  questions={precedingQuestions}
                  onChange={(visibleIf) => update({ visibleIf })}
                />
                <label>
                  Auf Seite verschieben
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
                        {index + 1}. {String(p.title ?? "Seite")}
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
                  Frage duplizieren
                </button>
                <button
                  type="button"
                  onClick={() =>
                    edit(() => history.removeQuestion(question.name))
                  }
                >
                  Frage entfernen
                </button>
              </>
            ) : (
              <p>
                {question
                  ? "Dieser Fragetyp bleibt unverändert erhalten."
                  : "Wählen Sie eine Frage, um Titel und Antworten zu bearbeiten."}
              </p>
            )}
          </aside>
        </div>
      </fieldset>
    </section>
  );
}
