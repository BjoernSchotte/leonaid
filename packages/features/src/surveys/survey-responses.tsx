import {
  ClipboardList,
  CircleDot,
  MessageSquareText,
  SlidersHorizontal,
  Undo2,
} from "lucide-react";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  ApiError,
  type CreateAnalysisSnapshot,
  type FreeTextItems,
  type IndividualResponse,
  type LeonAidApiClient,
  type ResponseItem,
  type ResponseQuestion,
  type ResponseSelection,
  type SurveySummaryResponse,
} from "@leonaid/api-client";
import type { ResponseStatus } from "@leonaid/surveys/contracts";
import {
  Button,
  DetailProps,
  DetailSection,
  EmptyState,
  Field,
  fullBleedPage,
  ListView,
  Modal,
  SkeletonRows,
  StatusIcon,
  StatusLabel,
  statusShape,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import { useContextCommands } from "../command-palette/store";
import "./survey-responses.css";

/*
 * Individual responses of one survey (`/admin/surveys/<id>/responses`).
 *
 * Privacy: every read goes through a frozen server-side selection
 * ("Antwortstand"). The list shows what the server returns for that
 * selection and this account; answers are only fetched for the response
 * that is open in the pane. Access is decided by the server
 * (`read_responses`); the page only hides what the account may not use.
 */

export const responseStatusLabels: Readonly<Record<ResponseStatus, string>> = {
  completed: "Abgeschlossen",
  partial: "Teilantwort",
  in_progress: "In Bearbeitung",
};
const RESPONSE_STATUSES = Object.keys(responseStatusLabels) as ResponseStatus[];
const TEXT_KINDS = new Set(["text", "comment"]);
/** The server pages responses by 50 and accepts offsets up to 5000. */
const PAGE_SIZE = 50;
const MAX_OFFSET = 5000;

export interface ResponseRow extends ResponseItem {
  /** Position in the selection, 1-based ("Antwort 12"). */
  readonly number: number;
}

/** `/admin/surveys/<id>/responses`, keeping a linked selection and response. */
export function surveyResponsesHref(surveyId: string, search = ""): string {
  const current = new URLSearchParams(search);
  const next = new URLSearchParams();
  const selection = current.get("responseSelection");
  const open = current.get("open") ?? current.get("response");
  if (selection) next.set("responseSelection", selection);
  if (selection && open) next.set("open", open);
  const query = next.toString();
  return `/admin/surveys/${encodeURIComponent(surveyId)}/responses${query ? `?${query}` : ""}`;
}

/** Old links named the open response `response=`; the list reads `open=`. */
export function migrateLegacyResponseParam(search: string): string {
  const params = new URLSearchParams(search);
  const legacy = params.get("response");
  if (legacy === null) return search;
  params.delete("response");
  if (!params.has("open") && legacy) params.set("open", legacy);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function answerText(value: unknown, question: ResponseQuestion): string {
  if (value == null || value === "" || (Array.isArray(value) && !value.length))
    return "Nicht beantwortet";
  const choice = (item: unknown) =>
    question.choices.find(
      (c) => JSON.stringify(c.value) === JSON.stringify(item),
    )?.label ?? (typeof item === "string" ? item : JSON.stringify(item));
  if (Array.isArray(value)) return value.map(choice).join("\n");
  if (typeof value === "object" && !Object.keys(value).length)
    return "Nicht beantwortet";
  if (question.kind === "matrix" && typeof value === "object")
    return Object.entries(value)
      .map(
        ([row, item]) =>
          `${question.rows.find((r) => r.value === row)?.label ?? row}: ${choice(item)}`,
      )
      .join("\n");
  return choice(value);
}

const dateTime = (value: string) =>
  new Date(value).toLocaleString("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  });
/** Prototype table format "03.11. 14:20"; the year only when it differs. */
export function receivedLabel(value: string, now = new Date()): string {
  const date = new Date(value);
  const pad = (part: number) => String(part).padStart(2, "0");
  const day = `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.`;
  const year =
    date.getFullYear() === now.getFullYear()
      ? ""
      : String(date.getFullYear()).slice(2);
  return `${day}${year} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
const localInput = (value: string | null) =>
  value
    ? new Date(
        new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000,
      )
        .toISOString()
        .slice(0, 16)
    : "";

/** ApiError text with support code; a read-specific fallback otherwise. */
function readError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError
    ? actionErrorMessage(cause).message
    : fallback;
}

/** Loads every page of a selection the server lets this account read. */
async function loadRows(
  client: LeonAidApiClient,
  surveyId: string,
  snapshotId: string,
  signal?: AbortSignal,
): Promise<{ rows: ResponseRow[]; total: number }> {
  const rows: ResponseRow[] = [];
  let offset = 0;
  let total = 0;
  for (;;) {
    const page = await client.listSurveyResponses(
      surveyId,
      snapshotId,
      offset ? { offset } : {},
      { signal },
    );
    total = page.total;
    page.items.forEach((item, index) =>
      rows.push({ ...item, number: page.offset + index + 1 }),
    );
    offset = page.offset + page.items.length;
    if (!page.items.length || offset >= total || offset > MAX_OFFSET) break;
  }
  return { rows, total };
}

/* ---------------- page ---------------- */

export function SurveyResponsesPage({
  client,
  surveyId,
}: {
  client: LeonAidApiClient;
  surveyId: string;
}) {
  const [summary, setSummary] = useState<SurveySummaryResponse | null>(null);
  const [failure, setFailure] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setFailure("");
    client
      .getSurvey(surveyId, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setSummary(value);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setFailure(
          readError(
            cause,
            "Die Umfrage konnte nicht geladen werden. Prüfen Sie die Verbindung und versuchen Sie es erneut.",
          ),
        );
      });
    return () => controller.abort();
  }, [client, surveyId, attempt]);

  const allowed = (capability: string) =>
    summary?.capabilities?.includes(capability) ?? false;
  const readable = summary !== null && summary.status !== "deleted";
  const surveyHref = `/admin/surveys/${encodeURIComponent(surveyId)}`;
  const title = summary?.title ?? "Umfrage";
  const frame = useCallback<PageFrame>(
    (fullBleed, children) => (
      <div
        className="svr-page"
        data-zone="surveys"
        {...(fullBleed ? fullBleedPage : {})}
      >
        <div className="svr-top">
          <nav aria-label="Brotkrumen" className="crumbs">
            <a href="/admin/surveys">Umfragen</a>
            <span aria-hidden="true">/</span>
            <a href={surveyHref}>{title}</a>
            <span aria-hidden="true">/</span>
            <span aria-current="page">Einzelantworten</span>
          </nav>
        </div>
        {children}
      </div>
    ),
    [surveyHref, title],
  );

  let content;
  if (failure) {
    content = (
      <div className="svr-blocked">
        <div className="callout tone-danger" role="alert">
          <span>{failure}</span>
        </div>
        <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
          Erneut versuchen
        </Button>
      </div>
    );
  } else if (!summary) {
    content = (
      <div className="svr-blocked" role="status" aria-busy="true">
        <span className="sr-only">Antworten werden geladen …</span>
        <SkeletonRows rows={6} />
      </div>
    );
  } else if (!readable || !allowed("read_responses")) {
    content = (
      <div className="svr-blocked">
        <div className="callout tone-warn" role="alert">
          <span>Dieser Antwortstand ist für Sie nicht zugänglich.</span>
        </div>
        <a href={surveyHref}>Zurück zur Umfrage</a>
      </div>
    );
  } else {
    // The responses decide themselves whether the list fills the page.
    return (
      <SurveyResponses
        canTest={allowed("design")}
        client={client}
        frame={frame}
        surveyHref={surveyHref}
        surveyId={surveyId}
      />
    );
  }
  return frame(false, content);
}

/**
 * The page root with the crumbs. Only the list fills main edge to edge
 * (shell contract `fullBleedPage`); the other states keep the page frame.
 */
type PageFrame = (fullBleed: boolean, children: ReactNode) => ReactNode;

/* ---------------- selection ---------------- */

interface SelectionFilter {
  readonly version: string;
  readonly statuses: readonly ResponseStatus[];
  readonly from: string;
  readonly before: string;
  readonly isTest: boolean;
}

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "none" }
  | { readonly kind: "error" }
  | {
      readonly kind: "ready";
      readonly selection: ResponseSelection;
      readonly rows: readonly ResponseRow[];
      readonly total: number;
    };

function SurveyResponses({
  client,
  surveyId,
  surveyHref,
  canTest,
  frame,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  surveyHref: string;
  canTest: boolean;
  frame: PageFrame;
}) {
  const [versions, setVersions] = useState<
    readonly { id: string; number: number }[]
  >([]);
  const [filter, setFilter] = useState<SelectionFilter>({
    version: "",
    statuses: ["partial", "completed"],
    from: "",
    before: "",
    isTest: false,
  });
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");
  const [choosing, setChoosing] = useState(false);
  const [freeTextOpen, setFreeTextOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(false);
  const running = useRef(false);
  const pending = useRef<CreateAnalysisSnapshot | null>(null);
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  // Old `?response=` links open the response through `?open=`.
  useState(() => {
    const next = migrateLegacyResponseParam(window.location.search);
    if (next !== window.location.search)
      history.replaceState(
        history.state,
        "",
        `${window.location.pathname}${next}${window.location.hash}`,
      );
  });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoad({ kind: "loading" });
    setNotice("");
    void (async () => {
      try {
        const value = await client.listSurveyResponseVersions(surveyId, {
          signal,
        });
        if (signal.aborted) return;
        setVersions(value.items);
        setFilter((current) =>
          current.version
            ? current
            : { ...current, version: value.items[0]?.id ?? "" },
        );
        const snapshotId = new URLSearchParams(window.location.search).get(
          "responseSelection",
        );
        if (!snapshotId) {
          setLoad({ kind: "none" });
          return;
        }
        let selection: ResponseSelection;
        try {
          selection = await client.getSurveyResponseSelection(
            surveyId,
            snapshotId,
            { signal },
          );
        } catch (cause) {
          // A selection that is gone or not readable: choose a new one.
          if (cause instanceof ApiError && cause.status < 500) {
            if (signal.aborted) return;
            setNotice(actionErrorMessage(cause).message);
            setLoad({ kind: "none" });
            return;
          }
          throw cause;
        }
        const { rows, total } = await loadRows(
          client,
          surveyId,
          snapshotId,
          signal,
        );
        if (signal.aborted) return;
        setFilter({
          version: selection.filter.versionId,
          statuses: selection.filter.statuses,
          from: localInput(selection.filter.createdFrom),
          before: localInput(selection.filter.createdBefore),
          isTest: selection.filter.isTest,
        });
        setLoad({ kind: "ready", selection, rows, total });
      } catch {
        if (!signal.aborted) setLoad({ kind: "error" });
      }
    })();
    return () => controller.abort();
  }, [client, surveyId, attempt]);

  async function create(repeat = false) {
    if (running.current) return;
    if (!repeat) {
      const createdFrom = filter.from
        ? new Date(filter.from).toISOString()
        : null;
      const createdBefore = filter.before
        ? new Date(filter.before).toISOString()
        : null;
      if (createdFrom && createdBefore && createdFrom >= createdBefore) {
        setError("Das Ende des Zeitraums muss nach seinem Beginn liegen.");
        return;
      }
      pending.current = {
        operationId: crypto.randomUUID(),
        filter: {
          versionId: filter.version,
          statuses: [...filter.statuses],
          isTest: canTest && filter.isTest,
          createdFrom,
          createdBefore,
        },
      };
    }
    if (!pending.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    try {
      // Same operation id after an uncertain acknowledgement: the server
      // returns the selection it already stored.
      const selection = await client.createSurveyResponseSelection(
        surveyId,
        pending.current,
      );
      const { rows, total } = await loadRows(client, surveyId, selection.id);
      if (!mounted.current) return;
      const url = new URL(window.location.href);
      url.searchParams.set("responseSelection", selection.id);
      url.searchParams.delete("open");
      history.replaceState(history.state, "", url);
      pending.current = null;
      setRetry(false);
      setNotice("");
      setChoosing(false);
      setLoad({ kind: "ready", selection, rows, total });
    } catch (cause) {
      if (!mounted.current) return;
      const uncertain = !(cause instanceof ApiError) || cause.status >= 500;
      setError(
        cause instanceof ApiError
          ? actionErrorMessage(cause).message
          : "Die Anfrage konnte nicht bestätigt werden. Bitte versuchen Sie es erneut.",
      );
      setRetry(Boolean(pending.current) && uncertain);
      if (!uncertain) {
        // A refused selection leaves nothing readable on screen.
        pending.current = null;
        setLoad({ kind: "none" });
      }
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const form = (
    <SelectionForm
      busy={busy}
      canTest={canTest}
      error={error}
      filter={filter}
      onChange={setFilter}
      onDiscardRetry={() => {
        pending.current = null;
        setRetry(false);
        setError("");
      }}
      onRetry={() => void create(true)}
      onSubmit={() => void create()}
      retry={retry}
      versions={versions}
    />
  );

  if (load.kind === "ready") {
    return frame(
      true,
      <>
        <ResponseList
          client={client}
          key={load.selection.id}
          onChoose={() => setChoosing(true)}
          onFreeText={() => setFreeTextOpen(true)}
          rows={load.rows}
          selection={load.selection}
          surveyHref={surveyHref}
          surveyId={surveyId}
          total={load.total}
        />
        <Modal
          description="Neue Antworten und spätere Änderungen erscheinen erst in einem neuen Antwortstand."
          onClose={() => {
            if (!busy) setChoosing(false);
          }}
          open={choosing}
          size="md"
          title="Antwortstand wählen"
        >
          {form}
        </Modal>
        <FreeTextDialog
          client={client}
          onClose={() => setFreeTextOpen(false)}
          open={freeTextOpen}
          selection={load.selection}
          surveyId={surveyId}
        />
      </>,
    );
  }

  return frame(
    false,
    <div className="svr-start">
      <header className="page-header">
        <div className="page-heading">
          <h1>Einzelantworten</h1>
        </div>
      </header>
      {load.kind === "loading" ? (
        <div role="status" aria-busy="true">
          <span className="sr-only">Antworten werden geladen …</span>
          <SkeletonRows rows={6} />
        </div>
      ) : load.kind === "error" ? (
        <div className="svr-blocked">
          <div className="callout tone-danger" role="alert">
            <span>
              Antworten konnten nicht geladen werden. Prüfen Sie die Verbindung
              und versuchen Sie es erneut.
            </span>
          </div>
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Erneut versuchen
          </Button>
        </div>
      ) : !versions.length ? (
        <EmptyState
          description="Veröffentlichen Sie zuerst einen Fragebogen. Danach lassen sich Antworten hier lesen."
          headingLevel={2}
          icon={ClipboardList}
          title="Noch keine Antworten"
        />
      ) : (
        <section aria-labelledby="svr-choose" className="svr-panel">
          <h2 id="svr-choose">Antwortstand wählen</h2>
          <p className="svr-lead">
            Wählen Sie einen festen Antwortstand. Neue Antworten und spätere
            Änderungen erscheinen erst in einer neuen Auswahl.
          </p>
          {notice ? (
            <div className="callout tone-warn" role="alert">
              <span>{notice}</span>
            </div>
          ) : null}
          {form}
        </section>
      )}
    </div>,
  );
}

function SelectionForm({
  versions,
  filter,
  onChange,
  canTest,
  busy,
  retry,
  error,
  onSubmit,
  onRetry,
  onDiscardRetry,
}: {
  versions: readonly { id: string; number: number }[];
  filter: SelectionFilter;
  onChange: (next: SelectionFilter) => void;
  canTest: boolean;
  busy: boolean;
  retry: boolean;
  error: string;
  onSubmit: () => void;
  onRetry: () => void;
  onDiscardRetry: () => void;
}) {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <form
      className="svr-form"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      {error ? (
        <div className="callout tone-danger" role="alert">
          <span>{error}</span>
        </div>
      ) : null}
      <fieldset className="svr-fields" disabled={busy || retry}>
        <legend className="sr-only">Antwortstand auswählen</legend>
        <Field label="Version der Einzelantworten">
          <select
            value={filter.version}
            onChange={(e) => onChange({ ...filter, version: e.target.value })}
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.number}
              </option>
            ))}
          </select>
        </Field>
        {canTest ? (
          <Field label="Antwortquelle">
            <select
              value={filter.isTest ? "test" : "real"}
              onChange={(e) =>
                onChange({ ...filter, isTest: e.target.value === "test" })
              }
            >
              <option value="real">Echte Teilnahmen</option>
              <option value="test">Nur Testteilnahmen</option>
            </select>
          </Field>
        ) : null}
        <fieldset className="svr-statuses">
          <legend className="field-label">Teilnahmestatus</legend>
          {RESPONSE_STATUSES.map((key) => (
            <label className="checkbox" key={key}>
              <input
                checked={filter.statuses.includes(key)}
                onChange={(e) =>
                  onChange({
                    ...filter,
                    statuses: e.target.checked
                      ? [...filter.statuses, key]
                      : filter.statuses.filter((s) => s !== key),
                  })
                }
                type="checkbox"
              />
              {responseStatusLabels[key]}
            </label>
          ))}
        </fieldset>
        <Field label="Begonnen ab">
          <input
            type="datetime-local"
            value={filter.from}
            onChange={(e) => onChange({ ...filter, from: e.target.value })}
          />
        </Field>
        <Field label="Begonnen vor">
          <input
            type="datetime-local"
            value={filter.before}
            onChange={(e) => onChange({ ...filter, before: e.target.value })}
          />
        </Field>
        <p className="field-hint svr-zone">
          Zeitzone: {zone}. Der Beginn zählt mit, der Endzeitpunkt nicht.
        </p>
      </fieldset>
      <div className="svr-form-actions">
        {retry ? (
          <>
            <Button disabled={busy} onClick={onRetry} variant="primary">
              Auswahl erneut anfordern
            </Button>
            <Button disabled={busy} onClick={onDiscardRetry} variant="ghost">
              Filter neu wählen
            </Button>
          </>
        ) : (
          <Button
            disabled={!filter.statuses.length || !filter.version}
            loading={busy}
            type="submit"
            variant="primary"
          >
            Antworten auswählen
          </Button>
        )}
      </div>
    </form>
  );
}

/* ---------------- list ---------------- */

function ResponseList({
  client,
  surveyId,
  surveyHref,
  selection,
  rows,
  total,
  onChoose,
  onFreeText,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  surveyHref: string;
  selection: ResponseSelection;
  rows: readonly ResponseRow[];
  total: number;
  onChoose: () => void;
  onFreeText: () => void;
}) {
  const hasFreeText = selection.questions.some((q) => TEXT_KINDS.has(q.kind));
  // The selection is frozen, so a loaded answer stays valid while it is open.
  const answers = useRef(new Map<string, IndividualResponse>());
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  useContextCommands(
    useMemo(
      () => [
        {
          id: "surveys:responses:choose",
          label: "Antwortstand wählen",
          group: "Einzelantworten",
          icon: SlidersHorizontal,
          run: onChoose,
        },
        ...(hasFreeText
          ? [
              {
                id: "surveys:responses:free-text",
                label: "Freitextantworten ansehen",
                group: "Einzelantworten",
                icon: MessageSquareText,
                run: onFreeText,
              },
            ]
          : []),
        {
          id: "surveys:responses:survey",
          label: "Zur Umfrage",
          group: "Einzelantworten",
          icon: Undo2,
          run: () => window.location.assign(surveyHref),
        },
      ],
      [hasFreeText, onChoose, onFreeText, surveyHref],
    ),
  );

  // Status is a fact of the participation: read-only, no letter key.
  const properties = useMemo<ListProperty<ResponseRow>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: RESPONSE_STATUSES.map((value) => ({
          value,
          label: responseStatusLabels[value],
          icon: (
            <StatusIcon
              label={responseStatusLabels[value]}
              status={statusShape[responseStatusLabels[value]] ?? "open"}
            />
          ),
        })),
        chip: (row) => (
          <StatusLabel status={responseStatusLabels[row.status]} />
        ),
      },
    ],
    [],
  );
  const sorts = useMemo<ListSort<ResponseRow>[]>(
    () => [
      {
        id: "number",
        label: "Reihenfolge",
        compare: (a, b) => a.number - b.number,
      },
      {
        id: "newest",
        label: "Neueste zuerst",
        compare: (a, b) => b.createdAt.localeCompare(a.createdAt),
      },
      {
        id: "oldest",
        label: "Älteste zuerst",
        compare: (a, b) => a.createdAt.localeCompare(b.createdAt),
      },
    ],
    [],
  );
  const views = useMemo<ListViewDefinition[]>(
    () => [
      { id: "all", label: "Alle", filters: [], groupBy: null, sort: "number" },
      {
        id: "completed",
        label: "Abgeschlossen",
        filters: [{ prop: "status", values: ["completed"] }],
        groupBy: null,
        sort: "number",
      },
      {
        id: "incomplete",
        label: "Unvollständig",
        filters: [{ prop: "status", values: ["partial", "in_progress"] }],
        groupBy: "status",
        sort: "number",
      },
    ],
    [],
  );
  const columns = useMemo<ListColumns<ResponseRow>>(() => {
    const now = new Date();
    return {
      primary: (row) => (
        <span data-response-row={row.participationId}>
          Antwort <span className="mono">{row.number}</span>
        </span>
      ),
      trailing: (row) => (
        <time dateTime={row.createdAt}>
          {receivedLabel(row.createdAt, now)}
        </time>
      ),
    };
  }, []);
  const getId = useCallback((row: ResponseRow) => row.participationId, []);
  const searchText = useCallback(
    (row: ResponseRow) =>
      `Antwort ${row.number} ${responseStatusLabels[row.status]} ${dateTime(row.createdAt)}`,
    [],
  );
  const detailTitle = useCallback(
    (row: ResponseRow) => `Antwort ${row.number}`,
    [],
  );
  const renderDetail = useCallback(
    (row: ResponseRow) => (
      <ResponseDetail
        cache={answers.current}
        client={client}
        key={row.participationId}
        row={row}
        selection={selection}
        surveyId={surveyId}
      />
    ),
    [client, selection, surveyId],
  );

  const { filter } = selection;
  const applied = (
    <p className="svr-applied" role="status">
      Antwortstand: Version {selection.versionNumber} ·{" "}
      {filter.statuses.map((s) => responseStatusLabels[s]).join(", ")} ·{" "}
      {filter.isTest ? "Testteilnahmen" : "Echte Teilnahmen"} ·{" "}
      {selection.total} Teilnahmen. Stand vom{" "}
      {new Date(selection.createdAt).toLocaleString("de-DE")} ({zone}).
      Zeitraum:{" "}
      {filter.createdFrom
        ? `ab ${new Date(filter.createdFrom).toLocaleString("de-DE")}`
        : "offener Beginn"}{" "}
      {filter.createdBefore
        ? `bis vor ${new Date(filter.createdBefore).toLocaleString("de-DE")}`
        : "bis offenes Ende"}
      .
    </p>
  );

  return (
    <ListView<ResponseRow>
      beforeList={
        <>
          {applied}
          {rows.length < total ? (
            <div className="callout tone-warn">
              <span>
                Angezeigt werden die ersten {rows.length} von {total}{" "}
                Teilnahmen. Grenzen Sie den Antwortstand über den Zeitraum ein,
                um die übrigen zu lesen.
              </span>
            </div>
          ) : null}
        </>
      }
      className="svr-list"
      columns={columns}
      detailTitle={detailTitle}
      emptyIcon={ClipboardList}
      entityLabel={{ one: "Antwort", many: "Antworten" }}
      getId={getId}
      headerExtra={
        <>
          {hasFreeText ? (
            <Button
              icon={MessageSquareText}
              onClick={onFreeText}
              variant="ghost"
            >
              Freitexte
            </Button>
          ) : null}
          <Button
            icon={SlidersHorizontal}
            onClick={onChoose}
            variant="secondary"
          >
            Antwortstand wählen
          </Button>
        </>
      }
      id="survey-responses"
      properties={properties}
      renderDetail={renderDetail}
      rows={rows}
      searchText={searchText}
      sorts={sorts}
      title="Einzelantworten"
      useCommands={useContextCommands}
      views={views}
    />
  );
}

function ResponseDetail({
  client,
  surveyId,
  selection,
  row,
  cache,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  selection: ResponseSelection;
  row: ResponseRow;
  cache: Map<string, IndividualResponse>;
}) {
  const [detail, setDetail] = useState<IndividualResponse | null>(
    () => cache.get(row.participationId) ?? null,
  );
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (detail) return;
    const controller = new AbortController();
    setError("");
    client
      .getSurveyResponse(surveyId, selection.id, row.participationId, {
        signal: controller.signal,
      })
      .then((value) => {
        if (controller.signal.aborted) return;
        cache.set(row.participationId, value);
        setDetail(value);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(
          readError(
            cause,
            "Die Anfrage konnte nicht bestätigt werden. Bitte versuchen Sie es erneut.",
          ),
        );
      });
    return () => controller.abort();
  }, [
    cache,
    client,
    detail,
    surveyId,
    selection.id,
    row.participationId,
    attempt,
  ]);

  const status = detail?.status ?? row.status;
  return (
    <div
      className="svr-detail"
      aria-busy={!detail && !error ? true : undefined}
    >
      <DetailSection title="Teilnahme">
        <DetailProps
          items={[
            {
              label: "Status",
              value: <StatusLabel status={responseStatusLabels[status]} />,
            },
            {
              label: "Begonnen",
              value: dateTime(detail?.createdAt ?? row.createdAt),
            },
          ]}
        />
      </DetailSection>
      <DetailSection title="Antworten">
        {error ? (
          <div className="svr-detail-error">
            <div className="callout tone-danger" role="alert">
              <span>{error}</span>
            </div>
            <Button
              onClick={() => setAttempt((n) => n + 1)}
              size="sm"
              variant="secondary"
            >
              Erneut laden
            </Button>
          </div>
        ) : detail ? (
          <dl aria-label="Antworten" className="svr-answers">
            {selection.questions.map((question) => (
              <div key={question.id}>
                <dt>{question.title}</dt>
                <dd>{answerText(detail.answers[question.id], question)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="svr-muted" role="status">
            Antwort wird geladen …
          </p>
        )}
      </DetailSection>
    </div>
  );
}

/* ---------------- free text ---------------- */

/** Opens a response in the list pane (pushes `?open=`; Back closes it). */
function openInPane(participationId: string) {
  const url = new URL(window.location.href);
  url.searchParams.set("open", participationId);
  history.pushState(history.state, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function FreeTextDialog({
  client,
  surveyId,
  selection,
  open,
  onClose,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  selection: ResponseSelection;
  open: boolean;
  onClose: () => void;
}) {
  const questions = selection.questions.filter((q) => TEXT_KINDS.has(q.kind));
  const [questionId, setQuestionId] = useState(questions[0]?.id ?? "");
  const [offset, setOffset] = useState(0);
  const [texts, setTexts] = useState<FreeTextItems | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!open || !questionId) return;
    const controller = new AbortController();
    setError("");
    setTexts(null);
    client
      .listSurveyFreeText(
        surveyId,
        selection.id,
        questionId,
        offset ? { offset } : {},
        { signal: controller.signal },
      )
      .then((value) => {
        if (!controller.signal.aborted) setTexts(value);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(
          readError(
            cause,
            "Freitexte konnten nicht geladen werden. Bitte versuchen Sie es erneut.",
          ),
        );
      });
    return () => controller.abort();
  }, [client, surveyId, selection.id, questionId, offset, open, attempt]);

  return (
    <Modal
      className="svr-freetext"
      footer={
        texts && texts.total > PAGE_SIZE ? (
          <nav aria-label="Freitextseiten" className="svr-pages">
            <Button
              disabled={texts.offset === 0}
              onClick={() => setOffset(Math.max(0, texts.offset - PAGE_SIZE))}
              variant="ghost"
            >
              Vorherige Freitexte
            </Button>
            <Button
              disabled={texts.offset + texts.items.length >= texts.total}
              onClick={() => setOffset(texts.offset + PAGE_SIZE)}
              variant="secondary"
            >
              Weitere Freitexte
            </Button>
          </nav>
        ) : undefined
      }
      onClose={onClose}
      open={open}
      size="lg"
      title="Freitextantworten"
    >
      <div className="svr-freetext-body">
        {questions.length > 1 ? (
          <Field label="Freitextfrage">
            <select
              value={questionId}
              onChange={(e) => {
                setQuestionId(e.target.value);
                setOffset(0);
              }}
            >
              {questions.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.title}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <p className="svr-question">{questions[0]?.title}</p>
        )}
        {error ? (
          <div className="svr-detail-error">
            <div className="callout tone-danger" role="alert">
              <span>{error}</span>
            </div>
            <Button
              onClick={() => setAttempt((n) => n + 1)}
              size="sm"
              variant="secondary"
            >
              Erneut laden
            </Button>
          </div>
        ) : !texts ? (
          <p className="svr-muted" role="status">
            Freitexte werden geladen …
          </p>
        ) : (
          <>
            <p className="svr-muted" role="status">
              {texts.total} Freitextantworten
            </p>
            {texts.items.length ? (
              <ol className="answer-texts" start={texts.offset + 1}>
                {texts.items.map((item) => (
                  <li key={item.participationId}>
                    <p>„{item.text}“</p>
                    <Button
                      onClick={() => {
                        onClose();
                        openInPane(item.participationId);
                      }}
                      size="sm"
                      variant="ghost"
                    >
                      Zugehörige Einzelantwort ansehen
                    </Button>
                  </li>
                ))}
              </ol>
            ) : (
              <p>Keine Freitextantworten für diese Auswahl.</p>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
