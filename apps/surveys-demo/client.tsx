import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { SurveyRunner, type RunnerMessages } from "@leonaid/surveys/runner";
import type {
  ParticipationAdapter,
  Participation,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/styles";
import "./host.css";

async function request(method: string, body?: unknown) {
  const response = await fetch("/api/participation", {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  return response.json();
}
const adapter: ParticipationAdapter = {
  start: (_, operationId) => request("POST", { operationId }),
  restore: () => request("GET"),
  save: (_, input) => request("PUT", input),
  complete: (_, input) => request("PATCH", input),
};
const messages: RunnerMessages = {
  saved: "Saved by the independent host",
  pending: "Changes waiting to save",
  saving: "Saving to the demo database",
  saveFailed: "Save unavailable; keep this tab open.",
  completionFailed: "Submission was not confirmed. Please retry.",
  completing: "Confirming submission …",
  retryCompletion: "Confirm submission again",
  completed: "Submitted",
  thankYouTitle: "Your feedback is safe",
  thankYouBody: "The independent host received your response.",
  retry: "Retry save",
  conflict: "A newer response exists. Reload to restore it.",
};
function App() {
  const [participation, setParticipation] = useState<Participation | null>(
    null,
  );
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    void adapter.restore("current").then((result) => {
      if (result.ok) setParticipation(result.value);
      setLoaded(true);
    });
  }, []);
  return (
    <main>
      <header>
        <p className="eyebrow">Independent package consumer</p>
        <h1>Community feedback</h1>
        <p>This host saves progress to its own SQLite database.</p>
        <p>
          <a href="/exports">Download saved feedback</a>
        </p>
        <button
          className="host-control"
          onClick={() => document.body.classList.toggle("warm")}
        >
          Change host theme
        </button>
      </header>
      {!loaded ? (
        <p>Loading…</p>
      ) : participation ? (
        <SurveyRunner
          participation={participation}
          adapter={adapter}
          locale="en"
          messages={messages}
        />
      ) : (
        <button
          className="host-control"
          onClick={async () => {
            const result = await adapter.start(
              "community",
              crypto.randomUUID(),
            );
            if (result.ok) setParticipation(result.value);
          }}
        >
          Start feedback
        </button>
      )}
    </main>
  );
}
createRoot(document.getElementById("app")!).render(<App />);
