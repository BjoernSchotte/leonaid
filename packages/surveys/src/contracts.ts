/** Host-neutral SurveyJS module contracts. Own license decision remains UNDEFINED. */
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type SurveyDefinition = { [key: string]: JsonValue };
export type SurveyStatus =
  | "draft"
  | "active"
  | "ended"
  | "archived"
  | "deleted";
export type ResponseStatus = "in_progress" | "partial" | "completed";
export type AccessMode = "anonymous" | "invitation";
export type SurveyCapability =
  | "design"
  | "publish"
  | "archive"
  | "view_aggregates"
  | "read_responses"
  | "export_raw"
  | "export_reports"
  | "manage_invitations"
  | "delete";

export interface Survey {
  id: string;
  title: string;
  status: SurveyStatus;
  revision: number;
  actionId: string | null;
  accessMode: AccessMode;
  inactivityTimeoutSeconds: number | null;
  publishedVersionId: string | null;
}
export interface Draft {
  surveyId: string;
  revision: number;
  definition: SurveyDefinition;
}
export interface PublishedVersion {
  id: string;
  surveyId: string;
  number: number;
  definition: SurveyDefinition;
  rendererVersion: string;
  capabilityProfile: string;
  publishedAt: string;
}
export interface Diagnostic {
  path: string;
  code: string;
  message: string;
  severity: "error" | "warning" | "information";
}
/** Intermediate answer data is not synonymous with a valid completed response. */
export interface ResponseSnapshot {
  participationId: string;
  versionId: string;
  revision: number;
  status: ResponseStatus;
  answers: Record<string, JsonValue>;
  currentPage: string | null;
  lastAnswerChangedAt: string | null;
  completedAt: string | null;
  diagnostics: Diagnostic[];
}
export interface Participation {
  id: string;
  version: PublishedVersion;
  response: ResponseSnapshot;
  inactivityTimeoutSeconds: number;
}
/** A stable operation ID is reused on retries; expectedRevision prevents lost updates. */
export interface Mutation {
  operationId: string;
  expectedRevision: number;
}
export interface SaveResponse extends Mutation {
  answers: Record<string, JsonValue>;
  currentPage: string | null;
}
export interface SaveDraft extends Mutation {
  definition: SurveyDefinition;
}
export type ErrorCode =
  | "unauthenticated"
  | "forbidden"
  | "not_found"
  | "closed"
  | "access_expired"
  | "revision_conflict"
  | "idempotency_conflict"
  | "invalid_definition"
  | "invalid_response"
  | "unsupported_capability"
  | "limit_exceeded"
  | "temporarily_unavailable";
export interface SurveyError {
  code: ErrorCode;
  message: string;
  diagnostics: Diagnostic[];
  currentRevision?: number;
  retryAfterSeconds?: number;
}
export type Result<T> =
  | { ok: true; value: T }
  | { ok: false; error: SurveyError };
export interface RequestOptions {
  signal?: AbortSignal;
}
/** The host manages session credentials; definitions and answers never contain them. */
export interface ParticipationAdapter {
  start(
    surveyId: string,
    operationId: string,
    options?: RequestOptions,
  ): Promise<Result<Participation>>;
  restore(
    participationId: string,
    options?: RequestOptions,
  ): Promise<Result<Participation>>;
  save(
    participationId: string,
    input: SaveResponse,
    options?: RequestOptions,
  ): Promise<Result<ResponseSnapshot>>;
  complete(
    participationId: string,
    input: Mutation,
    options?: RequestOptions,
  ): Promise<Result<ResponseSnapshot>>;
}
export interface AuthoringAdapter {
  loadDraft(surveyId: string, options?: RequestOptions): Promise<Result<Draft>>;
  saveDraft(
    surveyId: string,
    input: SaveDraft,
    options?: RequestOptions,
  ): Promise<Result<Draft>>;
  publish(
    surveyId: string,
    input: Mutation,
    options?: RequestOptions,
  ): Promise<Result<PublishedVersion>>;
}
export interface AnalysisFilter {
  versionId: string;
  statuses: ResponseStatus[];
}
export interface QuestionAggregate {
  questionId: string;
  relevant: number;
  answered: number;
  unanswered: number;
  hidden: number;
  invalid: number;
  counts: { value: JsonValue; count: number }[];
  mean: number | null;
  nps: number | null;
}
/** Frozen snapshot IDs bind UI and all exports to the same result set. */
export interface AnalysisSnapshot {
  id: string;
  surveyId: string;
  createdAt: string;
  filter: AnalysisFilter;
  participationCount: number;
  questions: QuestionAggregate[];
}
export type ExportProduct =
  | "responses_csv"
  | "responses_xlsx"
  | "analysis_xlsx"
  | "analysis_pdf";
export interface ExportJob {
  id: string;
  snapshotId: string;
  product: ExportProduct;
  status: "queued" | "running" | "completed" | "failed" | "revoked";
  error: SurveyError | null;
}
export interface AnalysisAdapter {
  snapshot(
    surveyId: string,
    filter: AnalysisFilter,
    options?: RequestOptions,
  ): Promise<Result<AnalysisSnapshot>>;
  requestExport(
    snapshotId: string,
    product: ExportProduct,
    operationId: string,
    options?: RequestOptions,
  ): Promise<Result<ExportJob>>;
  exportStatus(
    jobId: string,
    options?: RequestOptions,
  ): Promise<Result<ExportJob>>;
  download(jobId: string, options?: RequestOptions): Promise<Result<Blob>>;
}
