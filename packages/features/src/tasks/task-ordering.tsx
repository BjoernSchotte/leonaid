import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
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
import { useCallback, useLayoutEffect, useRef, type ReactNode } from "react";

/**
 * Drag and keyboard ordering of list rows. The list view renders the rows;
 * each movable row carries a `TaskOrderHandle`, which also makes its row
 * the sortable node. `ids` are the movable rows in visible order.
 */
export function TaskOrdering({
  children,
  ids,
  onCancel,
  onMove,
}: {
  readonly children: ReactNode;
  readonly ids: readonly string[];
  readonly onCancel: () => void;
  /** `before`/`after` is relative to `targetId`. */
  readonly onMove: (
    id: string,
    targetId: string,
    side: "before" | "after",
  ) => void;
}) {
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 220, tolerance: 6 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
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
      accessibility={{
        screenReaderInstructions: {
          draggable:
            "Zum Verschieben Leertaste drücken, mit den Pfeiltasten bewegen und mit Leertaste ablegen. Escape bricht ab.",
        },
        announcements: {
          onDragStart: () => "Aufgabe aufgenommen.",
          onDragOver: ({ over }) =>
            over ? "Neue Position gewählt." : "Kein Ziel gewählt.",
          onDragEnd: ({ over }) =>
            over ? "Aufgabe abgelegt." : "Verschieben abgebrochen.",
          onDragCancel: () => "Verschieben abgebrochen.",
        },
      }}
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

/**
 * The grip of one row. Its `.row` is the sortable node; the drag offset is
 * written through CSSOM (strict CSP: no style attributes in markup).
 */
export function TaskOrderHandle({
  disabled,
  id,
  title,
}: {
  readonly disabled: boolean;
  readonly id: string;
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
      ref={attach}
      className="task-order-handle"
      id={`task-move-${id}`}
      type="button"
      disabled={disabled}
      aria-label={`Aufgabe verschieben: ${title}`}
      title="Ziehen oder mit Leertaste und Pfeiltasten verschieben"
    >
      <GripVertical aria-hidden="true" size={14} />
    </button>
  );
}
