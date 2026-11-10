import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DndContextProps,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import {
  useCallback,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import "./task-ordering.css";

/**
 * How a touch on the grip starts a drag. "press": after a long press (small
 * grips, where a scroll may start on them). "handle": after a few pixels of
 * movement, no wait; for a large grip with `touch-action: none`, while the
 * row body still scrolls the list.
 */
export type OrderingTouch = "press" | "handle";

/** Mouse, touch and keyboard (space, arrows) for ordering. */
export function useOrderingSensors(touch: OrderingTouch = "press") {
  return useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, {
      activationConstraint:
        touch === "handle" ? { distance: 4 } : { delay: 220, tolerance: 6 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
}

/** German screen reader instructions and announcements for ordering. */
export function orderingAccessibility(
  noun: string,
): NonNullable<DndContextProps["accessibility"]> {
  return {
    screenReaderInstructions: {
      draggable:
        "Zum Verschieben Leertaste drücken, mit den Pfeiltasten bewegen und mit Leertaste ablegen. Escape bricht ab.",
    },
    announcements: {
      onDragStart: () => `${noun} aufgenommen.`,
      onDragOver: ({ over }) =>
        over ? "Neue Position gewählt." : "Kein Ziel gewählt.",
      onDragEnd: ({ over }) =>
        over ? `${noun} abgelegt.` : "Verschieben abgebrochen.",
      onDragCancel: () => "Verschieben abgebrochen.",
    },
  };
}

/**
 * Drag and keyboard ordering of list rows. The list view renders the rows;
 * each movable row carries a `TaskOrderHandle`, which also makes its row
 * the sortable node. `ids` are the movable rows in visible order.
 */
export function TaskOrdering({
  children,
  ids,
  noun = "Aufgabe",
  onCancel,
  onMove,
  touch = "press",
}: {
  readonly children: ReactNode;
  readonly ids: readonly string[];
  readonly touch?: OrderingTouch;
  /** What a row is, for the screen reader announcements ("Stopp"). */
  readonly noun?: string;
  readonly onCancel: () => void;
  /** `before`/`after` is relative to `targetId`. */
  readonly onMove: (
    id: string,
    targetId: string,
    side: "before" | "after",
  ) => void;
}) {
  const sensors = useOrderingSensors(touch);
  const finish = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    onMove(String(active.id), String(over.id), from < to ? "after" : "before");
  };
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={finish}
      onDragCancel={onCancel}
      accessibility={orderingAccessibility(noun)}
    >
      <SortableContext
        items={ids as string[]}
        strategy={verticalListSortingStrategy}
      >
        {children}
      </SortableContext>
    </DndContext>
  );
}

const MOVE_KEYS = new Set([
  " ",
  "Enter",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
]);

/** Marks the keys handled, so list hotkeys (arrows: next row) skip them. */
function swallowMoveKeys(event: KeyboardEvent<HTMLButtonElement>) {
  if (MOVE_KEYS.has(event.key)) event.preventDefault();
}

/**
 * The grip of one row. Its `.row` is the sortable node; the drag offset is
 * written through CSSOM (strict CSP: no style attributes in markup).
 *
 * `disabled` never becomes the HTML attribute: a disabled button drops
 * focus to `<body>`, so a keyboard user would lose their place while a move
 * saves. dnd-kit marks the grip `aria-disabled` and drops its listeners
 * instead, which keeps it focusable. While inert it also swallows the keys
 * of a keyboard move, so pressing on (Space, arrows) neither opens nor
 * walks the list and focus stays put.
 */
export function TaskOrderHandle({
  disabled,
  id,
  noun = "Aufgabe",
  title,
}: {
  readonly disabled: boolean;
  readonly id: string;
  /** What the row is, for the accessible name ("Stopp verschieben: …"). */
  readonly noun?: string;
  readonly title: string;
}) {
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });
  const row = useRef<HTMLElement | null>(null);
  const attach = useCallback(
    (element: HTMLButtonElement | null) => {
      setActivatorNodeRef(element);
      const next = element?.closest<HTMLElement>(".row") ?? null;
      if (next !== row.current) {
        row.current = next;
        setNodeRef(next);
      }
    },
    [setActivatorNodeRef, setNodeRef],
  );
  useLayoutEffect(() => {
    const element = row.current;
    if (!element) return;
    const offset = CSS.Transform.toString(transform);
    if (offset) element.style.setProperty("transform", offset);
    else element.style.removeProperty("transform");
    if (transition) element.style.setProperty("transition", transition);
    else element.style.removeProperty("transition");
    if (isDragging) element.dataset.dragging = "true";
    else delete element.dataset.dragging;
  }, [transform, transition, isDragging]);
  useLayoutEffect(
    () => () => {
      const element = row.current;
      element?.style.removeProperty("transform");
      element?.style.removeProperty("transition");
      if (element) delete element.dataset.dragging;
    },
    [],
  );
  return (
    <button
      {...attributes}
      {...listeners}
      {...(disabled ? { onKeyDown: swallowMoveKeys } : {})}
      ref={attach}
      className="task-order-handle"
      id={`task-move-${id}`}
      type="button"
      aria-label={`${noun} verschieben: ${title}`}
      title="Ziehen oder mit Leertaste und Pfeiltasten verschieben"
    >
      <GripVertical aria-hidden="true" size={14} />
    </button>
  );
}
