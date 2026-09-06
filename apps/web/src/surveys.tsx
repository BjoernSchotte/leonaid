import { useEffect, useMemo, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { SurveyEditor } from "@leonaid/surveys/editor";
import type {
  AuthoringAdapter,
  Draft,
  Result,
  ErrorCode,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/editor-styles";

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
export function SurveysPage({
  client,
  surveyId,
}: {
  client: LeonAidApiClient;
  surveyId?: string;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState(false);
  const adapter = useMemo<AuthoringAdapter>(
    () => ({
      validateDraft: (id, expectedRevision, options) =>
        mapped(client.validateSurveyDraft(id, { expectedRevision }, options)),
      loadDraft: (id, options) => mapped(client.getSurveyDraft(id, options)),
      saveDraft: (id, body, options) =>
        mapped(client.saveSurveyDraft(id, body, options)),
      publish: (id, body, options) =>
        mapped(client.publishSurvey(id, body, options)),
    }),
    [client],
  );
  useEffect(() => {
    if (!surveyId || draft?.surveyId === surveyId) return;
    const abort = new AbortController();
    void adapter
      .loadDraft(surveyId, { signal: abort.signal })
      .then((result) => {
        if (!abort.signal.aborted) {
          if (result.ok) setDraft(result.value);
          else setMessage(result.error.message);
        }
      })
      .catch(() => {
        if (!abort.signal.aborted)
          setMessage("Der Entwurf konnte nicht geladen werden.");
      });
    return () => abort.abort();
  }, [surveyId, adapter]);
  const creation = useMemo(
    () => ({ id: crypto.randomUUID(), operationId: crypto.randomUUID() }),
    [],
  );
  async function create() {
    setBusy(true);
    setMessage("");
    const id = creation.id;
    try {
      const result = await client.createSurvey(id, {
        operationId: creation.operationId,
        title,
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
      setDraft(result as Draft);
      history.replaceState(null, "", `/admin/surveys/${id}`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Umfrage konnte nicht erstellt werden.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="ui-main" aria-label="Umfragen">
      <header>
        <p>Umfragen</p>
        <h1>
          {draft
            ? "Fragebogen gestalten"
            : surveyId
              ? "Entwurf laden"
              : "Neue Umfrage"}
        </h1>
        <p>
          Gestalten Sie Fragen und Seiten. Änderungen werden als Entwurf
          gespeichert.
        </p>
      </header>
      {message && <p role="alert">{message}</p>}
      {draft ? (
        <>
          <SurveyEditor
            draft={draft}
            adapter={adapter}
            onPublished={() => setPublished(true)}
          />
          {published && (
            <a
              href={`/surveys/${draft.surveyId}`}
              target="_blank"
              rel="noreferrer"
            >
              Veröffentlichte Umfrage öffnen
            </a>
          )}
        </>
      ) : (
        !surveyId && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label>
              Titel der Umfrage
              <input
                required
                maxLength={240}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <button type="submit" disabled={busy || !title.trim()}>
              {busy ? "Wird erstellt …" : "Umfrage erstellen"}
            </button>
          </form>
        )
      )}
    </section>
  );
}
