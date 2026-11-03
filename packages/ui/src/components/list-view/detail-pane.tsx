import { ChevronLeft, ChevronRight, X } from "lucide-react";
import {
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { IconButton } from "../button";
import { registerModalLayer, unregisterModalLayer } from "../modal";

/** Below this width the pane is a full-screen sheet (native dialog). */
export const SHEET_QUERY = "(max-width: 720px)";

function subscribeMedia(query: string) {
  return (listener: () => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {};
    const list = window.matchMedia(query);
    list.addEventListener("change", listener);
    return () => list.removeEventListener("change", listener);
  };
}

/** Live `matchMedia` result; false where matchMedia is missing. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => subscribeMedia(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () =>
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia(query).matches
        : false,
    () => false,
  );
}

export interface DetailPaneProps {
  readonly title: string;
  readonly onClose: () => void;
  readonly onPrevious: () => void;
  readonly onNext: () => void;
  readonly children: ReactNode;
}

function PaneContent({
  children,
  onClose,
  onNext,
  onPrevious,
  title,
}: DetailPaneProps) {
  return (
    <>
      <header className="pane-header">
        <div className="pane-nav">
          <IconButton
            icon={ChevronLeft}
            label="Vorheriger Eintrag (K)"
            onClick={onPrevious}
            size="sm"
          />
          <IconButton
            icon={ChevronRight}
            label="Nächster Eintrag (J)"
            onClick={onNext}
            size="sm"
          />
        </div>
        <h2 className="pane-title">{title}</h2>
        <IconButton icon={X} label="Schließen (Esc)" onClick={onClose} />
      </header>
      <div className="pane-body">{children}</div>
    </>
  );
}

/**
 * Full-screen sheet on phones: a modal native <dialog>, so focus stays in it
 * and Esc closes it. The list's keys are inert while it is open.
 */
function DetailSheet(props: DetailPaneProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const slotRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(props.onClose);
  onCloseRef.current = props.onClose;

  useLayoutEffect(() => {
    const dialog = ref.current;
    const slot = slotRef.current;
    if (!dialog || !slot) return;
    if (!dialog.open) dialog.showModal();
    registerModalLayer(slot);
    return () => {
      unregisterModalLayer(slot);
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      aria-label={`Details: ${props.title}`}
      className="pane pane-sheet"
      onCancel={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        onCloseRef.current();
      }}
      ref={ref}
    >
      <PaneContent {...props} />
      <div className="modal-toast-slot" ref={slotRef} />
    </dialog>
  );
}

/** Desktop right pane (a drawer under 1180 px), a sheet under 720 px. */
export function DetailPane(props: DetailPaneProps) {
  const sheet = useMediaQuery(SHEET_QUERY);
  if (sheet) return <DetailSheet {...props} />;
  return (
    <aside aria-label={`Details: ${props.title}`} className="pane">
      <PaneContent {...props} />
    </aside>
  );
}

/** Caps-headed section of the pane body. */
export function DetailSection({
  children,
  title,
}: {
  readonly children: ReactNode;
  readonly title: ReactNode;
}) {
  return (
    <section className="pane-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export interface DetailPropsItem {
  readonly label: string;
  readonly value: ReactNode;
}

/** Definition list with a 38 % label column. */
export function DetailProps({
  items,
}: {
  readonly items: readonly DetailPropsItem[];
}) {
  return (
    <dl className="props">
      {items.map((item) => (
        <div className="props-row" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface DetailTimelineItem {
  readonly id: string;
  readonly text: ReactNode;
  /** Shown under the text in text-3. */
  readonly time: string;
  /** ISO value for the <time> element. */
  readonly dateTime?: string;
}

/** History with zone-coloured dots. */
export function DetailTimeline({
  items,
}: {
  readonly items: readonly DetailTimelineItem[];
}) {
  return (
    <ol className="timeline">
      {items.map((item) => (
        <li key={item.id}>
          <span>
            {item.text}
            <time dateTime={item.dateTime}>{item.time}</time>
          </span>
        </li>
      ))}
    </ol>
  );
}
