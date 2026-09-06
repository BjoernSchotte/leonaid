import { useEffect, useMemo, useState } from "react";
import { Model } from "survey-core";
import { createSurveyModel, restoreSurveyAnswers } from "./model";
import { Survey } from "survey-react-ui";
import "survey-core/i18n/german";
import type {
  Participation,
  ParticipationAdapter,
  ResponseSnapshot,
  SaveResponse,
} from "./contracts";

export interface RunnerProps {
  participation: Participation;
  adapter: ParticipationAdapter;
}
type SaveState =
  | "saved"
  | "pending"
  | "saving"
  | "error"
  | "conflict"
  | "completed";

/** One request at a time. An uncertain request keeps its exact key and payload. */
export class SaveCoordinator {
  private dirty = false;
  private generation = 0;
  private pending: { input: SaveResponse; generation: number } | null = null;
  private running: Promise<boolean> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private completion: { operationId: string; expectedRevision: number } | null =
    null;
  private restoring = false;
  private stopped = false;
  state: SaveState = "saved";
  message = "Alle Antworten gespeichert";
  response: ResponseSnapshot;
  constructor(
    readonly model: Model,
    readonly participation: Participation,
    readonly adapter: ParticipationAdapter,
    readonly notify: () => void,
  ) {
    this.response = participation.response;
  }
  private status(state: SaveState, message: string) {
    this.state = state;
    this.message = message;
    if (!this.stopped) this.notify();
  }
  changed(immediate = false) {
    if (this.restoring || this.stopped || this.state === "completed") return;
    this.generation++;
    this.dirty = true;
    if (this.state !== "conflict")
      this.status("pending", "Änderungen noch nicht gespeichert");
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), immediate ? 0 : 400);
  }
  flush(): Promise<boolean> {
    if (this.running) return this.running;
    if (this.state === "conflict" || this.stopped)
      return Promise.resolve(false);
    this.running = this.drain().finally(() => {
      this.running = null;
    });
    return this.running;
  }
  private async drain(): Promise<boolean> {
    while ((this.dirty || this.pending) && !this.stopped) {
      if (!this.pending)
        this.pending = {
          generation: this.generation,
          input: {
            operationId: crypto.randomUUID(),
            expectedRevision: this.response.revision,
            answers: structuredClone(this.model.data),
            currentPage: this.model.currentPage?.name ?? null,
          },
        };
      this.status("saving", "Antworten werden gespeichert …");
      try {
        const result = await this.adapter.save(
          this.participation.id,
          this.pending.input,
        );
        if (!result.ok) {
          if (
            ["invalid_response", "limit_exceeded"].includes(result.error.code)
          ) {
            this.pending = null;
            this.dirty = true;
          }
          this.status(
            result.error.code === "revision_conflict" ? "conflict" : "error",
            result.error.message,
          );
          return false;
        }
        this.response = result.value;
        this.dirty = this.generation !== this.pending.generation;
        if (!this.dirty) {
          this.restoring = true;
          try {
            restoreSurveyAnswers(this.model, result.value.answers);
          } finally {
            this.restoring = false;
          }
        }
        this.pending = null;
      } catch {
        this.status(
          "error",
          "Speichern derzeit nicht möglich. Ihre Änderungen bleiben in diesem geöffneten Fenster erhalten.",
        );
        return false;
      }
    }
    this.status("saved", "Alle Antworten gespeichert");
    return true;
  }
  async finish(): Promise<boolean> {
    this.model.mode = "display";
    if (!(await this.flush())) {
      this.model.mode = "edit";
      return false;
    }
    if (
      !this.completion ||
      this.completion.expectedRevision !== this.response.revision
    ) {
      this.completion = {
        operationId: crypto.randomUUID(),
        expectedRevision: this.response.revision,
      };
    }
    try {
      const result = await this.adapter.complete(
        this.participation.id,
        this.completion,
      );
      if (!result.ok) {
        this.status("error", result.error.message);
        this.model.mode = "edit";
        return false;
      }
      this.response = result.value;
      this.status("completed", "Vielen Dank. Ihre Antworten sind eingegangen.");
      return true;
    } catch {
      this.status(
        "error",
        "Der Abschluss konnte noch nicht bestätigt werden. Bitte versuchen Sie es erneut.",
      );
      this.model.mode = "edit";
      return false;
    }
  }
  dispose() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
  }
}

export function SurveyRunner({ participation, adapter }: RunnerProps) {
  const [, render] = useState(0);
  const { model, saves } = useMemo(() => {
    const model = createSurveyModel(participation.version.definition);
    model.locale = "de";
    model.textUpdateMode = "onTyping";
    restoreSurveyAnswers(model, participation.response.answers);
    if (participation.response.currentPage) {
      const page = model.getPageByName(participation.response.currentPage);
      if (page?.isVisible) model.currentPage = page;
    }
    const saves = new SaveCoordinator(model, participation, adapter, () =>
      render((n) => n + 1),
    );
    return { model, saves };
  }, [participation, adapter]);
  useEffect(() => {
    const changed = () => saves.changed();
    const pageChanged = () => saves.changed(true);
    const completing = async (
      _: Model,
      options: { allow: boolean; message?: string },
    ) => {
      options.allow = await saves.finish();
      if (!options.allow) options.message = saves.message;
    };
    const online = () => void saves.flush();
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (["pending", "saving", "error", "conflict"].includes(saves.state)) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    model.onValueChanged.add(changed);
    model.onCurrentPageChanged.add(pageChanged);
    model.onCompleting.add(completing);
    window.addEventListener("online", online);
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      model.onValueChanged.remove(changed);
      model.onCurrentPageChanged.remove(pageChanged);
      model.onCompleting.remove(completing);
      saves.dispose();
      window.removeEventListener("online", online);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [model, saves]);
  if (
    participation.response.status === "completed" ||
    saves.state === "completed"
  )
    return (
      <section className="survey-thanks">
        <h1>Vielen Dank für Ihre Rückmeldung.</h1>
        <p>Ihre Antworten sind eingegangen.</p>
      </section>
    );
  return (
    <section className="survey-runner">
      <div
        className="survey-save"
        role="status"
        aria-live="polite"
        data-save-state={saves.state}
      >
        <span>{saves.message}</span>
        {saves.state === "error" && (
          <button type="button" onClick={() => void saves.flush()}>
            Erneut speichern
          </button>
        )}
        {saves.state === "conflict" && (
          <p>
            Ein anderes Fenster hat neuere Antworten gespeichert. Laden Sie die
            Seite neu, um diesen Stand zu übernehmen.
          </p>
        )}
      </div>
      <Survey model={model} />
    </section>
  );
}
