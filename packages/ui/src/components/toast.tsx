import { CircleCheck, CircleX, Info, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

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

function ToastItem({
  onDismiss,
  toast,
}: {
  readonly onDismiss: (id: string) => void;
  readonly toast: ToastEntry;
}) {
  const tone = toast.tone ?? "info";
  const ToneIcon = toneIcon[tone];
  const timeout = toast.timeout ?? DEFAULT_TIMEOUT;
  // The timer pauses while the pointer or focus is on the toast.
  const remaining = useRef(timeout);
  const startedAt = useRef(0);
  const [paused, setPaused] = useState({ hover: false, focus: false });
  const isPaused = paused.hover || paused.focus;

  useEffect(() => {
    if (timeout <= 0 || isPaused) return;
    startedAt.current = Date.now();
    const timer = window.setTimeout(
      () => onDismiss(toast.id),
      remaining.current,
    );
    return () => {
      window.clearTimeout(timer);
      remaining.current = Math.max(
        0,
        remaining.current - (Date.now() - startedAt.current),
      );
    };
  }, [isPaused, onDismiss, timeout, toast.id]);

  return (
    <div
      className={`toast ${toneClass[tone]}`}
      data-testid="toast"
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

  const dismiss = useCallback((id: string) => {
    setToasts((list) => list.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback((toast: LeonAidToast) => {
    nextId.current += 1;
    const id = `toast-${nextId.current}`;
    setToasts((list) => [...list.slice(-(LIMIT - 1)), { ...toast, id }]);
    return id;
  }, []);

  const api = useMemo(() => ({ dismiss, show }), [dismiss, show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Errors go to an assertive region, everything else to a polite one.
          Both regions always exist, so screen readers pick up insertions.
          No role="alert" on the empty region: it would count as an alert
          on every page. */}
      <div className="toaster">
        <div aria-live="polite" className="toaster-region" role="status">
          {toasts
            .filter((toast) => toast.tone !== "error")
            .map((toast) => (
              <ToastItem key={toast.id} onDismiss={dismiss} toast={toast} />
            ))}
        </div>
        <div aria-live="assertive" className="toaster-region">
          {toasts
            .filter((toast) => toast.tone === "error")
            .map((toast) => (
              <ToastItem key={toast.id} onDismiss={dismiss} toast={toast} />
            ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast needs a surrounding ToastProvider");
  return api;
}
