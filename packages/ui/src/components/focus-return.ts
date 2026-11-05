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
 * The opener can also lose focus a moment after the dialog closed, when the
 * request finishes and the list re-renders. For a short time after closing,
 * focus moves to the fallback if the opener is removed or disabled while it
 * still holds focus (or focus already fell to <body>).
 */

export const FOCUS_FALLBACK_ATTRIBUTE = "data-focus-fallback";

/** How long a restored opener is watched for late removal or disabling. */
export const FOCUS_WATCH_MS = 3000;

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

function watchOpener(
  saved: FocusReturn & { opener: HTMLElement },
  doc: Document,
): void {
  const view = doc.defaultView;
  if (!view) return;
  const { opener } = saved;
  let done = false;
  const stop = () => {
    if (done) return;
    done = true;
    observer.disconnect();
    doc.removeEventListener("focusin", onFocusIn, true);
    view.clearTimeout(timer);
  };
  const check = () => {
    const active = doc.activeElement;
    const holdsFocus = active === opener || active === doc.body || !active;
    if (!holdsFocus) {
      stop();
      return;
    }
    if (!canTakeFocus(opener)) {
      stop();
      focusFallback(saved, doc);
    }
  };
  const onFocusIn = (event: FocusEvent) => {
    // The user (or the page) moved focus on: stop watching.
    if (event.target !== opener) stop();
  };
  const observer = new view.MutationObserver(check);
  observer.observe(doc.body, {
    attributes: true,
    attributeFilter: ["disabled", "hidden", "inert"],
    childList: true,
    subtree: true,
  });
  doc.addEventListener("focusin", onFocusIn, true);
  const timer = view.setTimeout(stop, FOCUS_WATCH_MS);
}

/** Returns focus after a dialog closed; see the module comment. */
export function restoreFocusReturn(
  saved: FocusReturn | null,
  doc: Document = document,
): void {
  if (!saved) return;
  const { opener } = saved;
  if (canTakeFocus(opener)) {
    opener.focus();
    if (doc.activeElement === opener) {
      watchOpener({ ...saved, opener }, doc);
      return;
    }
  }
  focusFallback(saved, doc);
}
