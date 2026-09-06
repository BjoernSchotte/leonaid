import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type LeonAidApiClient,
  type CurrentIdentityResponse,
  type SurveySummaryResponse,
  type SurveyListResponse,
  type TimeoutSettingsResponse,
} from "@leonaid/api-client";
import { Button } from "@leonaid/ui";
import { SurveyEditor } from "@leonaid/surveys/editor";
import type {
  AuthoringAdapter,
  Draft,
  Result,
  ErrorCode,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/editor-styles";
import "./surveys.css";

const labels = {
  draft: "Entwurf",
  active: "Aktiv",
  ended: "Beendet",
  archived: "Archiviert",
  deleted: "Papierkorb",
};
type Status = keyof typeof labels;
async function mapped<T>(request: Promise<unknown>): Promise<Result<T>> {
  try {
    return { ok: true, value: (await request) as T };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const codes = [
      "revision_conflict",
      "closed",
      "not_found",
      "invalid_definition",
      "unsupported_capability",
      "limit_exceeded",
      "forbidden",
      "unauthenticated",
      "idempotency_conflict",
    ];
    return {
      ok: false,
      error: {
        code: (codes.includes(error.detail.code)
          ? error.detail.code
          : "temporarily_unavailable") as ErrorCode,
        message: error.detail.message,
        diagnostics: [],
      },
    };
  }
}
const errorMessage = (error: unknown) =>
  error instanceof ApiError
    ? error.detail.message
    : "Die Änderung konnte nicht bestätigt werden. Bitte laden Sie den aktuellen Stand neu.";

export function SurveysPage({
  client,
  surveyId,
  createNew = false,
  identity,
}: {
  client: LeonAidApiClient;
  surveyId?: string;
  createNew?: boolean;
  identity: CurrentIdentityResponse;
}) {
  const [id, setId] = useState(surveyId);
  const [summary, setSummary] = useState<SurveySummaryResponse | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [list, setList] = useState<SurveyListResponse | null>(null);
  const [title, setTitle] = useState("");
  const [actionId, setActionId] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Status | "">("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [timeout, setTimeoutValue] = useState("");
  const [scheduledEnd, setScheduledEnd] = useState("");
  const [defaults, setDefaults] = useState<TimeoutSettingsResponse | null>(
    null,
  );
  const [defaultValue, setDefaultValue] = useState("");
  const [confirmTrash, setConfirmTrash] = useState(false);
  const [saveState, setSaveState] = useState("saved");
  const adapter = useMemo<AuthoringAdapter>(
    () => ({
      validateDraft: (key, expectedRevision, options) =>
        mapped(client.validateSurveyDraft(key, { expectedRevision }, options)),
      loadDraft: (key, options) => mapped(client.getSurveyDraft(key, options)),
      saveDraft: (key, body, options) =>
        mapped(client.saveSurveyDraft(key, body, options)),
      publish: (key, body, options) =>
        mapped(client.publishSurvey(key, body, options)),
    }),
    [client],
  );
  const refresh = useCallback(
    async (key: string) => {
      const value = await client.getSurvey(key);
      setSummary(value);
      const end = value.endsAt ? new Date(value.endsAt) : null;
      setScheduledEnd(
        end
          ? new Date(end.getTime() - end.getTimezoneOffset() * 60000)
              .toISOString()
              .slice(0, 16)
          : "",
      );
      setTimeoutValue(value.inactivityTimeoutSeconds?.toString() ?? "");
      if (
        ["draft", "active"].includes(value.status) &&
        value.capabilities?.includes("design")
      )
        setDraft((await client.getSurveyDraft(key)) as Draft);
      else setDraft(null);
    },
    [client],
  );
  useEffect(() => {
    let stopped = false;
    setLoading(true);
    setMessage("");
    const request = id
      ? refresh(id)
      : client
          .listSurveys({ status: filter || undefined, search, offset })
          .then((value) => {
            if (!stopped) setList(value);
          });
    void request
      .catch((error) => {
        if (!stopped) setMessage(errorMessage(error));
      })
      .finally(() => {
        if (!stopped) setLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [client, id, filter, search, offset, refresh]);
  useEffect(() => {
    if (!identity.globalRoles.includes("system_admin") || id || createNew)
      return;
    let stopped = false;
    void client
      .getSurveySettings()
      .then((value) => {
        if (!stopped) {
          setDefaults(value);
          setDefaultValue(String(value.inactivityTimeoutSeconds));
        }
      })
      .catch((error) => {
        if (!stopped) setMessage(errorMessage(error));
      });
    return () => {
      stopped = true;
    };
  }, [client, identity, id, createNew]);
  const creation = useMemo(
    () => ({ id: crypto.randomUUID(), operationId: crypto.randomUUID() }),
    [],
  );
  async function run(operation: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    setNotice("");
    try {
      await operation();
      setNotice(success);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    await run(async () => {
      await client.createSurvey(creation.id, {
        operationId: creation.operationId,
        title,
        actionId: actionId || null,
        definition: {
          title,
          pages: [
            {
              name: "page_first",
              title: "Ihre Rückmeldung",
              elements: [
                {
                  type: "text",
                  name: "question_first",
                  title: "Was möchten Sie uns mitteilen?",
                },
              ],
            },
          ],
        },
      });
      history.replaceState(null, "", `/admin/surveys/${creation.id}`);
      setId(creation.id);
    }, "");
  }
  async function mutate(
    action: "end" | "archive" | "unarchive" | "trash" | "restore",
  ) {
    if (!summary) return;
    await run(async () => {
      await client.transitionSurvey(summary.id, {
        action,
        operationId: crypto.randomUUID(),
        expectedRevision: summary.revision,
      });
      await refresh(summary.id);
      setConfirmTrash(false);
    }, "Status wurde gespeichert.");
  }
  const allowed = (capability: string) =>
    summary?.capabilities?.includes(capability) ?? false;
  const pending = busy || (draft !== null && saveState !== "saved");
  return (
    <section className="surveys-module" aria-label="Umfragen">
      <header className="surveys-heading">
        <div>
          {(id || createNew) && <a href="/admin/surveys">← Alle Umfragen</a>}
          <h1>
            {summary?.title ??
              (id ? "Umfrage laden" : createNew ? "Neue Umfrage" : "Umfragen")}
          </h1>
          <p>
            {id
              ? "Fragebogen, Teilnahme und Teilantworten verwalten."
              : createNew
                ? "Starten Sie mit einer Frage. Weitere Fragen und Seiten ergänzen Sie im nächsten Schritt."
                : "Rückmeldungen zu Ihren Aktionen sammeln und Fragebögen gemeinsam betreuen."}
          </p>
        </div>
        {!id && !createNew && (
          <a className="ui-button ui-button--primary" href="/admin/surveys/new">
            Neue Umfrage
          </a>
        )}
      </header>
      {message && (
        <div role="alert" className="surveys-error">
          <p>{message}</p>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Aktuellen Stand laden
          </Button>
        </div>
      )}
      {notice && <p role="status">{notice}</p>}
      {loading && <p role="status">Umfragen werden geladen …</p>}
      {!id && !createNew && list && (
        <>
          <form
            className="surveys-filters"
            onSubmit={(e) => e.preventDefault()}
          >
            <label>
              Umfrage suchen
              <input
                type="search"
                value={search}
                maxLength={240}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
              />
            </label>
            <label>
              Status
              <select
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value as Status | "");
                  setOffset(0);
                }}
              >
                <option value="">Alle</option>
                {Object.entries(labels).map(([key, label]) => (
                  <option value={key} key={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </form>
          <p className="surveys-count" aria-live="polite">
            {list.total} {list.total === 1 ? "Umfrage" : "Umfragen"}
          </p>
          {list.items.length ? (
            <ul className="surveys-list">
              {list.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <a href={`/admin/surveys/${item.id}`}>{item.title}</a>
                    <p>
                      {item.actionId
                        ? "Mit Charity-Aktion verknüpft"
                        : "Eigenständige Umfrage"}
                      {item.ownerUserId === identity.userId
                        ? " · Von Ihnen erstellt"
                        : ""}
                    </p>
                  </div>
                  <span
                    className="surveys-status"
                    data-survey-status={item.status}
                  >
                    {labels[item.status]}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="surveys-empty">
              Hier gibt es noch keine passenden Umfragen. Erstellen Sie einen
              Fragebogen oder ändern Sie den Filter.
            </p>
          )}
          {(offset > 0 || offset + 50 < list.total) && (
            <nav aria-label="Umfragenseiten" className="surveys-actions">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(offset - 50)}
              >
                Vorherige Seite
              </Button>
              <Button
                variant="secondary"
                disabled={offset + 50 >= list.total}
                onClick={() => setOffset(offset + 50)}
              >
                Nächste Seite
              </Button>
            </nav>
          )}
          {defaults && (
            <details className="surveys-settings">
              <summary>Standard für Teilantworten</summary>
              <p>
                Gilt für neue Teilnahmen ohne abweichende Umfrage-Einstellung.
                Bereits begonnene Teilnahmen behalten ihren Zeitraum.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () => {
                    const value = await client.updateSurveySettings({
                      operationId: crypto.randomUUID(),
                      expectedRevision: defaults.revision,
                      inactivityTimeoutSeconds: Number(defaultValue),
                    });
                    setDefaults(value);
                  }, "Standard wurde gespeichert.");
                }}
              >
                <label>
                  Standardzeitraum in Sekunden
                  <input
                    type="number"
                    min={1}
                    max={604800}
                    step={1}
                    required
                    value={defaultValue}
                    onChange={(e) => setDefaultValue(e.target.value)}
                  />
                </label>
                <Button type="submit" disabled={busy}>
                  Standard speichern
                </Button>
              </form>
            </details>
          )}
        </>
      )}
      {!id && createNew && (
        <form
          className="surveys-create"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <label>
            Titel der Umfrage
            <input
              required
              maxLength={240}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            Zuordnung
            <select
              value={actionId}
              onChange={(e) => setActionId(e.target.value)}
            >
              <option value="">Eigenständig – ich bin verantwortlich</option>
              {list?.actions.map((action) => (
                <option value={action.id} key={action.id}>
                  {action.name}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" disabled={busy || !title.trim()}>
            {busy ? "Wird erstellt …" : "Umfrage erstellen"}
          </Button>
        </form>
      )}
      {summary && (
        <>
          <section
            className="surveys-management"
            aria-label="Umfrage verwalten"
          >
            <div className="surveys-actions">
              <span
                className="surveys-status"
                data-survey-status={summary.status}
              >
                {labels[summary.status]}
              </span>
              {summary.status === "active" && (
                <a
                  href={`/surveys/${summary.id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Veröffentlichte Umfrage öffnen
                </a>
              )}
              {summary.status === "active" && allowed("publish") && (
                <Button
                  variant="secondary"
                  disabled={pending}
                  onClick={() => void mutate("end")}
                >
                  Teilnahme beenden
                </Button>
              )}
              {summary.status === "ended" && allowed("archive") && (
                <Button
                  variant="secondary"
                  disabled={pending}
                  onClick={() => void mutate("archive")}
                >
                  Archivieren
                </Button>
              )}
              {summary.status === "archived" && allowed("archive") && (
                <Button
                  variant="secondary"
                  disabled={pending}
                  onClick={() => void mutate("unarchive")}
                >
                  Aus Archiv holen
                </Button>
              )}
              {summary.status === "deleted" && allowed("delete") && (
                <Button
                  variant="secondary"
                  disabled={pending}
                  onClick={() => void mutate("restore")}
                >
                  Wiederherstellen
                </Button>
              )}
              {summary.status !== "deleted" && allowed("delete") && (
                <Button
                  variant="ghost"
                  disabled={pending}
                  onClick={() => setConfirmTrash(true)}
                >
                  In Papierkorb verschieben
                </Button>
              )}
            </div>
            {["ended", "archived", "deleted"].includes(summary.status) && (
              <p>
                Die Teilnahme ist geschlossen. Eine Wiederherstellung öffnet die
                Umfrage nicht erneut.
              </p>
            )}
            {confirmTrash && (
              <div className="surveys-confirm">
                <p>
                  Die Umfrage wird geschlossen und aus der normalen Bearbeitung
                  entfernt. Sie können sie später wiederherstellen.
                </p>
                <div className="surveys-actions">
                  <Button
                    variant="danger"
                    disabled={pending}
                    onClick={() => void mutate("trash")}
                  >
                    Jetzt in Papierkorb verschieben
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => setConfirmTrash(false)}
                  >
                    Abbrechen
                  </Button>
                </div>
              </div>
            )}
            {["draft", "active"].includes(summary.status) &&
              allowed("publish") && (
                <details className="surveys-settings">
                  <summary>Geplantes Ende</summary>
                  <p>
                    Die Teilnahme endet automatisch zu diesem Zeitpunkt. Bereits
                    gespeicherte Antworten bleiben erhalten.
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void run(async () => {
                        await client.scheduleSurveyEnd(summary.id, {
                          operationId: crypto.randomUUID(),
                          expectedRevision: summary.revision,
                          endsAt: scheduledEnd
                            ? new Date(scheduledEnd).toISOString()
                            : null,
                        });
                        await refresh(summary.id);
                      }, "Geplantes Ende wurde gespeichert.");
                    }}
                  >
                    <label>
                      Teilnahme endet am
                      <input
                        type="datetime-local"
                        value={scheduledEnd}
                        onChange={(e) => setScheduledEnd(e.target.value)}
                      />
                    </label>
                    <p>
                      Lokale Zeitzone:{" "}
                      {Intl.DateTimeFormat().resolvedOptions().timeZone}. Leer
                      lassen, um ohne geplantes Ende fortzufahren.
                    </p>
                    <Button type="submit" disabled={pending}>
                      Geplantes Ende speichern
                    </Button>
                  </form>
                </details>
              )}
            {summary.status !== "deleted" && allowed("design") && (
              <details className="surveys-settings">
                <summary>Teilantworten nach Inaktivität</summary>
                <p>
                  Antworten bleiben erhalten. Nach diesem Zeitraum gilt eine
                  neue Teilnahme als Teilantwort. Bereits begonnene Teilnahmen
                  behalten ihren Zeitraum.
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run(async () => {
                      await client.updateSurveyTimeout(summary.id, {
                        operationId: crypto.randomUUID(),
                        expectedRevision: summary.revision,
                        inactivityTimeoutSeconds:
                          timeout === "" ? null : Number(timeout),
                      });
                      await refresh(summary.id);
                    }, "Zeitraum wurde gespeichert.");
                  }}
                >
                  <label>
                    Abweichender Zeitraum in Sekunden
                    <input
                      type="number"
                      min={1}
                      max={604800}
                      step={1}
                      value={timeout}
                      placeholder="Standard verwenden"
                      onChange={(e) => setTimeoutValue(e.target.value)}
                    />
                  </label>
                  <p>
                    Leer lassen, um den Standard zu verwenden. Erlaubt: 1 bis
                    604800 Sekunden.
                  </p>
                  <Button type="submit" disabled={pending}>
                    Zeitraum speichern
                  </Button>
                </form>
              </details>
            )}
          </section>
          {draft && (
            <SurveyEditor
              draft={draft}
              adapter={adapter}
              canPublish={allowed("publish")}
              onSaveStateChange={setSaveState}
              onPublished={() => {
                void refresh(summary.id).catch((error) =>
                  setMessage(errorMessage(error)),
                );
              }}
            />
          )}
        </>
      )}
    </section>
  );
}
