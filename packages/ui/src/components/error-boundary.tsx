import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "./button";
import { StatusMessage } from "./status-message";

const RELOAD_MARKER = "leonaid:chunk-reload";

/** True when a lazily loaded chunk is gone, usually after a new deploy. */
export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.name === "ChunkLoadError" ||
    /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
      error.message,
    )
  );
}

function reloadOnceForNewDeploy(): boolean {
  try {
    if (window.sessionStorage.getItem(RELOAD_MARKER)) return false;
    window.sessionStorage.setItem(RELOAD_MARKER, String(Date.now()));
  } catch {
    return false;
  }
  window.location.reload();
  return true;
}

export interface ErrorBoundaryProps {
  readonly children: ReactNode;
}

interface ErrorBoundaryState {
  readonly error: unknown;
}

/**
 * Keeps a render error or a missing chunk from unmounting the whole app into
 * a blank page. A missing chunk triggers one automatic reload per session.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  override state: ErrorBoundaryState = { error: undefined };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error ?? new Error("Unknown render error") };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("LeonAid render error", error, info.componentStack);
    if (isChunkLoadError(error)) {
      reloadOnceForNewDeploy();
    }
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (error === undefined) return this.props.children;
    const newVersion = isChunkLoadError(error);
    return (
      <main className="ui-error-boundary" data-testid="app-error">
        <StatusMessage tone="error">
          <h1>
            {newVersion
              ? "Eine neue Version von LeonAid ist verfügbar."
              : "Diese Ansicht konnte nicht angezeigt werden."}
          </h1>
          <p>
            {newVersion
              ? "Bitte lade die Seite neu, um weiterzuarbeiten."
              : "Bitte lade die Seite neu. Wenn der Fehler bleibt, wende dich an die Administration."}
          </p>
        </StatusMessage>
        <Button onClick={() => window.location.reload()} type="button">
          Seite neu laden
        </Button>
      </main>
    );
  }
}
