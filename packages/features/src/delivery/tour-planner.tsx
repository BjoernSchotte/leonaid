import {
  closestCenter,
  DndContext,
  useDroppable,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import {
  ArrowDown,
  ArrowUp,
  Eye,
  EyeOff,
  MailPlus,
  Route,
  Save,
  Truck,
  Undo2,
  UserRound,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState, type MouseEvent } from "react";

import {
  ApiError,
  type DeliveryDayToursResponse,
  type DeliveryDropResponse,
  type DeliveryTourResponse,
  type DeliveryTourWindowResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  Button,
  buttonClassName,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Icon,
  IconButton,
  NextStep,
  OptionMenu,
  Popover,
  SkeletonRows,
  StatusIcon,
  StatusMessage,
  cn,
  useDiscardDialog,
  useLeaveGuard,
  useOptionalToast,
} from "@leonaid/ui";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";

import { actionErrorMessage } from "../action-admin/errors";
import { formatDateTime } from "../shared/dates";
import {
  orderingAccessibility,
  TaskOrderHandle,
  useOrderingSensors,
} from "../tasks/task-ordering";
import {
  BOARD_POLL_MS,
  clockMinutes,
  deliveryTimeRange,
  longDay,
} from "./delivery-shared";
import {
  canSuggestOrder,
  moveStop,
  nearestNextOrder,
  placeStop,
  tourLengthKm,
  type TourPoint,
} from "./tour-model";

/*
 * "Touren" (spec krapfentaxi-touren §6): the manager's view of one delivery
 * day. "Nicht zugeordnet" and one column per driver; each column groups its
 * stops by window, and stops are ordered only inside their window. A moved
 * column keeps a local draft until "Reihenfolge speichern". Web only, "Sie".
 * The map (§6.1, right side) and pins come with geocoding (stage 1b).
 */

/** The column key of the stops without a driver. */
const UNASSIGNED = "none";
const LANE_PREFIX = "lane:";

const copy = {
  intro:
    "Eine Tour je Fahrer und Liefertag. Sortiert wird nur innerhalb eines Lieferfensters, so bleibt jedes zugesagte Zeitfenster.",
  unassigned: "Nicht zugeordnet",
  unassignedHint:
    "Wählen Sie Stopps aus und ordnen Sie sie einem Fahrer zu, oder ziehen Sie sie in eine Spalte.",
  allAssigned: "Alles zugeordnet.",
  emptyLane:
    "Noch keine Stopps. Ziehen Sie welche hierher oder nutzen Sie „Fahrer zuordnen“.",
  assign: "Fahrer zuordnen",
  clearSelection: "Auswahl aufheben",
  suggest: "Vorschlag sortieren",
  suggestMissing: "Für den Vorschlag fehlen Koordinaten.",
  suggestHint: "Je Fenster der nächste Stopp zuerst, nach Luftlinie.",
  save: "Reihenfolge speichern",
  discardDraft: "Änderung verwerfen",
  unsaved: "Nicht gespeichert",
  driverOrder: (since: string) =>
    `Fahrer hat eigene Reihenfolge (seit ${since})`,
  viewingDriverOrder: (since: string) =>
    `Sie sehen die eigene Reihenfolge des Fahrers (seit ${since}). Sie ist nur lesbar.`,
  show: "anzeigen",
  showPlan: "Planung anzeigen",
  discard: "verwerfen",
  closed: "Abgeschlossen",
  isNew: "neu",
  notEnabled: "Für diese Aktion ist keine Lieferplanung aktiv.",
  error: "Die Touren konnten nicht geladen werden.",
  stale: "Die Touren konnten nicht aktualisiert werden.",
  codes: {
    delivery_window_closed:
      "Dieses Lieferfenster ist abgeschlossen. Zum Ändern öffnen Sie es in der Liste wieder.",
    delivery_state_conflict:
      "Diese Lieferung wurde inzwischen geändert. Die Touren zeigen jetzt den aktuellen Stand.",
    delivery_order_not_deliverable:
      "Diese Bestellung wird nicht (mehr) ausgeliefert.",
    delivery_management_required: "Das darf nur, wer die Aktion verwaltet.",
    tour_revision_conflict:
      "Die Tour wurde inzwischen geändert. Die Touren zeigen jetzt den aktuellen Stand.",
    tour_order_stale:
      "Die Tour wurde inzwischen geändert. Die Touren zeigen jetzt den aktuellen Stand.",
  },
} as const;

type ErrorCode = keyof typeof copy.codes;

/** Answers that mean "what you see is old": drop the draft and reload. */
const STALE_CODES: ReadonlySet<string> = new Set([
  "delivery_state_conflict",
  "tour_revision_conflict",
  "tour_order_stale",
]);

interface PlanStop {
  readonly drop: DeliveryDropResponse;
  readonly window: DeliveryTourWindowResponse;
  readonly lane: string;
  readonly newForDriver: boolean;
}

interface PlanLane {
  readonly key: string;
  readonly name: string;
  /** Null for "Nicht zugeordnet". */
  readonly tour: DeliveryTourResponse | null;
  readonly windows: readonly DeliveryTourWindowResponse[];
  /** The manager's base order (unassigned: the board's order). */
  readonly base: readonly string[];
  /** What the driver sees: their own order where set, else the base. */
  readonly effective: readonly string[];
}

interface Draft {
  readonly ids: readonly string[];
  /** The tour revision the draft started from; saving sends it. */
  readonly revision: string;
}

const byStart = (
  a: DeliveryTourWindowResponse,
  b: DeliveryTourWindowResponse,
) => Date.parse(a.startsAt) - Date.parse(b.startsAt);

function orderOf(
  windows: readonly DeliveryTourWindowResponse[],
  rank: "baseRank" | "effectiveRank",
) {
  return windows.flatMap((window) =>
    [...window.stops]
      .sort((a, b) => a[rank] - b[rank])
      .map((stop) => stop.drop.commitmentId),
  );
}

function laneOf(
  key: string,
  name: string,
  tour: DeliveryTourResponse | null,
  windows: readonly DeliveryTourWindowResponse[],
): PlanLane {
  const sorted = [...windows].sort(byStart);
  return {
    key,
    name,
    tour,
    windows: sorted,
    base: orderOf(sorted, "baseRank"),
    effective: orderOf(sorted, "effectiveRank"),
  };
}

/** "Nicht zugeordnet", then the action's drivers, then former drivers. */
function planModel(data: DeliveryDayToursResponse | undefined) {
  const lanes: PlanLane[] = [];
  const stops = new Map<string, PlanStop>();
  if (!data) return { lanes, stops };
  lanes.push(laneOf(UNASSIGNED, copy.unassigned, null, data.unassigned));
  const tours = new Map(data.tours.map((tour) => [tour.driverUserId, tour]));
  for (const driver of data.drivers) {
    const tour = tours.get(driver.userId) ?? null;
    tours.delete(driver.userId);
    lanes.push(
      laneOf(driver.userId, driver.displayName, tour, tour?.windows ?? []),
    );
  }
  for (const tour of tours.values()) {
    lanes.push(laneOf(tour.driverUserId, tour.driverName, tour, tour.windows));
  }
  for (const lane of lanes) {
    for (const window of lane.windows) {
      for (const stop of window.stops) {
        stops.set(stop.drop.commitmentId, {
          drop: stop.drop,
          lane: lane.key,
          newForDriver: stop.newForDriver,
          window,
        });
      }
    }
  }
  return { lanes, stops };
}

const sameOrder = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((id, index) => id === b[index]);

/** A draft kept to the tour's current stops; stops added since go last in their window. */
const reconcile = (
  draft: readonly string[],
  base: readonly string[],
  windowOf: (id: string) => string,
) => {
  // Window by window, in the base's window order: a stop added since the
  // draft goes to the end of its own window, not of the whole tour.
  const windows = [...new Set(base.map(windowOf))];
  return windows.flatMap((window) => {
    const current = base.filter((id) => windowOf(id) === window);
    const known = draft.filter((id) => current.includes(id));
    return [...known, ...current.filter((id) => !known.includes(id))];
  });
};

const boxes = (count: number) => `${count} ${count === 1 ? "Box" : "Boxen"}`;
const stopCount = (count: number) =>
  `${count} ${count === 1 ? "Stopp" : "Stopps"}`;

/** "12,4 km", or "–" while fewer than two stops have coordinates. */
function lengthLabel(points: readonly TourPoint[]) {
  const located = points.filter(
    (point) => point.lat !== null && point.lon !== null,
  );
  if (located.length < 2) return "–";
  const km = tourLengthKm(points, null);
  return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 }).format(km)} km`;
}

export interface TourPlannerProps {
  readonly client: LeonAidApiClient;
  readonly actionId: string;
  /** The delivery day (ISO); null lets the server pick the next one. */
  readonly day: string | null;
  readonly onDayChange: (day: string) => void;
  /** The "Liste" / "Touren" switch; leaving with a draft asks first. */
  readonly onShowList?: () => void;
}

export function TourPlanner({
  actionId,
  client,
  day,
  onDayChange,
  onShowList,
}: TourPlannerProps) {
  const queries = useQueryClient();
  const toast = useOptionalToast();
  const { confirmDiscard, dialog: discardDialog } = useDiscardDialog("Sie");
  const sensors = useOrderingSensors();

  /** Changed columns only: a draft equal to the base order is dropped. */
  const [drafts, setDrafts] = useState<Readonly<Record<string, Draft>>>({});
  const [viewing, setViewing] = useState<ReadonlySet<string>>(new Set());
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [assignOpen, setAssignOpen] = useState(false);
  const [discarding, setDiscarding] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const assignAnchor = useRef<HTMLButtonElement | null>(null);

  const dirty = Object.keys(drafts).length > 0;
  useLeaveGuard(dirty);

  const queryKey = ["delivery-tours", actionId, day] as const;
  const toursQuery = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getDeliveryTours(actionId, { day }),
    queryKey,
    // As the list: follow the drivers' ticks, but never under a draft, so
    // the columns do not move while the manager orders them.
    refetchInterval: dirty ? false : BOARD_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: !dirty,
    retry: false,
  });
  const data = toursQuery.data;
  const zone = data?.timezone ?? "Europe/Berlin";
  const model = useMemo(() => planModel(data), [data]);
  const lanes = model.lanes;
  const laneByKey = new Map(lanes.map((lane) => [lane.key, lane]));
  const windowOf = (id: string) => model.stops.get(id)?.window.windowId ?? "";

  const mutationOptions = { mutationKey: ["delivery-tours", actionId] };
  const refresh = () =>
    Promise.all([
      queries.invalidateQueries({ queryKey: ["delivery-tours", actionId] }),
      queries.invalidateQueries({ queryKey: ["delivery-board", actionId] }),
    ]);
  const errorText = (error: unknown) => {
    const shared = actionErrorMessage(error, { address: "Sie" });
    const code = shared.code as ErrorCode | null;
    return code && code in copy.codes ? copy.codes[code] : shared.message;
  };
  const isStale = (error: unknown) =>
    error instanceof ApiError && STALE_CODES.has(error.detail.code);
  const showError = (error: unknown) =>
    toast?.show({ title: errorText(error), tone: "error" });

  /** The draft of a column, kept to its current stops, or null. */
  const draftOf = (lane: PlanLane) => {
    const draft = drafts[lane.key];
    return draft ? reconcile(draft.ids, lane.base, windowOf) : null;
  };
  const shownOf = (lane: PlanLane) =>
    viewing.has(lane.key) && lane.tour?.driverOrderedAt
      ? lane.effective
      : (draftOf(lane) ?? lane.base);
  const isViewingDriver = (lane: PlanLane) =>
    viewing.has(lane.key) && Boolean(lane.tour?.driverOrderedAt);

  const setDraft = (lane: PlanLane, ids: readonly string[]) => {
    if (!lane.tour) return;
    const revision = drafts[lane.key]?.revision ?? lane.tour.revision;
    setDrafts((current) => {
      const next = { ...current };
      if (sameOrder(ids, lane.base)) delete next[lane.key];
      else next[lane.key] = { ids, revision };
      return next;
    });
  };
  const dropDraft = (key: string) =>
    setDrafts((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  /**
   * After the manager's own change to a column (assign, discard), its
   * draft follows the new revision; a change by someone else still
   * conflicts on save.
   */
  const rebase = (keys: Iterable<string>) => {
    const fresh = queries.getQueryData<DeliveryDayToursResponse>(queryKey);
    const revisions = new Map(
      fresh?.tours.map((tour) => [tour.driverUserId, tour.revision]) ?? [],
    );
    setDrafts((current) => {
      let changed = false;
      const next = { ...current };
      for (const key of keys) {
        const draft = next[key];
        const revision = revisions.get(key);
        if (draft && revision && revision !== draft.revision) {
          next[key] = { ...draft, revision };
          changed = true;
        }
      }
      return changed ? next : current;
    });
  };

  const moveInDraft = (lane: PlanLane, next: string[], id: string) => {
    setDraft(lane, next);
    const stop = model.stops.get(id);
    if (stop) {
      setAnnouncement(
        `${stop.drop.buyerName} ist jetzt Stopp ${next.indexOf(id) + 1} bei ${lane.name}.`,
      );
    }
  };

  /** Asks before an unsaved draft is dropped, then runs `leave`. */
  const guarded = (leave: () => void) => {
    if (!dirty) {
      leave();
      return;
    }
    void confirmDiscard().then((discard) => {
      if (!discard) return;
      setDrafts({});
      leave();
    });
  };

  const assign = useMutation({
    ...mutationOptions,
    mutationFn: ({
      ids,
      driverUserId,
    }: {
      ids: readonly string[];
      driverUserId: string | null;
    }) =>
      client.assignDeliveryDriver(actionId, {
        commitmentIds: [...ids],
        driverUserId,
      }),
    onSuccess: (_result, { ids, driverUserId }) => {
      setAssignOpen(false);
      setSelected(new Set());
      const target = driverUserId ? laneByKey.get(driverUserId) : null;
      toast?.show({
        title: target
          ? `${stopCount(ids.length)} ${target.name} zugeordnet. Sie stehen am Ende ihres Fensters.`
          : `Fahrer entfernt (${stopCount(ids.length)}).`,
        tone: "success",
      });
    },
    onError: showError,
    onSettled: async (_result, _error, { ids, driverUserId }) => {
      const touched = new Set<string>(driverUserId ? [driverUserId] : []);
      for (const id of ids) {
        const lane = model.stops.get(id)?.lane;
        if (lane) touched.add(lane);
      }
      await refresh();
      rebase(touched);
    },
  });

  const saveOrder = useMutation({
    ...mutationOptions,
    mutationFn: ({
      lane,
      ids,
      draft,
    }: {
      lane: PlanLane;
      ids: readonly string[];
      draft: Draft;
    }) =>
      client.saveDeliveryTourOrder(actionId, lane.key, {
        commitmentIds: [...ids],
        day: lane.tour!.day,
        expectedRevision: draft.revision,
      }),
    onSuccess: (updated, { lane }) => {
      queries.setQueryData<DeliveryDayToursResponse>(queryKey, (current) =>
        current
          ? {
              ...current,
              tours: current.tours.map((tour) =>
                tour.driverUserId === updated.driverUserId ? updated : tour,
              ),
            }
          : current,
      );
      dropDraft(lane.key);
      toast?.show({
        title: `Reihenfolge für ${lane.name} gespeichert.`,
        tone: "success",
      });
      void refresh();
    },
    onError: (error, { lane }) => {
      showError(error);
      // A changed tour: show the current one. Other failures (network)
      // keep the draft for another try.
      if (isStale(error)) {
        dropDraft(lane.key);
        void refresh();
      }
    },
  });

  const discardDriverOrder = useMutation({
    ...mutationOptions,
    mutationFn: (lane: PlanLane) =>
      client.discardDeliveryDriverOrder(actionId, lane.key, {
        day: lane.tour!.day,
      }),
    onSuccess: (_updated, lane) => {
      setDiscarding(null);
      setViewing((current) => {
        const next = new Set(current);
        next.delete(lane.key);
        return next;
      });
      toast?.show({
        title: `Eigene Reihenfolge von ${lane.name} verworfen. Es gilt wieder die Planung.`,
        tone: "success",
      });
    },
    onError: (error) => {
      setDiscarding(null);
      showError(error);
    },
    onSettled: async (_updated, _error, lane) => {
      await refresh();
      rebase([lane.key]);
    },
  });

  const finishDrag = ({ active, over }: DragEndEvent) => {
    if (!over) return;
    const id = String(active.id);
    const overId = String(over.id);
    const from = model.stops.get(id);
    if (!from) return;
    const target = overId.startsWith(LANE_PREFIX)
      ? overId.slice(LANE_PREFIX.length)
      : model.stops.get(overId)?.lane;
    if (!target) return;
    if (target !== from.lane) {
      // Onto another column: the existing driver assignment.
      if (!laneByKey.has(target) || assign.isPending) return;
      assign.mutate({
        ids: [id],
        driverUserId: target === UNASSIGNED ? null : target,
      });
      return;
    }
    const lane = laneByKey.get(target);
    if (!lane?.tour || overId === id || isViewingDriver(lane)) return;
    const ids = shownOf(lane);
    const side = ids.indexOf(id) < ids.indexOf(overId) ? "after" : "before";
    // placeStop ignores a target in another window.
    const next = placeStop(ids, id, overId, side, windowOf);
    if (!sameOrder(next, ids)) moveInDraft(lane, next, id);
  };

  const toggleSelected = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  // Stops that left the day or whose window closed drop out of the choice.
  const selectedIds = [...selected].filter((id) => {
    const stop = model.stops.get(id);
    return stop && !stop.window.closed;
  });
  const selectedLanes = new Set(
    selectedIds.map((id) => model.stops.get(id)!.lane),
  );
  const [onlyLane] = selectedLanes.size === 1 ? [...selectedLanes] : [];
  const driverOptions = [
    ...(data?.drivers ?? []).map((item) => ({
      value: item.userId,
      label: item.displayName,
      icon: <Avatar name={item.displayName} size="xs" />,
    })),
    { value: UNASSIGNED, label: "Kein Fahrer" },
  ];

  const notEnabled =
    toursQuery.error instanceof ApiError &&
    ["delivery_not_enabled", "feature_flag_disabled"].includes(
      toursQuery.error.detail.code,
    );
  const unassignedCount = laneByKey.get(UNASSIGNED)?.base.length ?? 0;
  const discardingLane = discarding ? laneByKey.get(discarding) : undefined;

  return (
    <div className="delivery tour-plan" data-zone="delivery">
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1>Auslieferung</h1>
            {data?.day ? (
              <span className="page-count">{longDay(data.day)}</span>
            ) : null}
          </div>
          <p className="page-sub">{copy.intro}</p>
        </div>
        <div className="delivery-filters">
          {data && data.days.length > 1 ? (
            <label className="driver-filter">
              <span>Liefertag</span>
              <select
                className="input select"
                data-testid="tour-day"
                onChange={(event) => {
                  const value = event.target.value;
                  guarded(() => {
                    setSelected(new Set());
                    setViewing(new Set());
                    onDayChange(value);
                  });
                }}
                value={data.day ?? ""}
              >
                {data.days.map((item) => (
                  <option key={item} value={item}>
                    {longDay(item)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {onShowList ? (
            <DeliveryViewSwitch
              onChange={(view) => {
                if (view === "list") guarded(onShowList);
              }}
              view="tours"
            />
          ) : null}
        </div>
      </header>

      {!actionId ? (
        <EmptyState
          description="Wählen Sie eine Charity-Aktion, um die Touren zu planen."
          headingLevel={2}
          icon={Truck}
          title="Keine Aktion gewählt"
        />
      ) : toursQuery.isPending ? (
        <SkeletonRows rows={6} />
      ) : notEnabled ? (
        <EmptyState
          description={copy.notEnabled}
          headingLevel={2}
          icon={Truck}
          title="Keine Lieferplanung"
        />
      ) : toursQuery.isError && !data ? (
        <ErrorState
          onRetry={() => void toursQuery.refetch()}
          title={copy.error}
        >
          Prüfen Sie die Verbindung und versuchen Sie es erneut.
        </ErrorState>
      ) : !data?.day ? (
        <EmptyState
          description="Legen Sie Lieferfenster in der Aktion an. Gebuchte Bestellungen erscheinen dann hier."
          headingLevel={2}
          icon={Truck}
          title="Noch keine Lieferungen"
        />
      ) : (
        <>
          {toursQuery.isError ? (
            <StatusMessage className="delivery-stale" tone="warning">
              <strong>{copy.stale}</strong>
              <p>
                Angezeigt wird der Stand von{" "}
                {formatDateTime(
                  new Date(toursQuery.dataUpdatedAt).toISOString(),
                )}
                .
              </p>
              <Button
                loading={toursQuery.isFetching}
                onClick={() => void toursQuery.refetch()}
                size="sm"
                variant="secondary"
              >
                Jetzt neu laden
              </Button>
            </StatusMessage>
          ) : null}
          {unassignedCount && !data.drivers.length ? (
            <NextStep
              action={
                <a
                  className={buttonClassName({ variant: "primary" })}
                  href={`${ADMIN_BASE}members/invitations?action=${encodeURIComponent(actionId)}`}
                >
                  <Icon icon={MailPlus} size={16} />
                  <span>Ausfahrer einladen</span>
                </a>
              }
              consequence={`${stopCount(unassignedCount)} ohne Fahrer, und die Aktion hat noch keine Ausfahrer. Laden Sie jemanden mit der Rolle „Ausfahrer“ ein.`}
            />
          ) : null}

          {selectedIds.length ? (
            <div aria-label="Auswahl" className="bulkbar" role="region">
              <span className="num">{selectedIds.length} ausgewählt</span>
              <Button
                aria-expanded={assignOpen}
                aria-haspopup="dialog"
                disabled={!data.drivers.length && onlyLane === UNASSIGNED}
                icon={UserRound}
                loading={assign.isPending}
                onClick={() => setAssignOpen(true)}
                ref={assignAnchor}
                size="sm"
                variant="secondary"
              >
                {copy.assign}
              </Button>
              <Button
                onClick={() => setSelected(new Set())}
                size="sm"
                variant="ghost"
              >
                {copy.clearSelection}
              </Button>
            </div>
          ) : (
            <p className="tour-plan-hint">{copy.unassignedHint}</p>
          )}
          <p aria-live="polite" className="sr-only" role="status">
            {announcement}
          </p>

          <DndContext
            accessibility={orderingAccessibility("Stopp")}
            collisionDetection={closestCenter}
            onDragCancel={() => setAnnouncement("Verschieben abgebrochen.")}
            onDragEnd={finishDrag}
            sensors={sensors}
          >
            <div className="tour-lanes">
              {lanes.map((lane) => (
                <Lane
                  busy={assign.isPending || saveOrder.isPending}
                  draft={draftOf(lane)}
                  key={lane.key}
                  lane={lane}
                  onDiscardDraft={() => dropDraft(lane.key)}
                  onDiscardDriverOrder={() => setDiscarding(lane.key)}
                  onMove={(id, direction) =>
                    moveInDraft(
                      lane,
                      moveStop(shownOf(lane), id, direction, windowOf),
                      id,
                    )
                  }
                  onSave={() => {
                    const draft = drafts[lane.key];
                    const ids = draftOf(lane);
                    if (draft && ids) saveOrder.mutate({ lane, ids, draft });
                  }}
                  onSuggest={(ids) => {
                    setDraft(lane, ids);
                    toast?.show({
                      title: `Vorschlag für ${lane.name}: ${copy.suggestHint} Speichern Sie, um ihn zu übernehmen.`,
                      tone: "info",
                    });
                  }}
                  onToggleSelected={toggleSelected}
                  onToggleViewing={() =>
                    setViewing((current) => {
                      const next = new Set(current);
                      if (next.has(lane.key)) next.delete(lane.key);
                      else next.add(lane.key);
                      return next;
                    })
                  }
                  saving={
                    saveOrder.isPending &&
                    saveOrder.variables?.lane.key === lane.key
                  }
                  selected={selected}
                  shown={shownOf(lane)}
                  stops={model.stops}
                  viewingDriver={isViewingDriver(lane)}
                  zone={zone}
                />
              ))}
            </div>
          </DndContext>
        </>
      )}

      <Popover
        anchor={assignAnchor}
        label="Fahrer wählen"
        onClose={() => setAssignOpen(false)}
        open={assignOpen && selectedIds.length > 0}
      >
        <OptionMenu<string>
          onSelect={(value) => {
            if (assign.isPending || !selectedIds.length) return;
            assign.mutate({
              ids: selectedIds,
              driverUserId: value === UNASSIGNED ? null : value,
            });
          }}
          options={driverOptions}
          placeholder="Fahrer suchen"
          value={onlyLane ?? ""}
        />
      </Popover>

      <ConfirmDialog
        confirmLabel="Verwerfen"
        description={`Die eigene Reihenfolge von ${discardingLane?.name ?? "diesem Fahrer"} geht verloren. Für die Tour gilt dann wieder Ihre Planung.`}
        onConfirm={() => {
          if (discardingLane?.tour) discardDriverOrder.mutate(discardingLane);
        }}
        onOpenChange={(open) => {
          if (!open) setDiscarding(null);
        }}
        open={Boolean(discardingLane)}
        pending={discardDriverOrder.isPending}
        title="Fahrerreihenfolge verwerfen?"
        tone="danger"
      />
      {discardDialog}
    </div>
  );
}

interface LaneProps {
  readonly lane: PlanLane;
  readonly shown: readonly string[];
  readonly draft: readonly string[] | null;
  readonly stops: ReadonlyMap<string, PlanStop>;
  readonly selected: ReadonlySet<string>;
  readonly viewingDriver: boolean;
  readonly busy: boolean;
  readonly saving: boolean;
  readonly zone: string;
  readonly onMove: (id: string, direction: -1 | 1) => void;
  readonly onSave: () => void;
  readonly onDiscardDraft: () => void;
  readonly onSuggest: (ids: string[]) => void;
  readonly onToggleSelected: (id: string) => void;
  readonly onToggleViewing: () => void;
  readonly onDiscardDriverOrder: () => void;
}

/** One column: head with count, ends, length and actions, then the windows. */
function Lane({
  busy,
  draft,
  lane,
  onDiscardDraft,
  onDiscardDriverOrder,
  onMove,
  onSave,
  onSuggest,
  onToggleSelected,
  onToggleViewing,
  saving,
  selected,
  shown,
  stops,
  viewingDriver,
  zone,
}: LaneProps) {
  const unassigned = lane.key === UNASSIGNED;
  const count = shown.length;
  // Empty columns take a drop; filled ones take it on their stops.
  const { setNodeRef, isOver } = useDroppable({
    id: `${LANE_PREFIX}${lane.key}`,
    disabled: count > 0,
  });
  const headingId = `tour-lane-${lane.key}`;
  const dirty = draft !== null;
  // Coordinates arrive with geocoding (stage 1b); until then none.
  const points: TourPoint[] = shown.map((id) => ({
    id,
    windowId: stops.get(id)?.window.windowId ?? "",
    lat: null,
    lon: null,
  }));
  const suggestable = canSuggestOrder(points);
  const nameOf = (id: string | undefined) =>
    id ? (stops.get(id)?.drop.buyerName ?? "") : "";
  const done = shown.filter(
    (id) => stops.get(id)?.drop.state !== "open",
  ).length;
  const since = lane.tour?.driverOrderedAt
    ? clockMinutes(lane.tour.driverOrderedAt, zone)
    : null;
  const editable = !unassigned && !viewingDriver;

  return (
    <section
      aria-labelledby={headingId}
      className={cn(
        "tour-lane",
        unassigned && "is-unassigned",
        dirty && "is-dirty",
        isOver && "is-over",
      )}
      data-driver={unassigned ? undefined : lane.key}
      data-lane={lane.key}
      data-testid={unassigned ? "tour-unassigned" : "tour-column"}
      ref={setNodeRef}
    >
      <header className="tour-lane-head">
        <div className="tour-lane-title">
          {unassigned ? (
            <span aria-hidden="true" className="drop-driver-empty">
              <Icon icon={UserRound} size={14} />
            </span>
          ) : (
            <Avatar name={lane.name} size="sm" />
          )}
          <h2 id={headingId}>{lane.name}</h2>
          <span
            className="badge tone-neutral num"
            data-testid="tour-count"
            title="Stopps"
          >
            {count}
          </span>
        </div>
        {unassigned ? null : count ? (
          <>
            <p className="tour-lane-meta">
              <span data-testid="tour-length">
                Strecke {lengthLabel(points)}
              </span>
              <span aria-hidden="true">·</span>
              <span className="num">
                {done} von {count} erledigt
              </span>
            </p>
            <p className="tour-lane-meta" data-testid="tour-ends">
              Erster: {nameOf(shown[0])} · Letzter: {nameOf(shown.at(-1))}
            </p>
          </>
        ) : null}
        {since ? (
          <div
            className={cn("tour-lane-hint", viewingDriver && "is-viewing")}
            data-testid="tour-driver-order-banner"
            role="status"
          >
            <span>
              {viewingDriver
                ? copy.viewingDriverOrder(since)
                : `${copy.driverOrder(since)}.`}
            </span>
            <span className="tour-lane-hint-actions">
              <Button
                aria-pressed={viewingDriver}
                data-testid="tour-show-driver-order"
                icon={viewingDriver ? EyeOff : Eye}
                onClick={onToggleViewing}
                size="sm"
                variant="secondary"
              >
                {viewingDriver ? copy.showPlan : copy.show}
              </Button>
              <Button
                data-testid="tour-discard-driver-order"
                icon={Undo2}
                onClick={onDiscardDriverOrder}
                size="sm"
                variant="ghost"
              >
                {copy.discard}
              </Button>
            </span>
          </div>
        ) : null}
        {!unassigned && count ? (
          <div className="tour-lane-actions">
            <Button
              data-testid="tour-suggest-order"
              disabled={!suggestable || viewingDriver || busy}
              focusableWhenDisabled
              icon={Route}
              onClick={() => onSuggest(nearestNextOrder(points, null))}
              size="sm"
              title={suggestable ? copy.suggestHint : copy.suggestMissing}
              variant="secondary"
            >
              {copy.suggest}
            </Button>
            <Button
              data-testid="tour-save-order"
              disabled={!dirty || viewingDriver}
              focusableWhenDisabled
              icon={Save}
              loading={saving}
              onClick={onSave}
              size="sm"
              variant={dirty ? "primary" : "secondary"}
            >
              {copy.save}
            </Button>
            {dirty ? (
              <>
                <Button
                  disabled={saving}
                  onClick={onDiscardDraft}
                  size="sm"
                  variant="ghost"
                >
                  {copy.discardDraft}
                </Button>
                <Badge tone="warn">{copy.unsaved}</Badge>
              </>
            ) : null}
          </div>
        ) : null}
      </header>

      {count === 0 ? (
        <p className="tour-lane-empty">
          {unassigned ? copy.allAssigned : copy.emptyLane}
        </p>
      ) : (
        lane.windows.map((window) => {
          const ids = shown.filter(
            (id) => stops.get(id)?.window.windowId === window.windowId,
          );
          if (!ids.length) return null;
          const movable = !window.closed && (unassigned || editable);
          const rows = (
            <ol className="tour-lane-stops">
              {ids.map((id, index) => (
                <StopRow
                  busy={busy}
                  first={index === 0}
                  key={id}
                  last={index === ids.length - 1}
                  movable={movable}
                  onMove={(direction) => onMove(id, direction)}
                  onToggleSelected={() => onToggleSelected(id)}
                  orderable={editable && !window.closed}
                  position={unassigned ? null : shown.indexOf(id) + 1}
                  selected={selected.has(id)}
                  showNew={viewingDriver}
                  stop={stops.get(id)!}
                />
              ))}
            </ol>
          );
          return (
            <div
              className={cn("tour-lane-window", window.closed && "is-closed")}
              data-testid="tour-window"
              key={window.windowId}
            >
              <div className="tour-lane-window-head">
                <h3>{deliveryTimeRange(window, zone)} Uhr</h3>
                <span className="small muted num">{stopCount(ids.length)}</span>
                {window.closed ? (
                  <span className="stamp tone-ok">{copy.closed}</span>
                ) : null}
              </div>
              {movable ? (
                <SortableContext
                  items={ids}
                  strategy={verticalListSortingStrategy}
                >
                  {rows}
                </SortableContext>
              ) : (
                rows
              )}
            </div>
          );
        })
      )}
    </section>
  );
}

/** One stop: choose, grip, number, name, and up/down inside its window. */
function StopRow({
  busy,
  first,
  last,
  movable,
  onMove,
  onToggleSelected,
  orderable,
  position,
  selected,
  showNew,
  stop,
}: {
  readonly busy: boolean;
  readonly first: boolean;
  readonly last: boolean;
  /** Draggable: to another column, and inside the window when orderable. */
  readonly movable: boolean;
  readonly orderable: boolean;
  readonly onMove: (direction: -1 | 1) => void;
  readonly onToggleSelected: () => void;
  readonly position: number | null;
  readonly selected: boolean;
  readonly showNew: boolean;
  readonly stop: PlanStop;
}) {
  const { drop } = stop;
  const name = drop.buyerName;
  const checkId = `tour-check-${drop.commitmentId}`;
  const recipient =
    drop.address?.recipientName && drop.address.recipientName !== name
      ? drop.address.recipientName
      : null;
  const stateLabel =
    drop.state === "delivered"
      ? "Zugestellt"
      : drop.state === "missed"
        ? "Nicht angetroffen"
        : null;
  const choosable = !stop.window.closed;
  return (
    <li
      className={cn(
        "row tour-stop",
        selected && choosable && "is-checked",
        drop.state !== "open" && "is-done",
      )}
      data-commitment-id={drop.commitmentId}
      data-testid="tour-stop"
    >
      {choosable ? (
        <input
          aria-label={`${name} auswählen`}
          checked={selected}
          className="tour-stop-check"
          id={checkId}
          onChange={onToggleSelected}
          type="checkbox"
        />
      ) : (
        <span aria-hidden="true" className="tour-stop-check-space" />
      )}
      {movable ? (
        <TaskOrderHandle
          disabled={busy}
          id={drop.commitmentId}
          noun="Stopp"
          title={name}
        />
      ) : (
        <span aria-hidden="true" className="task-handle-space" />
      )}
      {position !== null ? (
        <span className="tour-pos num">{position}</span>
      ) : null}
      <label
        className="tour-stop-main"
        htmlFor={choosable ? checkId : undefined}
      >
        <span className="tour-stop-name">
          <span data-testid="tour-stop-name">{name}</span>
          {showNew && stop.newForDriver ? <Badge tone="zone">neu</Badge> : null}
          {stateLabel ? (
            <span className="tour-stop-state">
              <StatusIcon
                label={stateLabel}
                size={14}
                status={drop.state === "delivered" ? "done" : "alert"}
              />
            </span>
          ) : null}
        </span>
        <span className="tour-stop-sub">
          {recipient ? `${recipient}, ` : ""}
          {drop.address?.streetLine1 ?? "Keine Lieferadresse"} ·{" "}
          {boxes(drop.totalBoxes)}
        </span>
      </label>
      {orderable ? (
        <span className="tour-stop-tools">
          <IconButton
            disabled={busy || first}
            focusableWhenDisabled
            icon={ArrowUp}
            label={`${name} nach oben`}
            onClick={() => onMove(-1)}
            size="sm"
          />
          <IconButton
            disabled={busy || last}
            focusableWhenDisabled
            icon={ArrowDown}
            label={`${name} nach unten`}
            onClick={() => onMove(1)}
            size="sm"
          />
        </span>
      ) : null}
    </li>
  );
}

export type DeliveryView = "list" | "tours";

/** "Liste" / "Touren" on the web delivery page, kept in `?view=`. */
export function DeliveryViewSwitch({
  onChange,
  view,
}: {
  readonly onChange: (view: DeliveryView) => void;
  readonly view: DeliveryView;
}) {
  const href = (target: DeliveryView) => {
    const url = new URL(window.location.href);
    if (target === "tours") url.searchParams.set("view", "tours");
    else url.searchParams.delete("view");
    return `${url.pathname}${url.search}`;
  };
  const link = (target: DeliveryView, label: string) => (
    <a
      aria-current={view === target ? "page" : undefined}
      data-testid={`delivery-view-${target}`}
      href={href(target)}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        // A new tab (modifier, middle click) keeps the plain link.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
          return;
        event.preventDefault();
        if (view !== target) onChange(target);
      }}
    >
      {label}
    </a>
  );
  return (
    <nav aria-label="Ansicht" className="section-links delivery-view-switch">
      {link("list", "Liste")}
      {link("tours", "Touren")}
    </nav>
  );
}
