import { createRoot } from "react-dom/client";
import { useEffect, useMemo, useState } from "react";
import { ApiError, LeonAidApiClient } from "@leonaid/api-client";
import { SurveyRunner } from "@leonaid/surveys/runner";
import type {
  ErrorCode,
  Participation,
  ParticipationAdapter,
  Result,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/styles";

const client = new LeonAidApiClient("");
const errorCodes: ErrorCode[] = [
  "unauthenticated",
  "forbidden",
  "not_found",
  "closed",
  "access_expired",
  "revision_conflict",
  "idempotency_conflict",
  "invalid_definition",
  "invalid_response",
  "unsupported_capability",
  "limit_exceeded",
  "temporarily_unavailable",
];
async function result<T>(request: Promise<unknown>): Promise<Result<T>> {
  try {
    return { ok: true, value: (await request) as T };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const code = errorCodes.includes(error.detail.code as ErrorCode)
      ? (error.detail.code as ErrorCode)
      : "temporarily_unavailable";
    return {
      ok: false,
      error: { code, message: error.detail.message, diagnostics: [] },
    };
  }
}
function ParticipationPage({ surveyId }: { surveyId: string }) {
  const [participation, setParticipation] = useState<Participation | null>(
    null,
  );
  const [title, setTitle] = useState("Ihre Rückmeldung zählt");
  const [message, setMessage] = useState("Fragebogen wird geladen …");
  const [ready, setReady] = useState(false);
  const [invitationToken, setInvitationToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const adapter = useMemo<ParticipationAdapter>(() => {
    const secret = Array.from(crypto.getRandomValues(new Uint8Array(48)), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
    return {
      start: (id, operationId, options) =>
        result(
          client.startSurveyParticipation(
            id,
            { operationId, resumeSecret: secret },
            options,
          ),
        ),
      restore: (id, options) =>
        result(client.restoreSurveyParticipation(surveyId, id, options)),
      save: (id, body, options) =>
        result(client.saveSurveyResponse(surveyId, id, body, options)),
      complete: (id, body, options) =>
        result(client.completeSurveyResponse(surveyId, id, body, options)),
    };
  }, [surveyId]);
  const startOperation = useMemo(() => crypto.randomUUID(), []);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const id = new URL(location.href).searchParams.get("participation");
        const invitation = new URLSearchParams(location.hash.slice(1)).get(
          "invitation",
        );
        if (invitation) {
          setInvitationToken(invitation);
          setMessage(
            "Dies ist Ihre persönliche Einladung. Ihre Antworten können dem Empfänger dieser Einladung zugeordnet werden. Sie werden während der Teilnahme gespeichert.",
          );
          setReady(true);
          return;
        }

        if (id) {
          const restored = await adapter.restore(id, {
            signal: controller.signal,
          });
          if (restored.ok) setParticipation(restored.value);
          else setMessage(restored.error.message);
        } else {
          const version = await client.getPublicSurvey(surveyId, {
            signal: controller.signal,
          });
          if (typeof version.definition.title === "string")
            setTitle(version.definition.title);
          setMessage(
            "Ihre Antworten werden während der Teilnahme gespeichert. Sie können den Fragebogen auf diesem Gerät später fortsetzen.",
          );
          setReady(true);
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setMessage(
            error instanceof ApiError
              ? error.message
              : "Der Fragebogen ist gerade nicht erreichbar. Bitte laden Sie die Seite erneut.",
          );
      }
    })();
    return () => controller.abort();
  }, [surveyId, adapter]);
  async function start() {
    setBusy(true);
    try {
      const started = invitationToken
        ? await result<Participation>(
            client.redeemSurveyInvitation(surveyId, { token: invitationToken }),
          )
        : await adapter.start(surveyId, startOperation);
      if (!started.ok) {
        setMessage(started.error.message);
        return;
      }
      const url = new URL(location.href);
      url.searchParams.set("participation", started.value.id);
      url.hash = "";
      history.replaceState(null, "", url);
      setParticipation(started.value);
    } catch {
      setMessage(
        "Die Teilnahme konnte noch nicht gestartet werden. Bitte versuchen Sie es erneut.",
      );
    } finally {
      setBusy(false);
    }
  }
  return participation ? (
    <SurveyRunner participation={participation} adapter={adapter} />
  ) : (
    <section className="survey-introduction">
      <p className="survey-eyebrow">Lions · Rückmeldung zur Aktion</p>
      <h1>{title}</h1>
      <p role="status">{message}</p>
      {ready && (
        <button type="button" disabled={busy} onClick={() => void start()}>
          {busy ? "Wird gestartet …" : "Umfrage beginnen"}
        </button>
      )}
    </section>
  );
}
const host = document.querySelector<HTMLElement>("[data-survey-host]");
if (host?.dataset.surveyId)
  createRoot(host).render(
    <ParticipationPage surveyId={host.dataset.surveyId} />,
  );
