import { useEffect, useRef, useState } from "react";

import type { ModulePageContext, ModuleSurface, UiModule } from "../modules";
import {
  isSearchQuery,
  normaliseQuery,
  SEARCH_DEBOUNCE_MS,
  searchPalette,
  type PaletteSearchOutcome,
} from "./sources";

export type PaletteSearchState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly query: string }
  | {
      readonly status: "done";
      readonly query: string;
      readonly outcome: PaletteSearchOutcome;
    }
  | { readonly status: "error"; readonly query: string };

/**
 * Debounced palette search. Each keystroke cancels the pending timer and
 * aborts the request in flight, so only the latest query can resolve.
 */
export function usePaletteSearch(
  context: ModulePageContext,
  modules: readonly UiModule[],
  surface: ModuleSurface,
  query: string,
  enabled: boolean,
): { readonly state: PaletteSearchState; readonly retry: () => void } {
  const [state, setState] = useState<PaletteSearchState>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);
  const latest = useRef({ context, modules, surface });
  latest.current = { context, modules, surface };
  const text = normaliseQuery(query);
  const searchable = enabled && isSearchQuery(text);

  useEffect(() => {
    if (!searchable) {
      setState({ status: "idle" });
      return;
    }
    setState({ status: "loading", query: text });
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const { context, modules, surface } = latest.current;
      searchPalette(context, modules, surface, text, controller.signal).then(
        (outcome) => {
          if (controller.signal.aborted) return;
          setState(
            outcome.allFailed
              ? { status: "error", query: text }
              : { status: "done", query: text, outcome },
          );
        },
        () => {
          if (controller.signal.aborted) return;
          setState({ status: "error", query: text });
        },
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [searchable, text, attempt, context.identity.userId]);

  return { state, retry: () => setAttempt((value) => value + 1) };
}
