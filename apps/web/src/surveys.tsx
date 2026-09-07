import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import {
  ApiError,
  type LeonAidApiClient,
  type CurrentIdentityResponse,
  type SurveySummaryResponse,
  type SurveyListResponse,
  type TimeoutSettingsResponse,
  type SurveyInvitationsResponse,
  type SurveyInvitationCreate,
  type SurveyDeletionResponse,
  type SurveyDraftResponse,
} from "@leonaid/api-client";
import { Button } from "@leonaid/ui";
import {
  SurveyEditor,
  SurveyPublicationPreview,
} from "@leonaid/surveys/editor";
import type {
  AuthoringAdapter,
  Draft,
  Result,
  ErrorCode,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/editor-styles";
import "./surveys.css";
import { SurveyAnalysis } from "./survey-analysis";
import { SurveyResponses } from "./survey-responses";
import taxiTemplate from "./survey-templates/krapfentaxi.json";
import golfTemplate from "./survey-templates/golf.json";

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
  const [template, setTemplate] = useState("blank");
  const creationRequest = useRef<
    Parameters<LeonAidApiClient["createSurvey"]>[1] | null
  >(null);
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
  const [accessMode, setAccessMode] = useState<"anonymous" | "invitation">(
    "anonymous",
  );
  const [invitations, setInvitations] =
    useState<SurveyInvitationsResponse | null>(null);
  const [invitationOffset, setInvitationOffset] = useState(0);
  const [recipientEmail, setRecipientEmail] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [expiryDays, setExpiryDays] = useState(30);
  const invitationRequest = useRef<SurveyInvitationCreate | null>(null);

  const [defaults, setDefaults] = useState<TimeoutSettingsResponse | null>(
    null,
  );
  const [defaultValue, setDefaultValue] = useState("");
  const [endedRetentionDays, setEndedRetentionDays] = useState("");
  const [trashRetentionDays, setTrashRetentionDays] = useState("");
  const [confirmTrash, setConfirmTrash] = useState(false);
  const [confirmErasure, setConfirmErasure] = useState(false);
  const [understoodErasure, setUnderstoodErasure] = useState(false);
  const [deletion, setDeletion] = useState<SurveyDeletionResponse | null>(null);
  const erasureRequest = useRef<{
    operationId: string;
    expectedRevision: number;
  } | null>(null);
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
      try {
        const status = await client.getSurveyDeletion(key);
        setDeletion(status);
        setSummary(null);
        setDraft(null);
        setInvitations(null);
        return;
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
      }
      const value = await client.getSurvey(key);
      setSummary(value);
      setAccessMode(value.accessMode);
      setInvitationOffset(0);
      if (
        value.status !== "deleted" &&
        value.accessMode === "invitation" &&
        value.capabilities?.includes("manage_invitations")
      ) {
        setInvitations(await client.listSurveyInvitations(key, { offset: 0 }));
      } else setInvitations(null);

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
    if (!id || !deletion || ["completed", "failed"].includes(deletion.status))
      return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await client.getSurveyDeletion(id);
        if (!stopped) {
          setDeletion(status);
          setMessage("");
          if (!["completed", "failed"].includes(status.status))
            timer = setTimeout(poll, 2000);
        }
      } catch (error) {
        if (!stopped) setMessage(errorMessage(error));
        // An unavailable status is not success. The reload control explicitly
        // retries using the durable server record, without another delete request.
      }
    };
    timer = setTimeout(poll, 1000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [client, id, deletion?.status]);
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
          setEndedRetentionDays(
            value.endedRetentionSeconds == null
              ? ""
              : String(value.endedRetentionSeconds / 86400),
          );
          setTrashRetentionDays(
            value.trashRetentionSeconds == null
              ? ""
              : String(value.trashRetentionSeconds / 86400),
          );
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
      // Keep exactly the same payload after an uncertain acknowledgement.
      creationRequest.current ??= {
        operationId: creation.operationId,
        title,
        actionId: actionId || null,
        definition:
          template === "blank"
            ? {
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
              }
            : {
                ...structuredClone(
                  template === "krapfentaxi" ? taxiTemplate : golfTemplate,
                ),
                title,
              },
      };
      try {
        await client.createSurvey(creation.id, creationRequest.current);
      } catch (error) {
        if (
          error instanceof ApiError &&
          [401, 403, 404, 422, 429].includes(error.status)
        )
          creationRequest.current = null;
        throw error;
      }
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
  async function erase() {
    if (!summary || !understoodErasure) return;
    erasureRequest.current ??= {
      operationId: crypto.randomUUID(),
      expectedRevision: summary.revision,
    };
    await run(async () => {
      let status: SurveyDeletionResponse;
      try {
        status = await client.deleteSurveyPermanently(
          summary.id,
          erasureRequest.current!,
        );
      } catch (error) {
        // A committed request with a lost acknowledgement must be recoverable
        // from the server, including after a full browser reload.
        try {
          status = await client.getSurveyDeletion(summary.id);
        } catch {
          throw error;
        }
      }
      setDeletion(status);
      setSummary(null);
      setDraft(null);
      setInvitations(null);
      setConfirmErasure(false);
    }, "");
  }
  return (
    <section className="surveys-module" aria-label="Umfragen">
      <header className="surveys-heading">
        <div>
          {(id || createNew) && <a href="/admin/surveys">← Alle Umfragen</a>}
          <h1>
            {deletion
              ? "Umfrage löschen"
              : (summary?.title ??
                (id
                  ? "Umfrage laden"
                  : createNew
                    ? "Neue Umfrage"
                    : "Umfragen"))}
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
      {deletion && (
        <section
          className="surveys-management"
          aria-label="Endgültige Löschung"
        >
          <p role="status">
            {
              {
                pending:
                  "Die endgültige Löschung wurde beauftragt. Antworten und Exportdateien sind nicht mehr zugänglich.",
                retrying:
                  "Die Löschung ist noch nicht abgeschlossen. Der Server bearbeitet den Auftrag weiter; Antworten und Exportdateien bleiben gesperrt.",
                failed: deletion.retryEventId
                  ? "Die Löschung konnte nicht abgeschlossen werden. Sie können den Auftrag erneut ausführen. Die Daten bleiben gesperrt."
                  : "Die Löschung konnte nicht abgeschlossen werden. Bitte wenden Sie sich an die Administration, damit der Auftrag erneut ausgeführt wird. Die Daten bleiben gesperrt.",
                completed:
                  "Die Umfrage einschließlich Antworten, Einladungen und Exportdateien wurde endgültig gelöscht.",
              }[deletion.status]
            }
          </p>
          <p>
            Der Löschauftrag bleibt auch nach dem Schließen dieser Seite
            bestehen.
          </p>
          {deletion.status === "failed" && deletion.retryEventId && (
            <Button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await client.retryOperationalJob(deletion.retryEventId!);
                  await refresh(deletion.surveyId);
                }, "Der Löschauftrag wurde erneut zur Bearbeitung vorgemerkt.")
              }
            >
              Löschung erneut versuchen
            </Button>
          )}
          <a href="/admin/surveys">Zur Umfragenübersicht</a>
        </section>
      )}
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
              <summary>Aufbewahrung und Papierkorb</summary>
              <p>
                Diese Fristen gelten für alle Umfragen, auch für bereits
                beendete. Leere Felder schalten den jeweiligen automatischen
                Schritt aus. Inaktivität beim Ausfüllen löscht keine Antworten.
              </p>
              <p>
                Nach Ablauf der ersten Frist kommen beendete und archivierte
                Umfragen in den Papierkorb. Die zweite Frist beginnt dort und
                führt zur endgültigen Löschung einschließlich Antworten und
                Exportdateien. Bereits beauftragte endgültige Löschungen lassen
                sich nicht zurücknehmen.
              </p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(async () => {
                    const value = await client.updateSurveySettings({
                      operationId: crypto.randomUUID(),
                      expectedRevision: defaults.revision,
                      inactivityTimeoutSeconds:
                        defaults.inactivityTimeoutSeconds,
                      endedRetentionSeconds:
                        endedRetentionDays === ""
                          ? null
                          : Math.round(Number(endedRetentionDays) * 86400),
                      trashRetentionSeconds:
                        trashRetentionDays === ""
                          ? null
                          : Math.round(Number(trashRetentionDays) * 86400),
                    });
                    setDefaults(value);
                  }, "Aufbewahrungsfristen wurden gespeichert.");
                }}
              >
                <label>
                  Tage nach Ende bis zum Papierkorb
                  <input
                    type="number"
                    min={1 / 86400}
                    max={3650}
                    step="any"
                    value={endedRetentionDays}
                    onChange={(event) =>
                      setEndedRetentionDays(event.target.value)
                    }
                  />
                </label>
                <label>
                  Tage im Papierkorb bis zur endgültigen Löschung
                  <input
                    type="number"
                    min={1 / 86400}
                    max={3650}
                    step="any"
                    value={trashRetentionDays}
                    onChange={(event) =>
                      setTrashRetentionDays(event.target.value)
                    }
                  />
                </label>
                <Button type="submit" disabled={busy}>
                  Aufbewahrungsfristen speichern
                </Button>
              </form>
            </details>
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
              disabled={busy || creationRequest.current !== null}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            Fragebogenvorlage
            <select
              aria-label="Fragebogenvorlage"
              value={template}
              disabled={busy || creationRequest.current !== null}
              onChange={(e) => setTemplate(e.target.value)}
              aria-describedby="survey-template-description"
            >
              <option value="blank">Leerer Fragebogen</option>
              <option value="krapfentaxi">
                Krapfentaxi – Lieferung und Zufriedenheit
              </option>
              <option value="golf">
                Golfturnier – Veranstaltung und Verbesserungen
              </option>
            </select>
          </label>
          <p id="survey-template-description">
            {template === "blank"
              ? "Beginnen Sie mit einer Textfrage und ergänzen Sie weitere Fragen."
              : "Drei Seiten mit vorbereiteten Fragen. Sie können alle Fragen vor der Veröffentlichung anpassen. Die Vorlage enthält keine Antworten oder Empfänger."}
          </p>
          <label>
            Zuordnung
            <select
              value={actionId}
              disabled={busy || creationRequest.current !== null}
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
              {summary.status === "active" &&
                summary.accessMode === "anonymous" && (
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
                <>
                  <Button
                    variant="secondary"
                    disabled={pending}
                    onClick={() => void mutate("restore")}
                  >
                    Wiederherstellen
                  </Button>
                  <Button
                    variant="danger"
                    disabled={pending}
                    onClick={() => setConfirmErasure(true)}
                  >
                    Endgültig löschen
                  </Button>
                </>
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
            {confirmErasure &&
              summary.status === "deleted" &&
              allowed("delete") && (
                <div
                  className="surveys-confirm"
                  role="group"
                  aria-label="Endgültige Löschung bestätigen"
                >
                  <p>
                    Der Fragebogen, alle Antworten, Einladungen und
                    Exportdateien werden unwiderruflich gelöscht. Eine
                    Wiederherstellung ist danach nicht möglich.
                  </p>
                  <label className="surveys-erasure-consent">
                    <input
                      type="checkbox"
                      checked={understoodErasure}
                      onChange={(event) =>
                        setUnderstoodErasure(event.target.checked)
                      }
                    />
                    Ich möchte diese Umfrage mit allen zugehörigen Daten
                    endgültig löschen.
                  </label>
                  <div className="surveys-actions">
                    <Button
                      variant="danger"
                      disabled={pending || !understoodErasure}
                      onClick={() => void erase()}
                    >
                      Löschung jetzt beauftragen
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => {
                        setConfirmErasure(false);
                        setUnderstoodErasure(false);
                      }}
                    >
                      Abbrechen
                    </Button>
                  </div>
                </div>
              )}
            <p>
              {summary.accessMode === "invitation"
                ? "Persönliche Einladungen: Antworten sind dem jeweiligen Empfänger zuordenbar."
                : "Anonymer Link: Antworten werden keinem Empfänger oder Auftrag zugeordnet."}
            </p>
            {summary.status === "draft" && allowed("publish") && (
              <details className="surveys-settings">
                <summary>Zugang zur Umfrage</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run(async () => {
                      await client.updateSurveyAccess(summary.id, {
                        operationId: crypto.randomUUID(),
                        expectedRevision: summary.revision,
                        accessMode,
                      });
                      await refresh(summary.id);
                    }, "Zugangsmodus wurde gespeichert.");
                  }}
                >
                  <label>
                    Zugangsmodus
                    <select
                      value={accessMode}
                      onChange={(e) =>
                        setAccessMode(
                          e.target.value as "anonymous" | "invitation",
                        )
                      }
                    >
                      <option value="anonymous">Anonymer Link</option>
                      <option value="invitation">Persönliche Einladung</option>
                    </select>
                  </label>
                  <p>
                    Nach der Veröffentlichung bleibt dieser Modus festgelegt.
                  </p>
                  <Button type="submit" disabled={pending}>
                    Zugangsmodus speichern
                  </Button>
                </form>
              </details>
            )}
            {invitations && allowed("manage_invitations") && (
              <details className="surveys-settings">
                <summary>Einladungen ({invitations.total})</summary>
                <Button
                  variant="secondary"
                  disabled={pending}
                  onClick={() =>
                    void run(async () => {
                      setInvitations(
                        await client.listSurveyInvitations(summary.id, {
                          offset: invitationOffset,
                        }),
                      );
                    }, "Versandstatus wurde aktualisiert.")
                  }
                >
                  Versandstatus aktualisieren
                </Button>
                {summary.status === "active" && (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void run(async () => {
                        invitationRequest.current ??= {
                          operationId: crypto.randomUUID(),
                          expectedRevision: summary.revision,
                          recipientEmail,
                          recipientName,
                          expiresInDays: expiryDays,
                        };
                        try {
                          await client.createSurveyInvitation(
                            summary.id,
                            invitationRequest.current,
                          );
                        } catch (error) {
                          if (
                            error instanceof ApiError &&
                            [400, 401, 403, 404, 409, 422].includes(
                              error.status,
                            )
                          )
                            invitationRequest.current = null;
                          throw error;
                        }
                        invitationRequest.current = null;
                        setRecipientEmail("");
                        setRecipientName("");
                        await refresh(summary.id);
                      }, "Einladung wurde zum Versand vorgemerkt.");
                    }}
                  >
                    <label>
                      E-Mail des Empfängers
                      <input
                        type="email"
                        required
                        maxLength={254}
                        value={recipientEmail}
                        readOnly={!!invitationRequest.current}
                        onChange={(e) => setRecipientEmail(e.target.value)}
                      />
                    </label>
                    <label>
                      Name des Empfängers (optional)
                      <input
                        maxLength={160}
                        value={recipientName}
                        readOnly={!!invitationRequest.current}
                        onChange={(e) => setRecipientName(e.target.value)}
                      />
                    </label>
                    <label>
                      Gültigkeit in Tagen
                      <input
                        type="number"
                        min={1}
                        max={90}
                        value={expiryDays}
                        readOnly={!!invitationRequest.current}
                        onChange={(e) => setExpiryDays(Number(e.target.value))}
                      />
                    </label>
                    <Button type="submit" disabled={pending}>
                      Einladung senden
                    </Button>
                  </form>
                )}
                <ul className="surveys-list">
                  {invitations.items.map((invitation) => (
                    <li key={invitation.id}>
                      <span>
                        {invitation.recipientName || invitation.recipientEmail}
                      </span>
                      {invitation.recipientName && (
                        <span>{invitation.recipientEmail}</span>
                      )}
                      <span>
                        {
                          {
                            queued: "Zum Versand vorgemerkt",
                            retrying:
                              "Versand verzögert · erneuter Versuch folgt",
                            failed:
                              "Versand fehlgeschlagen · bitte Administration kontaktieren",
                            cancelled: "Nicht versendet · Umfrage geschlossen",
                            sent: "Versendet",
                            redeemed: "Teilnahme begonnen",
                            expired: "Abgelaufen",
                            revoked: "Widerrufen",
                          }[invitation.status]
                        }
                      </span>
                      <span>
                        Gültig bis{" "}
                        {new Date(invitation.expiresAt).toLocaleDateString(
                          "de-DE",
                        )}
                      </span>
                      {!["revoked", "expired"].includes(invitation.status) && (
                        <Button
                          variant="secondary"
                          disabled={pending}
                          onClick={() =>
                            void run(async () => {
                              await client.revokeSurveyInvitation(
                                summary.id,
                                invitation.id,
                                {
                                  operationId: crypto.randomUUID(),
                                  expectedRevision: summary.revision,
                                },
                              );
                              await refresh(summary.id);
                            }, "Einladung wurde widerrufen.")
                          }
                        >
                          Einladung widerrufen
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="surveys-actions">
                  <Button
                    variant="secondary"
                    disabled={pending || invitationOffset === 0}
                    onClick={() =>
                      void run(async () => {
                        const next = Math.max(0, invitationOffset - 100);
                        setInvitations(
                          await client.listSurveyInvitations(summary.id, {
                            offset: next,
                          }),
                        );
                        setInvitationOffset(next);
                      }, "")
                    }
                  >
                    Vorherige Einladungen
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={
                      pending ||
                      invitationOffset + invitations.items.length >=
                        invitations.total
                    }
                    onClick={() =>
                      void run(async () => {
                        const next = invitationOffset + 100;
                        setInvitations(
                          await client.listSurveyInvitations(summary.id, {
                            offset: next,
                          }),
                        );
                        setInvitationOffset(next);
                      }, "")
                    }
                  >
                    Weitere Einladungen
                  </Button>
                </div>
              </details>
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
          {summary.status !== "deleted" && allowed("view_aggregates") && (
            <details className="surveys-settings">
              <summary>Antworten auswerten</summary>
              <SurveyAnalysis
                key={summary.id}
                client={client}
                surveyId={summary.id}
                canTest={allowed("design")}
                canExportRaw={allowed("export_raw")}
                canExportReports={allowed("export_reports")}
              />
            </details>
          )}
          {summary.status !== "deleted" &&
            !allowed("view_aggregates") &&
            (allowed("export_raw") || allowed("export_reports")) && (
              <details className="surveys-settings">
                <summary>Antworten exportieren</summary>
                <SurveyAnalysis
                  key={summary.id}
                  client={client}
                  surveyId={summary.id}
                  canTest={allowed("design")}
                  canExportRaw={allowed("export_raw")}
                  canExportReports={allowed("export_reports")}
                  exportOnly
                />
              </details>
            )}
          {summary.status !== "deleted" && allowed("read_responses") && (
            <details
              className="surveys-settings"
              open={Boolean(
                new URLSearchParams(location.search).get("responseSelection"),
              )}
            >
              <summary>Einzelantworten lesen</summary>
              <SurveyResponses
                key={summary.id}
                client={client}
                surveyId={summary.id}
                canTest={allowed("design")}
              />
            </details>
          )}
          {new URLSearchParams(location.search).has("responseSelection") &&
            (!allowed("read_responses") || summary.status === "deleted") && (
              <p role="alert">
                Dieser Antwortstand ist für Sie nicht zugänglich.
              </p>
            )}
          {["draft", "active"].includes(summary.status) &&
            allowed("publish") &&
            !allowed("design") && (
              <PublicationReview
                key={summary.id}
                client={client}
                surveyId={summary.id}
                onPublished={() => refresh(summary.id)}
              />
            )}
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

function PublicationReview({
  client,
  surveyId,
  onPublished,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  onPublished: () => Promise<void>;
}) {
  const [candidate, setCandidate] = useState<SurveyDraftResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const operation = useRef<{
    operationId: string;
    expectedRevision: number;
  } | null>(null);
  async function load() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setCandidate(await client.getSurveyPublicationDraft(surveyId));
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (!candidate) return;
    operation.current ??= {
      operationId: crypto.randomUUID(),
      expectedRevision: candidate.revision,
    };
    setBusy(true);
    setError("");
    try {
      await client.publishSurvey(surveyId, operation.current);
      operation.current = null;
      setCandidate(null);
      setNotice("Der geprüfte Fragebogen wurde veröffentlicht.");
      await onPublished();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        operation.current = null;
        setCandidate(null);
      }
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Veröffentlichung prüfen">
      <h2>Fragebogen zur Veröffentlichung prüfen</h2>
      <p>
        Die Vorschau speichert keine Antworten. Veröffentlicht wird genau der
        geladene Entwurfsstand.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <Button
        variant="secondary"
        disabled={busy || operation.current !== null}
        onClick={() => void load()}
      >
        Aktuellen Entwurf prüfen
      </Button>
      {candidate && (
        <>
          <SurveyPublicationPreview definition={candidate.definition} />
          <Button disabled={busy} onClick={() => void publish()}>
            {operation.current
              ? "Veröffentlichung erneut prüfen"
              : "Veröffentlichen"}
          </Button>
        </>
      )}
    </section>
  );
}
