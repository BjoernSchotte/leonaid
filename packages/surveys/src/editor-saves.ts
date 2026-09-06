import type { AuthoringAdapter, Draft, SaveDraft } from "./contracts";
import { EditorHistory } from "./editor-model";

export class DraftCoordinator {
  revision: number;
  state: "saved" | "pending" | "saving" | "error" | "conflict" = "saved";
  message = "Entwurf gespeichert";
  private savedGeneration = 0;
  private pending: { input: SaveDraft; generation: number } | null = null;
  private running: Promise<boolean> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  constructor(
    readonly initial: Draft,
    readonly history: EditorHistory,
    readonly adapter: AuthoringAdapter,
    readonly notify: () => void,
  ) {
    this.revision = initial.revision;
  }
  changed() {
    if (this.state !== "conflict") {
      this.state = "pending";
      this.message = "Änderungen noch nicht gespeichert";
    }
    this.notify();
    this.cancelTimer();
    this.timer = setTimeout(() => void this.flush(), 700);
  }
  cancelTimer() {
    if (this.timer) clearTimeout(this.timer);
  }
  flush(): Promise<boolean> {
    this.cancelTimer();
    if (this.state === "conflict") return Promise.resolve(false);
    if (this.running) return this.running;
    this.running = this.drain().finally(() => {
      this.running = null;
    });
    return this.running;
  }
  private async drain(): Promise<boolean> {
    while (this.pending || this.savedGeneration !== this.history.generation) {
      this.pending ??= {
        generation: this.history.generation,
        input: {
          operationId: crypto.randomUUID(),
          expectedRevision: this.revision,
          definition: this.history.document,
        },
      };
      this.state = "saving";
      this.message = "Entwurf wird gespeichert …";
      this.notify();
      try {
        const result = await this.adapter.saveDraft(
          this.initial.surveyId,
          this.pending.input,
        );
        if (!result.ok) {
          this.state =
            result.error.code === "revision_conflict" ? "conflict" : "error";
          this.message = result.error.message;
          if (
            [
              "invalid_definition",
              "limit_exceeded",
              "unsupported_capability",
            ].includes(result.error.code)
          )
            this.pending = null;
          this.notify();
          return false;
        }
        this.revision = result.value.revision;
        this.savedGeneration = this.pending.generation;
        this.pending = null;
      } catch {
        this.state = "error";
        this.message =
          "Speichern nicht bestätigt. Ihre Änderungen bleiben in diesem Fenster erhalten.";
        this.notify();
        return false;
      }
    }
    this.state = "saved";
    this.message = "Entwurf gespeichert";
    this.notify();
    return true;
  }
}
