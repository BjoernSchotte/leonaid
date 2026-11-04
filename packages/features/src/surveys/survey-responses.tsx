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
  type AnalysisSnapshot,
  type CreateAnalysisSnapshot,
  type FreeTextItems,
  type IndividualResponse,
  type LeonAidApiClient,
  type ResponseItem,
  type ResponseQuestion,
  type ResolvedAnalysisFilter,
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
import { SurveySummary } from "./survey-summary";
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
const CHOICE_KINDS = new Set([
  "radiogroup",
  "dropdown",
  "checkbox",
  "rating",
  "matrix",
]);

/** The chosen option labels of a row, question by question ("A · B"). */
export function answerSummary(
  row: Pick<ResponseItem, "choiceAnswers">,
  questions: readonly Pick<ResponseQuestion, "id">[],
  limit = Infinity,
): string {
  if (!row.choiceAnswers) return "";
  return questions
    .map((q) => row.choiceAnswers?.[q.id]?.join(", "))
    .filter((text): text is string => Boolean(text))
    .slice(0, limit)
    .join(" · ");
}
/** Free text is paged by 50 on the server. */
const PAGE_SIZE = 50;
/*
 * Response summaries (no answers) come in pages of up to 5000. The server
 * caps a selection at 5000 participations, so one request is the whole
 * selection; the loop and the offset bound are guards for a changed cap.
 */
const SUMMARY_PAGE = 5000;
/*
 * Rows rendered at once. Measured on 5000 rows: rendering all of them makes
 * j, x and a view switch take 200–450 ms; search, filters and sorts still
 * cover every row (task 5.6 fix 1).
 */
const RENDER_LIMIT = 500;
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

/* One formatter: toLocaleString builds a new one per call (slow for 5000 rows). */
const dateTimeFormat = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});
const dateTime = (value: string) => dateTimeFormat.format(new Date(value));
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

/** A date or datetime-local value as an instant: a bare day means 00:00 local. */
function localInstant(value: string): string {
  return new Date(value.length === 10 ? `${value}T00:00` : value).toISOString();
}

/** ApiError text with support code; a read-specific fallback otherwise. */
function readError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError
    ? actionErrorMessage(cause).message
    : fallback;
}

export interface LoadProgress {
  readonly loaded: number;
  readonly total: number;
}

/** Loads the summaries of a selection the server lets this account read. */
export async function loadRows(
  client: LeonAidApiClient,
  surveyId: string,
  snapshotId: string,
  signal: AbortSignal,
  onProgress?: (progress: LoadProgress) => void,
): Promise<{ rows: ResponseRow[]; total: number }> {
  const rows: ResponseRow[] = [];
  let offset = 0;
  let total = 0;
  for (;;) {
    const page = await client.listSurveyResponses(
      surveyId,
      snapshotId,
      // fields=choice: option labels of choice, rating and matrix answers
      // (never free text), the prototype's answer columns.
      offset
        ? { offset, limit: SUMMARY_PAGE, fields: "choice" }
        : { limit: SUMMARY_PAGE, fields: "choice" },
      { signal },
    );
    total = page.total;
    page.items.forEach((item, index) =>
      rows.push({ ...item, number: page.offset + index + 1 }),
    );
    offset = page.offset + page.items.length;
    onProgress?.({ loaded: rows.length, total });
    if (!page.items.length || offset >= total || offset > MAX_OFFSET) break;
  }
  return { rows, total };
}

function progressText(progress: LoadProgress | null): string {
  if (!progress) return "Antworten werden geladen …";
  return progress.loaded
    ? `${progress.loaded} von ${progress.total} Antworten geladen …`
    : `${progress.total} Antworten werden geladen …`;
}

/** Old `?response=` links open the response through `?open=`; runs once, before the list reads the URL. */
function useLegacyResponseParam() {
  useState(() => {
    const next = migrateLegacyResponseParam(window.location.search);
    if (next !== window.location.search)
      history.replaceState(
        history.state,
        "",
        `${window.location.pathname}${next}${window.location.hash}`,
      );
    return null;
  });
}

/* ---------------- page ---------------- */

/** "list": the individual responses; "summary": the evaluation (charts). */
export type ResponsesSection = "list" | "summary";

export function SurveyResponsesPage({
  client,
  surveyId,
  section = "list",
}: {
  client: LeonAidApiClient;
  surveyId: string;
  section?: ResponsesSection;
}) {
  const [summary, setSummary] = useState<SurveySummaryResponse | null>(null);
  const [failure, setFailure] = useState<{
    readonly message: string;
    readonly transient: boolean;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setFailure(null);
    client
      .getSurvey(surveyId, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setSummary(value);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setFailure({
          message: readError(
            cause,
            "Die Umfrage konnte nicht geladen werden. Prüfen Sie die Verbindung und versuchen Sie es erneut.",
          ),
          // A refusal (e.g. 404) does not change on retry.
          transient: !(cause instanceof ApiError) || cause.status >= 500,
        });
      });
    return () => controller.abort();
  }, [client, surveyId, attempt]);

  const allowed = (capability: string) =>
    summary?.capabilities?.includes(capability) ?? false;
  const readable = summary !== null && summary.status !== "deleted";
  const surveyHref = `/admin/surveys/${encodeURIComponent(surveyId)}`;
  const title = summary?.title ?? "Umfrage";
  const reader = allowed("read_responses");
  // Charts: view_aggregates OR read_responses (Björn, 2026-11-04).
  const mayEnter =
    readable &&
    (section === "list" ? reader : reader || allowed("view_aggregates"));
  const sectionLabel = section === "list" ? "Einzelantworten" : "Auswertung";
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
            <span aria-current="page">{sectionLabel}</span>
          </nav>
          {reader && summary ? (
            <SectionLinks section={section} surveyId={surveyId} />
          ) : null}
        </div>
        {children}
      </div>
    ),
    [surveyHref, title, sectionLabel, reader, summary, section, surveyId],
  );

  let content;
  if (failure) {
    content = (
      <div className="svr-blocked">
        <div className="callout tone-danger" role="alert">
          <span>{failure.message}</span>
        </div>
        {failure.transient ? (
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Erneut versuchen
          </Button>
        ) : (
          <a href="/admin/surveys">Zu allen Umfragen</a>
        )}
      </div>
    );
  } else if (!summary) {
    content = (
      <div className="svr-blocked" role="status" aria-busy="true">
        <span className="sr-only">Antworten werden geladen …</span>
        <SkeletonRows rows={6} />
      </div>
    );
  } else if (!mayEnter) {
    content = (
      <div className="svr-blocked">
        <div className="callout tone-warn" role="alert">
          <span>
            {new URLSearchParams(window.location.search).has(
              "responseSelection",
            )
              ? "Dieser Antwortstand ist für Sie nicht zugänglich."
              : section === "list"
                ? "Die Einzelantworten dieser Umfrage sind für Sie nicht zugänglich."
                : "Die Auswertung dieser Umfrage ist für Sie nicht zugänglich."}
          </span>
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
        key={section}
        mode={reader ? "reader" : "aggregates"}
        section={section}
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

/** `/admin/surveys/<id>/responses[/summary]`, keeping the selection. */
export function responsesSectionHref(
  surveyId: string,
  section: ResponsesSection,
  search = window.location.search,
): string {
  const selection = new URLSearchParams(search).get("responseSelection");
  const base = `/admin/surveys/${encodeURIComponent(surveyId)}/responses${section === "summary" ? "/summary" : ""}`;
  return selection
    ? `${base}?responseSelection=${encodeURIComponent(selection)}`
    : base;
}

/** The prototype's subnav (shared `.section-links`), readers only. */
function SectionLinks({
  section,
  surveyId,
}: {
  section: ResponsesSection;
  surveyId: string;
}) {
  return (
    <nav aria-label="Antworten" className="section-links svr-sections">
      {(
        [
          ["list", "Einzelantworten"],
          ["summary", "Auswertung"],
        ] as const
      ).map(([target, label]) => (
        <a
          aria-current={target === section ? "page" : undefined}
          href={responsesSectionHref(surveyId, target)}
          key={target}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

/** The frozen selection in one line (both sections). */
export function AppliedSelection({ info }: { info: SelectionInfo }) {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const { filter } = info;
  return (
    <p className="svr-applied" role="status">
      Antwortstand: Version {info.versionNumber} ·{" "}
      {filter.statuses.map((s) => responseStatusLabels[s]).join(", ")} ·{" "}
      {filter.isTest ? "Testteilnahmen" : "Echte Teilnahmen"} · {info.total}{" "}
      Teilnahmen. Stand vom {new Date(info.createdAt).toLocaleString("de-DE")} (
      {zone}). Zeitraum:{" "}
      {filter.createdFrom
        ? `ab ${new Date(filter.createdFrom).toLocaleString("de-DE")}`
        : "offener Beginn"}{" "}
      {filter.createdBefore
        ? `bis vor ${new Date(filter.createdBefore).toLocaleString("de-DE")}`
        : "bis offenes Ende"}
      .
    </p>
  );
}

/* ---------------- selection ---------------- */

/** What the applied-selection line needs, from either kind of snapshot. */
export interface SelectionInfo {
  readonly id: string;
  readonly createdAt: string;
  readonly versionNumber: number;
  readonly filter: ResolvedAnalysisFilter;
  readonly total: number;
}

interface Loaded {
  readonly info: SelectionInfo;
  /** Readers: questions for the pane and free text. */
  readonly selection: ResponseSelection | null;
  /** List section. */
  readonly rows: readonly ResponseRow[];
  readonly total: number;
  /** Summary section: the disclosed aggregates (k = 5). */
  readonly aggregates: AnalysisSnapshot | null;
}

interface Source {
  versions(
    signal: AbortSignal,
  ): Promise<{ items: { id: string; number: number }[] }>;
  /** The selection's metadata; a 4xx here means "choose a new one". */
  meta(id: string, signal: AbortSignal): Promise<Loaded>;
  create(body: CreateAnalysisSnapshot, signal: AbortSignal): Promise<Loaded>;
  /** The rest of a loaded selection (rows or aggregates). */
  fill(
    loaded: Loaded,
    signal: AbortSignal,
    onProgress: (progress: LoadProgress) => void,
  ): Promise<Loaded>;
}

const infoOf = (
  value: ResponseSelection | AnalysisSnapshot,
): SelectionInfo => ({
  id: value.id,
  createdAt: value.createdAt,
  versionNumber: value.versionNumber,
  filter: value.filter,
  total: "total" in value ? value.total : value.participationCount,
});

const fromSelection = (selection: ResponseSelection): Loaded => ({
  info: infoOf(selection),
  selection,
  rows: [],
  total: selection.total,
  aggregates: null,
});

/**
 * Readers use the response-selection endpoints (read_responses); an
 * aggregate-only account uses the analysis endpoints (view_aggregates).
 * The server checks both; aggregates are disclosed with k = 5 either way.
 */
function sourceFor(
  client: LeonAidApiClient,
  surveyId: string,
  mode: "reader" | "aggregates",
  section: ResponsesSection,
): Source {
  if (mode === "aggregates") {
    const loaded = (snapshot: AnalysisSnapshot): Loaded => ({
      info: infoOf(snapshot),
      selection: null,
      rows: [],
      total: snapshot.participationCount,
      aggregates: snapshot,
    });
    return {
      versions: (signal) =>
        client.listSurveyAnalysisVersions(surveyId, { signal }),
      meta: async (id, signal) =>
        loaded(await client.getSurveyAnalysis(surveyId, id, { signal })),
      create: async (body, signal) =>
        loaded(await client.createSurveyAnalysis(surveyId, body, { signal })),
      fill: async (value) => value,
    };
  }
  return {
    versions: (signal) =>
      client.listSurveyResponseVersions(surveyId, { signal }),
    meta: async (id, signal) =>
      fromSelection(
        await client.getSurveyResponseSelection(surveyId, id, { signal }),
      ),
    create: async (body, signal) =>
      fromSelection(
        await client.createSurveyResponseSelection(surveyId, body, { signal }),
      ),
    fill: async (value, signal, onProgress) => {
      if (section === "summary") {
        return {
          ...value,
          aggregates: await client.getSurveyResponseAggregates(
            surveyId,
            value.info.id,
            { signal },
          ),
        };
      }
      onProgress({ loaded: 0, total: value.info.total });
      const { rows, total } = await loadRows(
        client,
        surveyId,
        value.info.id,
        signal,
        onProgress,
      );
      return { ...value, rows, total };
    },
  };
}

interface SelectionFilter {
  readonly version: string;
  readonly statuses: readonly ResponseStatus[];
  readonly from: string;
  readonly before: string;
  readonly isTest: boolean;
}

type LoadState =
  | { readonly kind: "loading"; readonly progress: LoadProgress | null }
  | { readonly kind: "none" }
  | { readonly kind: "error" }
  | { readonly kind: "ready"; readonly data: Loaded };

function SurveyResponses({
  client,
  surveyId,
  surveyHref,
  canTest,
  frame,
  mode,
  section,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  surveyHref: string;
  canTest: boolean;
  frame: PageFrame;
  mode: "reader" | "aggregates";
  section: ResponsesSection;
}) {
  const source = useMemo(
    () => sourceFor(client, surveyId, mode, section),
    [client, surveyId, mode, section],
  );
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
  const [load, setLoad] = useState<LoadState>({
    kind: "loading",
    progress: null,
  });
  /* Rows of a new selection while they load (shown in the form). */
  const [creating, setCreating] = useState<LoadProgress | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");
  const [choosing, setChoosing] = useState(false);
  // ?freeText=<questionId> (from the evaluation's quote panel) opens the
  // free-text dialog on that question.
  const [freeTextQuestion] = useState(() =>
    new URLSearchParams(window.location.search).get("freeText"),
  );
  const [freeTextOpen, setFreeTextOpen] = useState(Boolean(freeTextQuestion));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(false);
  const running = useRef(false);
  const pending = useRef<CreateAnalysisSnapshot | null>(null);
  const mounted = useRef(true);
  /* Aborts a running create() when the page goes away. */
  const createAbort = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      mounted.current = false;
      createAbort.current?.abort();
    },
    [],
  );
  useLegacyResponseParam();

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoad({ kind: "loading", progress: null });
    setNotice("");
    void (async () => {
      try {
        const value = await source.versions(signal);
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
        let loaded: Loaded;
        try {
          loaded = await source.meta(snapshotId, signal);
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
        const data = await source.fill(loaded, signal, (progress) => {
          if (!signal.aborted) setLoad({ kind: "loading", progress });
        });
        if (signal.aborted) return;
        const { filter: applied } = data.info;
        setFilter({
          version: applied.versionId,
          statuses: applied.statuses,
          from: localInput(applied.createdFrom),
          before: localInput(applied.createdBefore),
          isTest: applied.isTest,
        });
        setLoad({ kind: "ready", data });
      } catch {
        if (!signal.aborted) setLoad({ kind: "error" });
      }
    })();
    return () => controller.abort();
  }, [source, attempt]);

  async function create(repeat = false) {
    if (running.current) return;
    if (!repeat) {
      const createdFrom = filter.from ? localInstant(filter.from) : null;
      const createdBefore = filter.before ? localInstant(filter.before) : null;
      if (createdFrom && createdBefore && createdFrom >= createdBefore) {
        setError("Das Ende des Zeitraums muss nach seinem Beginn liegen.");
        return;
      }
      pending.current = {
        operationId: crypto.randomUUID(),
        filter: {
          versionId: filter.version,
          // Without raw access the server counts completed ones only.
          statuses:
            mode === "aggregates" ? ["completed"] : [...filter.statuses],
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
    const controller = new AbortController();
    createAbort.current = controller;
    const { signal } = controller;
    try {
      // Same operation id after an uncertain acknowledgement: the server
      // returns the selection it already stored.
      const created = await source.create(pending.current, signal);
      setCreating({ loaded: 0, total: created.info.total });
      const data = await source.fill(created, signal, (progress) => {
        if (!signal.aborted) setCreating(progress);
      });
      if (!mounted.current) return;
      const url = new URL(window.location.href);
      url.searchParams.set("responseSelection", data.info.id);
      url.searchParams.delete("open");
      history.replaceState(history.state, "", url);
      pending.current = null;
      setRetry(false);
      setNotice("");
      setChoosing(false);
      setLoad({ kind: "ready", data });
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
        // A refused selection leaves nothing readable on screen, and a
        // reload must not bring the old one back.
        pending.current = null;
        const url = new URL(window.location.href);
        url.searchParams.delete("responseSelection");
        url.searchParams.delete("open");
        history.replaceState(history.state, "", url);
        setLoad({ kind: "none" });
      }
    } finally {
      running.current = false;
      if (createAbort.current === controller) createAbort.current = null;
      if (mounted.current) {
        setBusy(false);
        setCreating(null);
      }
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
      progress={creating}
      daysOnly={mode === "aggregates"}
      rangeHint={
        mode === "aggregates"
          ? "Ohne Leserecht zählen ganze Tage (Europe/Berlin) bis einschließlich gestern und nur abgeschlossene Teilnahmen, damit niemand einzeln erkennbar wird."
          : undefined
      }
      retry={retry}
      versions={versions}
    />
  );

  const chooser = (
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
  );

  if (load.kind === "ready" && section === "summary" && load.data.aggregates) {
    return frame(
      false,
      <>
        <SurveySummary
          aggregates={load.data.aggregates}
          applied={<AppliedSelection info={load.data.info} />}
          client={client}
          key={load.data.info.id}
          onChoose={() => setChoosing(true)}
          selection={load.data.selection}
          surveyId={surveyId}
        />
        {chooser}
      </>,
    );
  }

  if (load.kind === "ready" && load.data.selection) {
    const { data } = load;
    const selection = data.selection!;
    return frame(
      true,
      <>
        <ResponseList
          client={client}
          key={data.info.id}
          onChoose={() => setChoosing(true)}
          onFreeText={() => setFreeTextOpen(true)}
          rows={data.rows}
          selection={selection}
          surveyHref={surveyHref}
          surveyId={surveyId}
          total={data.total}
        />
        {chooser}
        <FreeTextDialog
          client={client}
          initialQuestion={freeTextQuestion}
          onClose={() => {
            setFreeTextOpen(false);
            const url = new URL(window.location.href);
            if (url.searchParams.has("freeText")) {
              url.searchParams.delete("freeText");
              history.replaceState(history.state, "", url);
            }
          }}
          open={freeTextOpen}
          selection={selection}
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
          <h1>{section === "list" ? "Einzelantworten" : "Auswertung"}</h1>
        </div>
      </header>
      {load.kind === "loading" ? (
        <div aria-busy="true" className="svr-loading">
          <p className="svr-progress" role="status">
            {progressText(load.progress)}
          </p>
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
  progress,
  rangeHint,
  daysOnly = false,
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
  progress: LoadProgress | null;
  rangeHint?: string;
  /** Accounts without raw access pick whole days (the server snaps anyway). */
  daysOnly?: boolean;
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
        {daysOnly ? (
          <p className="field-hint svr-zone">
            Teilnahmestatus: nur abgeschlossene Teilnahmen, die vor dem Ende des
            Zeitraums abgeschlossen wurden.
          </p>
        ) : (
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
        )}
        <Field label="Begonnen ab">
          <input
            type={daysOnly ? "date" : "datetime-local"}
            value={daysOnly ? filter.from.slice(0, 10) : filter.from}
            onChange={(e) => onChange({ ...filter, from: e.target.value })}
          />
        </Field>
        <Field label="Begonnen vor">
          <input
            type={daysOnly ? "date" : "datetime-local"}
            value={daysOnly ? filter.before.slice(0, 10) : filter.before}
            onChange={(e) => onChange({ ...filter, before: e.target.value })}
          />
        </Field>
        <p className="field-hint svr-zone">
          Zeitzone: {zone}. Der Beginn zählt mit, der Endzeitpunkt nicht.
          {rangeHint ? ` ${rangeHint}` : null}
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
        {progress ? (
          <span className="svr-progress" role="status">
            {progressText(progress)}
          </span>
        ) : null}
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
  /** Questions whose chosen options show in the row (answer columns). */
  const choiceQuestions = useMemo(
    () => selection.questions.filter((q) => CHOICE_KINDS.has(q.kind)),
    [selection],
  );

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
      secondary: (row) => answerSummary(row, choiceQuestions, 3),
      trailing: (row) => (
        <time dateTime={row.createdAt}>
          {receivedLabel(row.createdAt, now)}
        </time>
      ),
    };
  }, [choiceQuestions]);
  const getId = useCallback((row: ResponseRow) => row.participationId, []);
  // Built once per selection, not per keystroke and row.
  const searchIndex = useMemo(
    () =>
      new Map(
        rows.map((row) => [
          row.participationId,
          `Antwort ${row.number} ${responseStatusLabels[row.status]} ${dateTime(row.createdAt)} ${answerSummary(row, choiceQuestions)}`,
        ]),
      ),
    [rows, choiceQuestions],
  );
  const searchText = useCallback(
    (row: ResponseRow) => searchIndex.get(row.participationId) ?? "",
    [searchIndex],
  );
  const detailTitle = useCallback(
    (row: ResponseRow) => `Antwort ${row.number}`,
    [],
  );
  const renderDetail = useCallback(
    (row: ResponseRow) => (
      <ResponseDetail
        client={client}
        key={row.participationId}
        row={row}
        selection={selection}
        surveyId={surveyId}
      />
    ),
    [client, selection, surveyId],
  );

  const applied = <AppliedSelection info={infoOf(selection)} />;

  return (
    <ListView<ResponseRow>
      beforeList={
        <>
          {applied}
          {/* Guard only: the server caps a selection at 5000 participations,
              which loadRows always reaches. It shows if that cap changes. */}
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
      renderLimit={RENDER_LIMIT}
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
}: {
  client: LeonAidApiClient;
  surveyId: string;
  selection: ResponseSelection;
  row: ResponseRow;
}) {
  // Only the open response is held; reopening one fetches it again.
  const [detail, setDetail] = useState<IndividualResponse | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    client
      .getSurveyResponse(surveyId, selection.id, row.participationId, {
        signal: controller.signal,
      })
      .then((value) => {
        if (!controller.signal.aborted) setDetail(value);
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
  }, [client, surveyId, selection.id, row.participationId, attempt]);

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
  initialQuestion,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  selection: ResponseSelection;
  open: boolean;
  onClose: () => void;
  initialQuestion?: string | null;
}) {
  const questions = selection.questions.filter((q) => TEXT_KINDS.has(q.kind));
  const [questionId, setQuestionId] = useState(
    questions.find((q) => q.id === initialQuestion)?.id ??
      questions[0]?.id ??
      "",
  );
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
