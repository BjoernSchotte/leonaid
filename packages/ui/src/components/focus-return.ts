/**
 * Where focus goes when a dialog closes.
 *
 * The opener gets focus back when it can still take it. A confirm flow often
 * removes or disables its opener (a revoked row, a swapped "Wieder öffnen"
 * button, a button that is `disabled` while its request runs), and then focus
 * would fall to <body>. The fallback, in this order:
 * 1. the nearest `[data-focus-fallback]` around the opener, remembered when
 *    the dialog opened (the opener may be gone by now);
 * 2. the page's main heading (`main h1`), made focusable with tabIndex -1;
 * 3. `main` itself, made focusable with tabIndex -1.
 *
 * The fallback only fills a gap: it acts when focus is lost (on <body> or a
 * removed element), after the app had its turn (FOCUS_SETTLE_MS), and for a
 * short time after closing (FOCUS_WATCH_MS) in case the opener is removed
 * later. It never takes focus from an element the app or the user focused.
 */

export const FOCUS_FALLBACK_ATTRIBUTE = "data-focus-fallback";

/** How long after closing a lost focus is still filled by the fallback. */
export const FOCUS_WATCH_MS = 3000;

/**
 * Delay before the fallback fills a lost focus: the app's own deferred focus
 * moves (effects, `setTimeout(0)`, a frame) come first.
 */
export const FOCUS_SETTLE_MS = 100;

export interface FocusReturn {
  readonly opener: HTMLElement | null;
  readonly fallback: HTMLElement | null;
}

export function captureFocusReturn(doc: Document = document): FocusReturn {
  const active = doc.activeElement;
  const opener =
    active instanceof HTMLElement && active !== doc.body ? active : null;
  const fallback =
    opener?.closest<HTMLElement>(`[${FOCUS_FALLBACK_ATTRIBUTE}]`) ?? null;
  return { opener, fallback };
}

function canTakeFocus(element: HTMLElement | null): element is HTMLElement {
  if (!element?.isConnected) return false;
  if (element.matches(":disabled")) return false;
  if (element.closest("[inert], [hidden]")) return false;
  return true;
}

function focusWithin(element: HTMLElement): boolean {
  if (
    !element.matches("a[href], button, input, select, textarea, [tabindex]")
  ) {
    element.tabIndex = -1;
  }
  element.focus();
  return element.ownerDocument.activeElement === element;
}

/** Moves focus to the fallback chain; true when something took focus. */
export function focusFallback(
  saved: FocusReturn,
  doc: Document = document,
): boolean {
  const candidates = [
    saved.fallback,
    doc.querySelector<HTMLElement>("main h1"),
    doc.querySelector<HTMLElement>("main"),
  ];
  for (const candidate of candidates) {
    if (canTakeFocus(candidate) && focusWithin(candidate)) return true;
  }
  return false;
}

/** Focus is lost when nothing (or <body>, or a removed element) holds it. */
function focusIsLost(doc: Document): boolean {
  const active = doc.activeElement;
  return !active || active === doc.body || !active.isConnected;
}

/**
 * Watches the moments after a dialog closed. The fallback only ever fills a
 * gap: it acts when focus is lost, and only after the app had its turn (a
 * list may move focus to a row in its own effect or timeout). It never moves
 * focus away from an element that holds it, and any focus change by the app
 * or the user ends the watch.
 */
function watchAfterClose(saved: FocusReturn, doc: Document): void {
  const view = doc.defaultView;
  if (!view) return;
  let done = false;
  let pending: number | undefined;
  const stop = () => {
    if (done) return;
    done = true;
    observer.disconnect();
    doc.removeEventListener("focusin", onFocusIn, true);
    view.clearTimeout(timer);
    view.clearTimeout(pending);
  };
  const settle = () => {
    pending = undefined;
    if (done) return;
    if (focusIsLost(doc)) {
      stop();
      focusFallback(saved, doc);
    }
  };
  const later = () => {
    if (pending === undefined)
      pending = view.setTimeout(settle, FOCUS_SETTLE_MS);
  };
  const onFocusIn = (event: FocusEvent) => {
    // Focus went somewhere on purpose (the app or the user): leave it there.
    if (event.target !== saved.opener) stop();
  };
  // The opener may be removed a moment later (a refetched list): check again
  // then, still only if focus ends up lost.
  const observer = new view.MutationObserver(() => {
    if (focusIsLost(doc)) later();
  });
  observer.observe(doc.body, { childList: true, subtree: true });
  doc.addEventListener("focusin", onFocusIn, true);
  const timer = view.setTimeout(stop, FOCUS_WATCH_MS);
  later();
}

/** Returns focus after a dialog closed; see the module comment. */
export function restoreFocusReturn(
  saved: FocusReturn | null,
  doc: Document = document,
): void {
  if (!saved) return;
  if (canTakeFocus(saved.opener)) saved.opener.focus();
  watchAfterClose(saved, doc);
}
