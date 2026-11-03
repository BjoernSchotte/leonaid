import { CircleCheck, CircleX, Info, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { subscribeModalStack, topModalSlot } from "./modal";

export type ToastTone = "error" | "info" | "success";

export interface ToastAction {
  readonly label: string;
  readonly run: () => void;
}

export interface LeonAidToast {
  /** Optional follow-up such as "Rückgängig"; running it dismisses the toast. */
  readonly action?: ToastAction;
  readonly description?: ReactNode;
  /** Milliseconds until it closes; 0 keeps it open. Default 5200. */
  readonly timeout?: number;
  readonly title: ReactNode;
  readonly tone?: ToastTone;
}

interface ToastEntry extends LeonAidToast {
  readonly id: string;
  /** False until the frame after show(); see ToastProvider. */
  readonly ready: boolean;
}

const DEFAULT_TIMEOUT = 5_200;
const LIMIT = 3;

const toneClass = {
  error: "tone-danger",
  info: "tone-info",
  success: "tone-ok",
} as const;

const toneIcon = {
  error: CircleX,
  info: Info,
  success: CircleCheck,
} as const;

interface ToastApi {
  readonly show: (toast: LeonAidToast) => string;
  readonly dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

function subscribeVisibility(listener: () => void) {
  document.addEventListener("visibilitychange", listener);
  return () => document.removeEventListener("visibilitychange", listener);
}

function ToastItem({
  hidden,
  onDismiss,
  remainingTimes,
  toast,
}: {
  /** The page is in a background tab. */
  readonly hidden: boolean;
  readonly onDismiss: (id: string) => void;
  /** Remaining ms per toast; survives a remount when the toaster moves. */
  readonly remainingTimes: Map<string, number>;
  readonly toast: ToastEntry;
}) {
  const tone = toast.tone ?? "info";
  const ToneIcon = toneIcon[tone];
  const timeout = toast.timeout ?? DEFAULT_TIMEOUT;
  // The timer pauses while the pointer or focus is on the toast and while
  // the page is hidden.
  const [paused, setPaused] = useState({ hover: false, focus: false });
  const isPaused = paused.hover || paused.focus || hidden;

  useEffect(() => {
    if (timeout <= 0 || isPaused) return;
    const remaining = remainingTimes.get(toast.id) ?? timeout;
    const startedAt = Date.now();
    const timer = window.setTimeout(() => onDismiss(toast.id), remaining);
    return () => {
      window.clearTimeout(timer);
      remainingTimes.set(
        toast.id,
        Math.max(0, remaining - (Date.now() - startedAt)),
      );
    };
  }, [isPaused, onDismiss, remainingTimes, timeout, toast.id]);

  return (
    <div
      className={`toast ${toneClass[tone]}`}
      data-testid="toast"
      data-toast-id={toast.id}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setPaused((state) => ({ ...state, focus: false }));
        }
      }}
      onFocus={() => setPaused((state) => ({ ...state, focus: true }))}
      onMouseEnter={() => setPaused((state) => ({ ...state, hover: true }))}
      onMouseLeave={() => setPaused((state) => ({ ...state, hover: false }))}
    >
      <ToneIcon aria-hidden="true" size={16} />
      <span className="toast-text">
        <strong className="toast-title">{toast.title}</strong>
        {toast.description ? (
          <span className="toast-description">{toast.description}</span>
        ) : null}
      </span>
      {toast.action ? (
        <button
          className="toast-action"
          onClick={() => {
            toast.action?.run();
            onDismiss(toast.id);
          }}
          type="button"
        >
          {toast.action.label}
        </button>
      ) : null}
      <button
        aria-label="Meldung schließen"
        className="toast-close"
        onClick={() => onDismiss(toast.id)}
        type="button"
      >
        <X aria-hidden="true" size={14} />
      </button>
    </div>
  );
}

/** Holds the toasts and renders their live regions, bottom right. */
export function ToastProvider({ children }: { readonly children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly ToastEntry[]>([]);
  const nextId = useRef(0);

  const remainingTimes = useRef(new Map<string, number>()).current;
  const toastsRef = useRef(toasts);
  toastsRef.current = toasts;
  const toasterRef = useRef<HTMLDivElement>(null);
  /*
   * One persistent host node holds the toaster, so both live regions keep
   * their identity. Outside the topmost modal dialog the toaster would sit
   * behind it and be inert, so the host moves into that dialog while one is
   * open and back to <body> afterwards.
   */
  const [host] = useState(() =>
    typeof document === "undefined" ? null : document.createElement("div"),
  );
  useLayoutEffect(() => {
    if (!host) return;
    const place = () => {
      const target = topModalSlot() ?? document.body;
      if (host.parentNode === target) return;
      const active = document.activeElement;
      const hadFocus = active instanceof HTMLElement && host.contains(active);
      target.appendChild(host);
      // Moving a node drops focus; give it back to the toast.
      if (hadFocus && document.activeElement !== active) {
        active.focus({ preventScroll: true });
      }
    };
    place();
    const unsubscribe = subscribeModalStack(place);
    return () => {
      unsubscribe();
      host.remove();
    };
  }, [host]);
  const hidden = useSyncExternalStore(
    subscribeVisibility,
    () => document.hidden,
    () => false,
  );

  const dismiss = useCallback(
    (id: string) => {
      remainingTimes.delete(id);
      setToasts((list) => list.filter((toast) => toast.id !== id));
    },
    [remainingTimes],
  );

  // F6 jumps to the newest toast (its action, else its close button).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (
        event.key !== "F6" ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey
      ) {
        return;
      }
      const newest = toastsRef.current.at(-1);
      const target = newest
        ? toasterRef.current?.querySelector<HTMLElement>(
            `[data-toast-id="${newest.id}"] button`,
          )
        : null;
      if (!target) return;
      event.preventDefault();
      target.focus();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const show = useCallback((toast: LeonAidToast) => {
    nextId.current += 1;
    const id = `toast-${nextId.current}`;
    setToasts((list) => [
      ...list.slice(-(LIMIT - 1)),
      { ...toast, id, ready: false },
    ]);
    return id;
  }, []);

  const api = useMemo(() => ({ dismiss, show }), [dismiss, show]);

  // A toast enters its live region one frame after show(). A modal that
  // closes in the same update has moved the host by then, so the toast is
  // inserted into a region that is connected and visible, which screen
  // readers announce.
  const waiting = toasts.some((toast) => !toast.ready);
  useEffect(() => {
    if (!waiting) return;
    const frame = window.requestAnimationFrame(() => {
      setToasts((list) =>
        list.map((toast) => (toast.ready ? toast : { ...toast, ready: true })),
      );
    });
    return () => window.cancelAnimationFrame(frame);
  }, [waiting]);
  const visible = toasts.filter((toast) => toast.ready);

  const item = (toast: ToastEntry) => (
    <ToastItem
      hidden={hidden}
      key={toast.id}
      onDismiss={dismiss}
      remainingTimes={remainingTimes}
      toast={toast}
    />
  );
  // Errors go to an assertive region, everything else to a polite one. Both
  // regions always exist, so screen readers pick up insertions. No
  // role="alert" on the empty region: it would count as an alert on every
  // page.
  const toaster = (
    <div className="toaster" ref={toasterRef}>
      <div aria-live="polite" className="toaster-region" role="status">
        {visible.filter((toast) => toast.tone !== "error").map(item)}
      </div>
      <div aria-live="assertive" className="toaster-region">
        {visible.filter((toast) => toast.tone === "error").map(item)}
      </div>
    </div>
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {host ? createPortal(toaster, host) : null}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast needs a surrounding ToastProvider");
  return api;
}
