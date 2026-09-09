import assert from "node:assert/strict";

// The caller has verified the complete published bundle hash. Keep the native
// repeater's state, mutations and DnD implementation; repair its input controls.
export function patchRepeaterEditor(source) {
  const start = source.indexOf("function RepeaterField(");
  const end = source.indexOf("function SubFieldInput(", start);
  assert.ok(start > 0 && end > start);
  const original = source.slice(start, end);
  let patched = original;
  const replace = (before, after) => {
    assert.equal(
      patched.split(before).length,
      2,
      "Repeater patch seam changed",
    );
    patched = patched.replace(before, after);
  };
  replace(
    "\tconst rawItems = Array.isArray(value) ? value : [];",
    "\tconst sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));\n\tconst rawItems = Array.isArray(value) ? value : [];",
  );
  replace(
    "\t\t\tcollisionDetection: closestCenter,",
    "\t\t\tsensors,\n\t\t\tcollisionDetection: closestCenter,",
  );
  replace(
    "const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item._key });",
    "const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: item._key });",
  );
  replace(
    "\t\t\tonClick: onToggleCollapse,\n\t\t\tchildren:",
    "\t\t\tchildren:",
  );
  replace(
    `jsx(DotsSixVertical, {
\t\t\t\t\tclassName: "h-4 w-4 text-kumo-subtle cursor-grab shrink-0",
\t\t\t\t\t...attributes,
\t\t\t\t\t...listeners,
\t\t\t\t\tonClick: (e) => e.stopPropagation()
\t\t\t\t})`,
    `jsx("button", {
\t\t\t\t\ttype: "button",
\t\t\t\t\tref: setActivatorNodeRef,
\t\t\t\t\tclassName: "flex min-h-11 min-w-11 items-center justify-center rounded cursor-grab touch-none text-kumo-subtle focus-visible:outline-2 focus-visible:outline-offset-2",
\t\t\t\t\t...attributes,
\t\t\t\t\t...listeners,
\t\t\t\t\t"aria-label": _t2({ id: "2BPVq8", message: "Reorder {0}", values: { 0: summaryLabel } }),
\t\t\t\t\tchildren: jsx(DotsSixVertical, { className: "h-4 w-4", "aria-hidden": true })
\t\t\t\t})`,
  );
  replace(
    `jsx("span", {
\t\t\t\t\tclassName: "text-sm font-medium flex-1 truncate",
\t\t\t\t\tchildren: summaryLabel
\t\t\t\t})`,
    `jsx("button", {
\t\t\t\t\ttype: "button",
\t\t\t\t\tclassName: "min-h-11 min-w-0 text-start text-sm font-medium flex-1 truncate rounded focus-visible:outline-2 focus-visible:outline-offset-2",
\t\t\t\t\t"aria-expanded": !isCollapsed,
\t\t\t\t\tonClick: onToggleCollapse,
\t\t\t\t\tchildren: summaryLabel
\t\t\t\t})`,
  );
  return source.slice(0, start) + patched + source.slice(end);
}
