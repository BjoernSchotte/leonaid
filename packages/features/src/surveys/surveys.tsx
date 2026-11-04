import {
  ClipboardList,
  ExternalLink,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useRef,
} from "react";
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
import {
  Button,
  buttonClassName,
  cn,
  ConfirmDialog,
  EmptyState,
  Field,
  Icon,
  isTypingTarget,
  Kbd,
  LeaveGuardContext,
  NextStep,
  ReadOnlyNotice,
  StatusLabel,
  type StatusShape,
  useDiscardDialog,
  useHotkeys,
  useLeaveGuard,
} from "@leonaid/ui";
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
import { useContextCommands } from "../command-palette/store";
import { formatDateTime, shortDate } from "../shared/dates";
import "./surveys.css";
import { SurveyAnalysis } from "./survey-analysis";
import { surveyResponsesHref } from "./survey-responses";
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
type SettingsField = "accessMode" | "scheduledEnd" | "timeout";
/**
 * Per-field edit tracking for the survey settings forms. A field is dirty while
 * its edit count differs from the count last confirmed by the server. A refresh
 * replaces only clean fields, so a save of one form cannot overwrite unsaved
 * input in another form.
 */
class SettingsEdits {
  private survey: string | null = null;
  private edited: Record<SettingsField, number> = {
    accessMode: 0,
    scheduledEnd: 0,
    timeout: 0,
  };
  private synced = { ...this.edited };
  /** A different survey starts clean: its server values replace every field. */
  forSurvey(key: string) {
    if (this.survey === key) return;
    this.survey = key;
    this.edited = { accessMode: 0, scheduledEnd: 0, timeout: 0 };
    this.synced = { ...this.edited };
  }
  edit(field: SettingsField) {
    this.edited[field] += 1;
  }
  /** Token for the value a save submits; pass it to `saved` after success. */
  snapshot(field: SettingsField) {
    return this.edited[field];
  }
  /** Edits made after `snapshot` keep the field dirty. */
  saved(field: SettingsField, snapshot: number) {
    this.synced[field] = snapshot;
  }
  dirty(field: SettingsField) {
    return this.edited[field] !== this.synced[field];
  }
}
const localDateTime = (value: string | null | undefined) => {
  if (!value) return "";
  const end = new Date(value);
  return new Date(end.getTime() - end.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};
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
  const settingsEdits = useRef(new SettingsEdits());
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
      const edits = settingsEdits.current;
      edits.forSurvey(key);
      setSummary(value);
      if (!edits.dirty("accessMode")) setAccessMode(value.accessMode);
      setInvitationOffset(0);
      if (
        value.status !== "deleted" &&
        value.accessMode === "invitation" &&
        value.capabilities?.includes("manage_invitations")
      ) {
        setInvitations(await client.listSurveyInvitations(key, { offset: 0 }));
      } else setInvitations(null);

      if (!edits.dirty("scheduledEnd"))
        setScheduledEnd(localDateTime(value.endsAt));
      if (!edits.dirty("timeout"))
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
  const settingsDirty =
    !!summary &&
    (accessMode !== summary.accessMode ||
      scheduledEnd !== localDateTime(summary.endsAt) ||
      timeout !== (summary.inactivityTimeoutSeconds?.toString() ?? "") ||
      recipientEmail !== "" ||
      recipientName !== "");
  const createDirty =
    !id && createNew && title.trim() !== "" && creationRequest.current === null;
  const dirty =
    createDirty || settingsDirty || (draft !== null && saveState !== "saved");
  useLeaveGuard(dirty);
  const leaveGuards = useContext(LeaveGuardContext);
  const { confirmDiscard, dialog: discardDialog } = useDiscardDialog("Sie");
  const leaveToList = useCallback(async () => {
    if (dirty && !(await confirmDiscard())) return;
    if (leaveGuards) leaveGuards.leaving = true;
    window.location.assign("/admin/surveys");
  }, [dirty, confirmDiscard, leaveGuards]);

  const items = list?.items ?? [];
  const [focus, setFocus] = useState(0);
  const rowLinks = useRef<(HTMLAnchorElement | null)[]>([]);
  const move = (delta: number) => {
    if (!items.length) return;
    const next = Math.max(0, Math.min(items.length - 1, focus + delta));
    setFocus(next);
    rowLinks.current[next]?.focus();
  };
  const onList = !id && !createNew;
  const openCreate = () => window.location.assign("/admin/surveys/new");
  useHotkeys(
    onList
      ? [
          {
            keys: "j",
            label: "Nächste Umfrage",
            group: "Umfragen",
            run: () => move(1),
          },
          {
            keys: "k",
            label: "Vorherige Umfrage",
            group: "Umfragen",
            run: () => move(-1),
          },
          {
            keys: "c",
            label: "Umfrage anlegen",
            group: "Umfragen",
            run: openCreate,
          },
        ]
      : [
          {
            keys: "escape",
            label: "Zurück zu allen Umfragen",
            group: "Umfrage",
            // Esc in a field stays with the field.
            when: () => !isTypingTarget(document.activeElement),
            run: () => void leaveToList(),
          },
        ],
    [onList, items.length, focus, leaveToList],
  );
  useContextCommands(
    onList
      ? [
          {
            id: "create:survey",
            label: "Umfrage anlegen",
            group: "Umfragen",
            icon: Plus,
            keys: "c",
            keywords: ["Neue Umfrage", "Fragebogen"],
            run: openCreate,
          },
        ]
      : [],
  );

  const actionName = (actionId: string | null) =>
    actionId
      ? (list?.actions.find((action) => action.id === actionId)?.name ??
        "Mit Aktion verknüpft")
      : "Eigenständig";
  const heading = deletion
    ? "Umfrage löschen"
    : (summary?.title ??
      (id ? "Umfrage laden" : createNew ? "Neue Umfrage" : "Umfragen"));

  return (
    <section
      className={cn("surveys-module", onList ? "surveys-index" : "survey-page")}
      aria-label="Umfragen"
    >
      {!onList && (
        <nav aria-label="Brotkrumen" className="crumbs">
          <a
            aria-label="Alle Umfragen"
            href="/admin/surveys"
            onClick={(event) => {
              if (!dirty || event.metaKey || event.ctrlKey || event.shiftKey)
                return;
              event.preventDefault();
              void leaveToList();
            }}
          >
            Umfragen
          </a>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{heading}</span>
        </nav>
      )}
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1>{heading}</h1>
            {onList && list ? (
              <span className="page-count num" aria-live="polite">
                {list.total} {list.total === 1 ? "Umfrage" : "Umfragen"}
              </span>
            ) : null}
            {summary ? (
              <span data-survey-status={summary.status}>
                <StatusLabel
                  shape={shapes[summary.status]}
                  status={labels[summary.status]}
                />
              </span>
            ) : null}
          </div>
          {summary ? (
            <p className="page-sub">
              {actionName(summary.actionId)} ·{" "}
              {summary.accessMode === "invitation"
                ? "Persönliche Einladungen"
                : "Anonymer Link"}
              {summary.endsAt
                ? ` · Antworten bis ${formatDateTime(summary.endsAt)}`
                : ""}
            </p>
          ) : createNew && !id ? (
            <p className="page-sub">
              Starten Sie mit einer Frage oder einer Vorlage. Weitere Fragen und
              Seiten ergänzen Sie im nächsten Schritt.
            </p>
          ) : null}
        </div>
        {onList && (
          <div className="page-actions">
            <a
              className={buttonClassName({ variant: "primary" })}
              href="/admin/surveys/new"
            >
              <Icon icon={Plus} size={16} />
              <span className="btn-label">Neue Umfrage</span>
              <Kbd announce={false} keys="c" subtle />
            </a>
          </div>
        )}
      </header>
      {message && (
        <div role="alert" className="callout tone-danger surveys-error">
          <p>{message}</p>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Aktuellen Stand laden
          </Button>
        </div>
      )}
      {notice && (
        <p className="surveys-notice" role="status">
          {notice}
        </p>
      )}
      {loading && (
        <p className="surveys-loading" role="status">
          Umfragen werden geladen …
        </p>
      )}
      {deletion && (
        <section
          className="surveys-panel surveys-deletion"
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
          <p className="surveys-muted">
            Der Löschauftrag bleibt auch nach dem Schließen dieser Seite
            bestehen.
          </p>
          <div className="surveys-actions">
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
          </div>
        </section>
      )}
      {onList && list && (
        <>
          <form
            className="surveys-filters"
            role="search"
            onSubmit={(e) => e.preventDefault()}
          >
            <label className="search">
              <Search aria-hidden="true" size={15} />
              <span className="sr-only">Umfrage suchen</span>
              <input
                type="search"
                value={search}
                maxLength={240}
                placeholder="Umfragen durchsuchen"
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                  setFocus(0);
                }}
              />
            </label>
            <label className="select-inline">
              <span className="sr-only">Status</span>
              <select
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value as Status | "");
                  setOffset(0);
                  setFocus(0);
                }}
              >
                <option value="">Alle Status</option>
                {Object.entries(labels).map(([key, label]) => (
                  <option value={key} key={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </form>
          {items.length ? (
            <ul className="surveys-list survey-list">
              {items.map((item, index) => (
                <li className="survey-row" key={item.id}>
                  <span className="survey-row-main">
                    <a
                      className="survey-row-title"
                      href={`/admin/surveys/${item.id}`}
                      tabIndex={index === focus ? 0 : -1}
                      onFocus={() => setFocus(index)}
                      ref={(element) => {
                        rowLinks.current[index] = element;
                      }}
                    >
                      {item.title}
                    </a>
                    <span className="survey-row-meta">
                      {actionName(item.actionId)} ·{" "}
                      {item.accessMode === "invitation"
                        ? "Persönliche Einladungen"
                        : "Anonymer Link"}
                      {item.ownerUserId === identity.userId
                        ? " · von Ihnen erstellt"
                        : ""}
                    </span>
                  </span>
                  <span
                    className="survey-row-status"
                    data-survey-status={item.status}
                  >
                    <StatusLabel
                      shape={shapes[item.status]}
                      status={labels[item.status]}
                    />
                  </span>
                  <span className="survey-row-close num">
                    {item.endsAt
                      ? `bis ${shortDate(item.endsAt)}`
                      : item.status === "draft" || item.status === "active"
                        ? "kein Ende"
                        : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={ClipboardList}
              title={
                search || filter
                  ? "Keine passenden Umfragen"
                  : "Noch keine Umfragen"
              }
              description={
                search || filter
                  ? "Ändern Sie die Suche oder den Status-Filter."
                  : "Fragen Sie Helfer, Sponsoren oder Mitglieder nach ihrer Meinung. Antworten lassen sich anonym auswerten."
              }
              action={
                search || filter ? undefined : (
                  <a
                    className={buttonClassName({ variant: "primary" })}
                    href="/admin/surveys/new"
                  >
                    Umfrage anlegen
                  </a>
                )
              }
            />
          )}
          {items.length > 0 && (
            <p className="list-hint" aria-hidden="true">
              <Kbd keys="j" /> <Kbd keys="k" /> bewegen · <Kbd keys="enter" />{" "}
              öffnen · <Kbd keys="c" /> neue Umfrage
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
            <section
              className="surveys-defaults"
              aria-labelledby="surveys-defaults-title"
            >
              <h2 id="surveys-defaults-title">Für alle Umfragen</h2>
              <details className="surveys-settings">
                <summary>Aufbewahrung und Papierkorb</summary>
                <div className="surveys-settings-body">
                  <p>
                    Diese Fristen gelten für alle Umfragen, auch für bereits
                    beendete. Leere Felder schalten den jeweiligen automatischen
                    Schritt aus. Inaktivität beim Ausfüllen löscht keine
                    Antworten.
                  </p>
                  <p>
                    Nach Ablauf der ersten Frist kommen beendete und archivierte
                    Umfragen in den Papierkorb. Die zweite Frist beginnt dort
                    und führt zur endgültigen Löschung einschließlich Antworten
                    und Exportdateien. Bereits beauftragte endgültige Löschungen
                    lassen sich nicht zurücknehmen.
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
                    <Field label="Tage nach Ende bis zum Papierkorb">
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
                    </Field>
                    <Field label="Tage im Papierkorb bis zur endgültigen Löschung">
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
                    </Field>
                    <Button type="submit" variant="secondary" disabled={busy}>
                      Aufbewahrungsfristen speichern
                    </Button>
                  </form>
                </div>
              </details>
              <details className="surveys-settings">
                <summary>Standard für Teilantworten</summary>
                <div className="surveys-settings-body">
                  <p>
                    Gilt für neue Teilnahmen ohne abweichende
                    Umfrage-Einstellung. Bereits begonnene Teilnahmen behalten
                    ihren Zeitraum.
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
                    <Field label="Standardzeitraum in Sekunden">
                      <input
                        type="number"
                        min={1}
                        max={604800}
                        step={1}
                        required
                        value={defaultValue}
                        onChange={(e) => setDefaultValue(e.target.value)}
                      />
                    </Field>
                    <Button type="submit" variant="secondary" disabled={busy}>
                      Standard speichern
                    </Button>
                  </form>
                </div>
              </details>
            </section>
          )}
        </>
      )}
      {!id && createNew && (
        <form
          className="surveys-panel surveys-create"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <div className="field">
            <label className="field-label" htmlFor="survey-title">
              Titel der Umfrage
            </label>
            <input
              className="input"
              id="survey-title"
              required
              maxLength={240}
              value={title}
              disabled={busy || creationRequest.current !== null}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="survey-template">
              Fragebogenvorlage
            </label>
            <select
              className="input select"
              id="survey-template"
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
            <p className="field-hint" id="survey-template-description">
              {template === "blank"
                ? "Beginnen Sie mit einer Textfrage und ergänzen Sie weitere Fragen."
                : "Drei Seiten mit vorbereiteten Fragen. Sie können alle Fragen vor der Veröffentlichung anpassen. Die Vorlage enthält keine Antworten oder Empfänger."}
            </p>
          </div>
          <Field label="Zuordnung">
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
          </Field>
          <div className="surveys-actions">
            <Button
              type="submit"
              icon={Plus}
              loading={busy}
              disabled={!title.trim()}
            >
              {busy ? "Wird erstellt …" : "Umfrage erstellen"}
            </Button>
          </div>
        </form>
      )}
      {summary && (
        <>
          <section
            className="surveys-management"
            aria-label="Umfrage verwalten"
          >
            <SurveyNextStep
              summary={summary}
              allowed={allowed}
              pending={pending}
              onMutate={(action) => void mutate(action)}
              onErase={() => setConfirmErasure(true)}
            />
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
                  <label className="checkbox surveys-erasure-consent">
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
                      variant="ghost"
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
            <ConfirmDialog
              open={confirmTrash}
              onOpenChange={setConfirmTrash}
              title="Umfrage in den Papierkorb verschieben?"
              description="Die Umfrage wird geschlossen und aus der normalen Bearbeitung entfernt. Sie können sie später wiederherstellen."
              confirmLabel="Jetzt in Papierkorb verschieben"
              pending={busy}
              tone="danger"
              onConfirm={() => void mutate("trash")}
            />
          </section>
          <nav className="section-links" aria-label="Bereiche der Umfrage">
            {draft ||
            (["draft", "active"].includes(summary.status) &&
              allowed("publish")) ? (
              <a href="#survey-questions">Fragen</a>
            ) : null}
            {summary.status !== "deleted" &&
            (allowed("view_aggregates") ||
              allowed("read_responses") ||
              allowed("export_raw") ||
              allowed("export_reports")) ? (
              <a href="#survey-answers">Antworten</a>
            ) : null}
            <a href="#survey-settings">Einstellungen</a>
          </nav>
          {(draft ||
            (["draft", "active"].includes(summary.status) &&
              allowed("publish") &&
              !allowed("design"))) && (
            <div className="survey-section" id="survey-questions">
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
            </div>
          )}
          {summary.status !== "deleted" &&
            (allowed("view_aggregates") ||
              allowed("read_responses") ||
              allowed("export_raw") ||
              allowed("export_reports")) && (
              <div
                className="survey-section survey-answers"
                id="survey-answers"
              >
                <h2 className="survey-section-title">Antworten</h2>
                {allowed("view_aggregates") && (
                  <details className="surveys-settings">
                    <summary>Antworten auswerten</summary>
                    <div className="surveys-settings-body">
                      <SurveyAnalysis
                        key={`${summary.id}:${summary.publishedVersionId ?? "draft"}`}
                        client={client}
                        surveyId={summary.id}
                        canTest={allowed("design")}
                        canExportRaw={allowed("export_raw")}
                        canExportReports={allowed("export_reports")}
                      />
                    </div>
                  </details>
                )}
                {!allowed("view_aggregates") &&
                  (allowed("export_raw") || allowed("export_reports")) && (
                    <details className="surveys-settings">
                      <summary>Antworten exportieren</summary>
                      <div className="surveys-settings-body">
                        <SurveyAnalysis
                          key={`${summary.id}:${summary.publishedVersionId ?? "draft"}`}
                          client={client}
                          surveyId={summary.id}
                          canTest={allowed("design")}
                          canExportRaw={allowed("export_raw")}
                          canExportReports={allowed("export_reports")}
                          exportOnly
                        />
                      </div>
                    </details>
                  )}
                {(allowed("view_aggregates") || allowed("read_responses")) && (
                  <p className="surveys-settings surveys-settings-link">
                    <a
                      href={`/admin/surveys/${encodeURIComponent(summary.id)}/responses/summary`}
                    >
                      Auswertung ansehen
                    </a>
                  </p>
                )}
                {allowed("read_responses") && (
                  <p className="surveys-settings surveys-settings-link">
                    <a href={surveyResponsesHref(summary.id, location.search)}>
                      Einzelantworten lesen
                    </a>
                  </p>
                )}
              </div>
            )}
          {new URLSearchParams(location.search).has("responseSelection") &&
            (!allowed("read_responses") || summary.status === "deleted") && (
              <p role="alert" className="callout tone-danger">
                Dieser Antwortstand ist für Sie nicht zugänglich.
              </p>
            )}
          <section
            className="survey-section"
            id="survey-settings"
            aria-labelledby="survey-settings-title"
          >
            <h2 className="survey-section-title" id="survey-settings-title">
              Einstellungen
            </h2>
            <p className="surveys-muted">
              {summary.accessMode === "invitation"
                ? "Persönliche Einladungen: Antworten sind dem jeweiligen Empfänger zuordenbar."
                : "Anonymer Link: Antworten werden keinem Empfänger oder Auftrag zugeordnet."}
            </p>
            {summary.status === "draft" && allowed("publish") && (
              <details className="surveys-settings">
                <summary>Zugang zur Umfrage</summary>
                <div className="surveys-settings-body">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const submitted =
                        settingsEdits.current.snapshot("accessMode");
                      void run(async () => {
                        await client.updateSurveyAccess(summary.id, {
                          operationId: crypto.randomUUID(),
                          expectedRevision: summary.revision,
                          accessMode,
                        });
                        settingsEdits.current.saved("accessMode", submitted);
                        await refresh(summary.id);
                      }, "Zugangsmodus wurde gespeichert.");
                    }}
                  >
                    <Field
                      label="Zugangsmodus"
                      hint="Nach der Veröffentlichung bleibt dieser Modus festgelegt."
                    >
                      <select
                        value={accessMode}
                        onChange={(e) => {
                          settingsEdits.current.edit("accessMode");
                          setAccessMode(
                            e.target.value as "anonymous" | "invitation",
                          );
                        }}
                      >
                        <option value="anonymous">Anonymer Link</option>
                        <option value="invitation">
                          Persönliche Einladung
                        </option>
                      </select>
                    </Field>
                    <Button
                      type="submit"
                      variant="secondary"
                      disabled={pending}
                    >
                      Zugangsmodus speichern
                    </Button>
                  </form>
                </div>
              </details>
            )}
            {invitations && allowed("manage_invitations") && (
              <details className="surveys-settings">
                <summary>Einladungen ({invitations.total})</summary>
                <div className="surveys-settings-body">
                  <div className="surveys-actions">
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
                  </div>
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
                      <div className="field">
                        <label
                          className="field-label"
                          htmlFor="survey-recipient-email"
                        >
                          E-Mail des Empfängers
                        </label>
                        <input
                          className="input"
                          id="survey-recipient-email"
                          type="email"
                          required
                          maxLength={254}
                          value={recipientEmail}
                          readOnly={!!invitationRequest.current}
                          onChange={(e) => setRecipientEmail(e.target.value)}
                        />
                      </div>
                      <Field label="Name des Empfängers (optional)">
                        <input
                          maxLength={160}
                          value={recipientName}
                          readOnly={!!invitationRequest.current}
                          onChange={(e) => setRecipientName(e.target.value)}
                        />
                      </Field>
                      <Field label="Gültigkeit in Tagen">
                        <input
                          type="number"
                          min={1}
                          max={90}
                          value={expiryDays}
                          readOnly={!!invitationRequest.current}
                          onChange={(e) =>
                            setExpiryDays(Number(e.target.value))
                          }
                        />
                      </Field>
                      <Button type="submit" disabled={pending}>
                        Einladung senden
                      </Button>
                    </form>
                  )}
                  <ul className="surveys-list surveys-invitations">
                    {invitations.items.map((invitation) => (
                      <li key={invitation.id}>
                        <span className="surveys-invitation-name">
                          {invitation.recipientName ||
                            invitation.recipientEmail}
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
                              cancelled:
                                "Nicht versendet · Umfrage geschlossen",
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
                        {!["revoked", "expired"].includes(
                          invitation.status,
                        ) && (
                          <Button
                            variant="ghost"
                            size="sm"
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
                </div>
              </details>
            )}
            {["draft", "active"].includes(summary.status) &&
              allowed("publish") && (
                <details className="surveys-settings">
                  <summary>Geplantes Ende</summary>
                  <div className="surveys-settings-body">
                    <p>
                      Die Teilnahme endet automatisch zu diesem Zeitpunkt.
                      Bereits gespeicherte Antworten bleiben erhalten.
                    </p>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const submitted =
                          settingsEdits.current.snapshot("scheduledEnd");
                        void run(async () => {
                          await client.scheduleSurveyEnd(summary.id, {
                            operationId: crypto.randomUUID(),
                            expectedRevision: summary.revision,
                            endsAt: scheduledEnd
                              ? new Date(scheduledEnd).toISOString()
                              : null,
                          });
                          settingsEdits.current.saved(
                            "scheduledEnd",
                            submitted,
                          );
                          await refresh(summary.id);
                        }, "Geplantes Ende wurde gespeichert.");
                      }}
                    >
                      <Field
                        label="Teilnahme endet am"
                        hint={`Lokale Zeitzone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Leer lassen, um ohne geplantes Ende fortzufahren.`}
                      >
                        <input
                          type="datetime-local"
                          value={scheduledEnd}
                          onChange={(e) => {
                            settingsEdits.current.edit("scheduledEnd");
                            setScheduledEnd(e.target.value);
                          }}
                        />
                      </Field>
                      <Button
                        type="submit"
                        variant="secondary"
                        disabled={pending}
                      >
                        Geplantes Ende speichern
                      </Button>
                    </form>
                  </div>
                </details>
              )}
            {summary.status !== "deleted" && allowed("design") && (
              <details className="surveys-settings">
                <summary>Teilantworten nach Inaktivität</summary>
                <div className="surveys-settings-body">
                  <p>
                    Antworten bleiben erhalten. Nach diesem Zeitraum gilt eine
                    neue Teilnahme als Teilantwort. Bereits begonnene Teilnahmen
                    behalten ihren Zeitraum.
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const submitted =
                        settingsEdits.current.snapshot("timeout");
                      void run(async () => {
                        await client.updateSurveyTimeout(summary.id, {
                          operationId: crypto.randomUUID(),
                          expectedRevision: summary.revision,
                          inactivityTimeoutSeconds:
                            timeout === "" ? null : Number(timeout),
                        });
                        settingsEdits.current.saved("timeout", submitted);
                        await refresh(summary.id);
                      }, "Zeitraum wurde gespeichert.");
                    }}
                  >
                    <Field
                      label="Abweichender Zeitraum in Sekunden"
                      hint="Leer lassen, um den Standard zu verwenden. Erlaubt: 1 bis 604800 Sekunden."
                    >
                      <input
                        type="number"
                        min={1}
                        max={604800}
                        step={1}
                        value={timeout}
                        placeholder="Standard verwenden"
                        onChange={(e) => {
                          settingsEdits.current.edit("timeout");
                          setTimeoutValue(e.target.value);
                        }}
                      />
                    </Field>
                    <Button
                      type="submit"
                      variant="secondary"
                      disabled={pending}
                    >
                      Zeitraum speichern
                    </Button>
                  </form>
                </div>
              </details>
            )}
            {summary.status !== "deleted" && allowed("delete") && (
              <div className="surveys-danger">
                <p>
                  <strong>Papierkorb:</strong> Die Umfrage wird geschlossen und
                  lässt sich später wiederherstellen.
                </p>
                <Button
                  variant="ghost"
                  icon={Trash2}
                  disabled={pending}
                  onClick={() => setConfirmTrash(true)}
                >
                  In Papierkorb verschieben
                </Button>
              </div>
            )}
          </section>
        </>
      )}
      {discardDialog}
    </section>
  );
}

const shapes: Record<Status, StatusShape> = {
  draft: "draft",
  active: "progress",
  ended: "done",
  archived: "done",
  deleted: "cancelled",
};

/** "Nächster Schritt" per lifecycle status; read-only roles get a notice. */
function SurveyNextStep({
  summary,
  allowed,
  pending,
  onMutate,
  onErase,
}: {
  summary: SurveySummaryResponse;
  allowed: (capability: string) => boolean;
  pending: boolean;
  onMutate: (action: "end" | "archive" | "unarchive" | "restore") => void;
  onErase: () => void;
}) {
  const closed = "Eine Wiederherstellung öffnet die Teilnahme nicht erneut.";
  switch (summary.status) {
    case "draft":
      if (allowed("design") || allowed("publish"))
        return (
          <NextStep
            data-testid="survey-next-step"
            consequence={
              allowed("publish")
                ? "Noch kann niemand antworten. Prüfen Sie den Fragebogen in der Vorschau und veröffentlichen Sie ihn dann."
                : "Noch kann niemand antworten. Gestalten Sie den Fragebogen; veröffentlichen kann die Umfrage-Verantwortung."
            }
            action={
              <a
                className={buttonClassName({ variant: "primary" })}
                href="#survey-questions"
              >
                Zum Fragebogen
              </a>
            }
          />
        );
      break;
    case "active":
      if (allowed("publish"))
        return (
          <NextStep
            data-testid="survey-next-step"
            consequence={`Antworten gehen ein${summary.endsAt ? ` bis ${formatDateTime(summary.endsAt)}` : ""}. Beenden Sie die Teilnahme, wenn genug Rückmeldungen da sind; danach kann niemand mehr antworten.`}
            action={
              <Button
                variant="danger"
                disabled={pending}
                onClick={() => onMutate("end")}
              >
                Teilnahme beenden
              </Button>
            }
            alternatives={
              summary.accessMode === "anonymous" ? (
                <PublishedLink surveyId={summary.id} />
              ) : undefined
            }
          />
        );
      if (summary.accessMode === "anonymous")
        return (
          <div className="callout surveys-live">
            <span>Die Umfrage ist veröffentlicht. Antworten gehen ein.</span>
            <PublishedLink surveyId={summary.id} />
          </div>
        );
      break;
    case "ended":
      if (allowed("archive"))
        return (
          <NextStep
            data-testid="survey-next-step"
            consequence={`Die Teilnahme ist geschlossen; Antworten bleiben auswertbar. Archivieren Sie die Umfrage, wenn die Auswertung abgeschlossen ist. ${closed}`}
            action={
              <Button disabled={pending} onClick={() => onMutate("archive")}>
                Archivieren
              </Button>
            }
          />
        );
      break;
    case "archived":
      if (allowed("archive"))
        return (
          <NextStep
            data-testid="survey-next-step"
            consequence={`Die Umfrage ist archiviert. ${closed}`}
            action={
              <Button disabled={pending} onClick={() => onMutate("unarchive")}>
                Aus Archiv holen
              </Button>
            }
          />
        );
      break;
    case "deleted":
      if (allowed("delete"))
        return (
          <NextStep
            data-testid="survey-next-step"
            consequence={`Die Umfrage liegt im Papierkorb. ${closed}`}
            action={
              <Button disabled={pending} onClick={() => onMutate("restore")}>
                Wiederherstellen
              </Button>
            }
            alternatives={
              <Button
                variant="ghost"
                className="surveys-danger-ghost"
                disabled={pending}
                onClick={onErase}
              >
                Endgültig löschen
              </Button>
            }
          />
        );
      break;
  }
  return (
    <ReadOnlyNotice data-testid="survey-read-only">
      {summary.status === "draft" || summary.status === "active"
        ? "Sie sehen den Stand der Umfrage; Fragen und Teilnahme ändern andere Rollen."
        : `Die Teilnahme ist geschlossen. ${closed}`}
    </ReadOnlyNotice>
  );
}

function PublishedLink({ surveyId }: { surveyId: string }) {
  return (
    <a
      className={buttonClassName({ variant: "ghost" })}
      href={`/surveys/${surveyId}`}
      target="_blank"
      rel="noreferrer"
    >
      <Icon icon={ExternalLink} size={16} />
      <span className="btn-label">Veröffentlichte Umfrage öffnen</span>
    </a>
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
    <section className="surveys-review" aria-label="Veröffentlichung prüfen">
      <h2>Fragebogen zur Veröffentlichung prüfen</h2>
      <p>
        Die Vorschau speichert keine Antworten. Veröffentlicht wird genau der
        geladene Entwurfsstand.
      </p>
      {error && (
        <p className="callout tone-danger" role="alert">
          {error}
        </p>
      )}
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
