import type {
  PersonalPlan,
  PlannedTask,
  TaskSummary,
} from "@leonaid/api-client";

/** Where a task sits in my personal plan (property "Plan"). */
export type PlanBucket =
  | "today"
  | "due"
  | "week"
  | "later"
  | "someday"
  | "none";
/** Due date relative to today (property "Fällig"). */
export type DueBucket =
  | "overdue"
  | "today"
  | "week"
  | "later"
  | "past"
  | "none";

export const PLAN_LABELS: Readonly<Record<PlanBucket, string>> = {
  today: "Heute",
  due: "Bis heute fällig",
  week: "Diese Woche",
  later: "Später",
  someday: "Irgendwann",
  none: "Nicht eingeplant",
};
export const PLAN_BUCKETS = Object.keys(PLAN_LABELS) as PlanBucket[];
/** The buckets "Mein Plan" shows: everything I planned or that is due. */
export const PLANNED_BUCKETS: readonly PlanBucket[] = PLAN_BUCKETS.filter(
  (bucket) => bucket !== "none",
);

export const DUE_LABELS: Readonly<Record<DueBucket, string>> = {
  overdue: "Überfällig",
  today: "Heute",
  week: "Nächste 7 Tage",
  later: "Später",
  past: "Vergangen",
  none: "Ohne Datum",
};
export const DUE_BUCKETS = Object.keys(DUE_LABELS) as DueBucket[];

export const STATUS_LABELS = { open: "Offen", done: "Erledigt" } as const;

/** One list row: the server's task plus my plan and the server order. */
export interface TaskRow {
  readonly id: string;
  readonly task: TaskSummary;
  /** My personal plan when the plan views returned it, else null. */
  readonly plan: PersonalPlan | null;
  readonly planSource: PlannedTask["planSource"] | null;
  readonly planBucket: PlanBucket;
  /** Position in the server's personal plan order; Infinity when unplanned. */
  readonly planIndex: number;
  /** Position in the server's list order (manual order on list pages). */
  readonly listIndex: number;
  readonly dueBucket: DueBucket;
  readonly deferred: boolean;
}

/** Local calendar date `YYYY-MM-DD`. */
export function localIsoDate(date = new Date()): string {
  const part = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())}`;
}

function dayNumber(iso: string): number {
  const [year, month, day] = iso.split("-").map(Number);
  return Date.UTC(year!, month! - 1, day!) / 86_400_000;
}

/** Whole days from `today` to `iso` (both `YYYY-MM-DD`). */
export function daysBetween(today: string, iso: string): number {
  return dayNumber(iso) - dayNumber(today);
}

export function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  return localIsoDate(new Date(year!, month! - 1, day! + days));
}

export function planBucket(
  plan: PersonalPlan | null,
  source: PlannedTask["planSource"] | null,
  today: string,
): PlanBucket {
  // As the server's today view: due today even when planned for later.
  if (source === "due") return "due";
  if (plan?.state === "scheduled" && plan.plannedOn) {
    const days = daysBetween(today, plan.plannedOn);
    if (days <= 0) return "today";
    return days <= 7 ? "week" : "later";
  }
  if (plan?.state === "someday") return "someday";
  return "none";
}

export function dueBucket(task: TaskSummary, now: Date): DueBucket {
  if (!task.dueAt) return "none";
  const due = new Date(task.dueAt).getTime();
  const start = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const day = (offset: number) =>
    new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
  if (due < start) return task.status === "done" ? "past" : "overdue";
  if (due < day(1).getTime()) return "today";
  if (due < day(8).getTime()) return "week";
  return "later";
}

export function isDeferred(task: TaskSummary, now: Date): boolean {
  return (
    !!task.deferredUntil &&
    new Date(task.deferredUntil).getTime() > now.getTime()
  );
}

function isPlannedTask(task: TaskSummary | PlannedTask): task is PlannedTask {
  return "personalPlan" in task && "planSource" in task;
}

/**
 * Merges the server sources into one row per task. The open (and done)
 * list gives the order; the plan views add my plan to known tasks and bring
 * planned tasks the open list did not return. On a list page only that
 * list's planned tasks are added.
 */
export function buildTaskRows({
  open,
  done,
  plans,
  listId,
  now,
}: {
  readonly open: readonly TaskSummary[];
  readonly done: readonly TaskSummary[];
  /** Today, planned, then someday, in server order. */
  readonly plans: readonly PlannedTask[];
  readonly listId?: string;
  readonly now: Date;
}): TaskRow[] {
  const today = localIsoDate(now);
  const planned = new Map<
    string,
    {
      plan: PersonalPlan | null;
      source: PlannedTask["planSource"];
      index: number;
    }
  >();
  plans.forEach((task, index) => {
    const known = planned.get(task.id);
    // A task can be due today and planned later: the first view wins.
    if (known) {
      if (!known.plan && task.personalPlan) known.plan = task.personalPlan;
      return;
    }
    planned.set(task.id, {
      plan: task.personalPlan,
      source: task.planSource,
      index,
    });
  });
  const rows = new Map<string, TaskRow>();
  const add = (task: TaskSummary | PlannedTask, listIndex: number) => {
    if (rows.has(task.id)) return;
    const mine = planned.get(task.id);
    const base: TaskSummary = isPlannedTask(task)
      ? (({ personalPlan: _plan, planSource: _source, ...summary }) => summary)(
          task,
        )
      : task;
    rows.set(task.id, {
      id: task.id,
      task: base,
      plan: mine?.plan ?? null,
      planSource: mine?.source ?? null,
      planBucket: planBucket(mine?.plan ?? null, mine?.source ?? null, today),
      planIndex: mine?.index ?? Number.POSITIVE_INFINITY,
      listIndex,
      dueBucket: dueBucket(base, now),
      deferred: isDeferred(base, now),
    });
  };
  open.forEach((task, index) => add(task, index));
  done.forEach((task, index) => add(task, open.length + index));
  plans.forEach((task, index) => {
    if (!listId || task.listId === listId) {
      add(task, open.length + done.length + index);
    }
  });
  return [...rows.values()];
}

/* ---------- formatting ---------- */

const weekday = new Intl.DateTimeFormat("de-DE", {
  weekday: "short",
  day: "numeric",
  month: "short",
});
const shortDay = new Intl.DateTimeFormat("de-DE", {
  day: "numeric",
  month: "short",
});
const longDate = new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" });
const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** "heute", "morgen", "gestern", "in 3 Tagen", "vor 2 Tagen", "Mi., 12. Nov.". */
export function relativeDay(iso: string, today: string): string {
  const days = daysBetween(today, iso);
  if (days === 0) return "heute";
  if (days === 1) return "morgen";
  if (days === -1) return "gestern";
  if (days > 1 && days < 7) return `in ${days} Tagen`;
  if (days < -1 && days > -7) return `vor ${-days} Tagen`;
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year!, month! - 1, day!);
  return Math.abs(days) < 180 ? weekday.format(date) : longDate.format(date);
}

/** The plan pill: "Heute", "Mi., 12. Nov.", "Irgendwann". */
export function planLabel(row: TaskRow, today: string): string | null {
  if (row.plan?.state === "scheduled" && row.plan.plannedOn) {
    const days = daysBetween(today, row.plan.plannedOn);
    if (days <= 0) return "Heute";
    if (days === 1) return "Morgen";
    const [year, month, day] = row.plan.plannedOn.split("-").map(Number);
    return weekday.format(new Date(year!, month! - 1, day!));
  }
  if (row.plan?.state === "someday") return "Irgendwann";
  if (row.planSource === "due") return "Fällig";
  return null;
}

export function formatDateTime(value: string): string {
  return dateTime.format(new Date(value));
}

export function formatCalendarDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return longDate.format(new Date(year!, month! - 1, day!));
}

export function formatShortDay(value: string): string {
  return shortDay.format(new Date(value));
}

/* ---------- legacy URLs ---------- */

const LEGACY_VIEWS = new Set([
  "due-today",
  "due-next",
  "deferred",
  "plan-today",
  "plan-planned",
  "plan-someday",
]);

/**
 * Rewrites the old task URLs (`scope`, `view=due-today|…|plan-*`, `sort`,
 * `search`, `task`) to list view parameters, or returns null when the query
 * is not a legacy one. Bookmarks and old search links keep working.
 */
export function migrateLegacyTaskQuery(
  search: string,
  { listId, userId }: { readonly listId?: string; readonly userId: string },
): string | null {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  const sort = params.get("sort");
  const legacy =
    params.has("scope") ||
    params.has("search") ||
    params.has("task") ||
    (view !== null && LEGACY_VIEWS.has(view)) ||
    sort === "section";
  if (!legacy) return null;
  const scope = params.get("scope");
  const text = params.get("search");
  const task = params.get("task");
  for (const key of ["scope", "view", "sort", "search", "task"]) {
    params.delete(key);
  }
  // The all-tasks page used to open "Für mich"; a list page all tasks.
  const mine = scope === "mine" || (!listId && scope !== "all");
  const filters: [string, string[]][] = [];
  let nextView: string | null = mine ? "mine" : "open";
  const scoped = (...rest: [string, string[]][]) => {
    filters.push(["status", ["open"]], ...rest);
    if (mine) filters.push(["assignee", [userId]]);
  };
  switch (view) {
    case "due-today":
      scoped(["due", ["today"]]);
      break;
    case "due-next":
      scoped(["due", ["week"]]);
      break;
    case "deferred":
      scoped(["deferral", ["deferred"]]);
      break;
    case "done":
      nextView = "done";
      if (mine) filters.push(["status", ["done"]], ["assignee", [userId]]);
      break;
    case "plan-today":
    case "plan-planned":
    case "plan-someday":
      if (listId) break;
      nextView = "plan";
      filters.push([
        "plan",
        view === "plan-today"
          ? ["today", "due"]
          : view === "plan-planned"
            ? ["week", "later"]
            : ["someday"],
      ]);
      break;
    default:
      break;
  }
  if (nextView) params.set("view", nextView);
  for (const [prop, values] of filters) {
    for (const value of values) params.append(`f.${prop}`, value);
  }
  const planView = nextView === "plan";
  if (!planView && (sort === "created" || sort === "due")) {
    params.set("sort", sort);
    params.set("group", "none");
  } else if (!planView && sort === "section") {
    params.set("sort", "created");
    params.set("group", "epic");
  } else if (!planView && sort === "manual" && listId) {
    params.set("sort", "manual");
    params.set("group", "epic");
  }
  if (text) params.set("q", text);
  if (task) {
    params.set("open", task);
    // The task may be done or someone else's: show it in a view that has it.
    if (!view) params.set("view", listId ? "all" : "lists");
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
