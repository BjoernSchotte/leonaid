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
import { quantityLabel, type OfferingUnit } from "../commitments/quantities";
import {
  BOARD_POLL_MS,
  clockMinutes,
  deliveryTimeRange,
  dropQuantities,
  longDay,
} from "./delivery-shared";
import {
  canSuggestOrder,
  moveStop,
  nearestNextOrder,
  placeStop,
  reconcileOrder,
  tourLengthKm,
  type TourPoint,
} from "./tour-model";
import { useOrderAutosave } from "./use-order-autosave";

/*
 * "Touren" (spec krapfentaxi-touren §6): the manager's view of one delivery
 * day. "Nicht zugeordnet" and one column per driver; each column groups its
 * stops by window, and stops are ordered only inside their window. Every
 * move saves at once with "Rückgängig" on the toast, as in the driver view
 * (D16, D19 2a). Web only, "Sie".
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
  allAssigned: "Alle Stopps zugeordnet.",
  emptyLane:
    "Noch keine Stopps. Ziehen Sie welche hierher oder nutzen Sie „Fahrer zuordnen“.",
  assign: "Fahrer zuordnen",
  clearSelection: "Auswahl aufheben",
  suggest: "Vorschlag sortieren",
  suggestMissing: "Für den Vorschlag fehlen Koordinaten.",
  suggestHint: "Je Fenster der nächste Stopp zuerst, nach Luftlinie.",
  saved: (lane: string) => `Reihenfolge für ${lane} gespeichert.`,
  undone: (lane: string) =>
    `Vorherige Reihenfolge für ${lane} wiederhergestellt.`,
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

/** Answers that mean "what you see is old": reload the columns. */
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

const stopCount = (count: number) =>
  `${count} ${count === 1 ? "Stopp" : "Stopps"}`;

/** "12,4 km", or null while fewer than two stops have coordinates. */
function lengthLabel(points: readonly TourPoint[]) {
  const located = points.filter(
    (point) => point.lat !== null && point.lon !== null,
  );
  if (located.length < 2) return null;
  const km = tourLengthKm(points, null);
  return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 }).format(km)} km`;
}

/** "3 Stopps, 2 Boxen, 42 Stk": the load of one window in a column. */
function windowLoad(drops: readonly DeliveryDropResponse[]) {
  const live = drops.filter((drop) => drop.orderStatus !== "cancelled");
  const totals = new Map<OfferingUnit, number>();
  for (const drop of live) {
    const items = drop.quantities.length
      ? drop.quantities
      : [{ quantity: drop.totalBoxes, unit: "box" as const }];
    for (const item of items) {
      totals.set(item.unit, (totals.get(item.unit) ?? 0) + item.quantity);
    }
  }
  const units = [...totals].map(
    ([unit, quantity]) =>
      `${quantity} ${unit === "piece" ? "Stk" : quantityLabel(quantity, unit)}`,
  );
  return [stopCount(live.length), ...units].join(", ");
}

export interface TourPlannerProps {
  readonly client: LeonAidApiClient;
  readonly actionId: string;
  /** The delivery day (ISO); null lets the server pick the next one. */
  readonly day: string | null;
  readonly onDayChange: (day: string) => void;
  /** The "Liste" / "Touren" switch; a waiting move is sent first. */
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
  const sensors = useOrderingSensors();

  const [viewing, setViewing] = useState<ReadonlySet<string>>(new Set());
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [assignOpen, setAssignOpen] = useState(false);
  const [discarding, setDiscarding] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const assignAnchor = useRef<HTMLButtonElement | null>(null);

  const queryKey = ["delivery-tours", actionId, day] as const;
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

  // Save on drop (D19 2a): each move saves after a short pause, with the
  // revision it started from; a conflict reloads the columns.
  const laneName = (key: string) =>
    planModel(
      queries.getQueryData<DeliveryDayToursResponse>(queryKey),
    ).lanes.find((lane) => lane.key === key)?.name ?? "";
  const autosave = useOrderAutosave<DeliveryTourResponse>({
    save: (key, ids, revision) => {
      const current = queries.getQueryData<DeliveryDayToursResponse>(queryKey);
      const tour = current?.tours.find((item) => item.driverUserId === key);
      return client.saveDeliveryTourOrder(actionId, key, {
        commitmentIds: [...ids],
        day: tour?.day ?? current?.day ?? day ?? "",
        expectedRevision: revision,
      });
    },
    revisionOf: (saved) => saved.revision,
    onSaved: (_key, updated) => {
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
      void queries.invalidateQueries({
        queryKey: ["delivery-board", actionId],
      });
    },
    onFailed: (_key, error) => {
      showError(error);
      if (isStale(error)) void refresh();
    },
    savedText: (key) => copy.saved(laneName(key)),
    undoneText: (key) => copy.undone(laneName(key)),
  });
  const saving = autosave.dirty;
  useLeaveGuard(saving);

  const toursQuery = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getDeliveryTours(actionId, { day }),
    queryKey,
    // As the list: follow the drivers' ticks, but not while a move saves,
    // so the columns do not jump back under the manager's hand.
    refetchInterval: saving ? false : BOARD_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: !saving,
    retry: false,
  });
  const data = toursQuery.data;
  const zone = data?.timezone ?? "Europe/Berlin";
  const model = useMemo(() => planModel(data), [data]);
  const lanes = model.lanes;
  const laneByKey = new Map(lanes.map((lane) => [lane.key, lane]));
  const windowOf = (id: string) => model.stops.get(id)?.window.windowId ?? "";

  const shownOf = (lane: PlanLane) => {
    if (viewing.has(lane.key) && lane.tour?.driverOrderedAt) {
      return lane.effective;
    }
    const pending = autosave.orderOf(lane.key);
    return pending ? reconcileOrder(pending, lane.base, windowOf) : lane.base;
  };
  const isViewingDriver = (lane: PlanLane) =>
    viewing.has(lane.key) && Boolean(lane.tour?.driverOrderedAt);

  const moveTo = (lane: PlanLane, next: readonly string[], id?: string) => {
    if (!lane.tour) return;
    const current = shownOf(lane);
    if (sameOrder(next, current)) return;
    autosave.move(lane.key, next, current, lane.tour.revision);
    const stop = id ? model.stops.get(id) : undefined;
    if (stop && id) {
      setAnnouncement(
        `${stop.drop.buyerName} ist jetzt Stopp ${next.indexOf(id) + 1} bei ${lane.name}.`,
      );
    }
  };

  /** Sends waiting moves first, then runs `leave` (day or view change). */
  const guarded = (leave: () => void) => {
    for (const lane of lanes) autosave.flush(lane.key);
    leave();
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
    onSettled: () => refresh(),
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
    onSettled: () => refresh(),
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
    moveTo(lane, placeStop(ids, id, overId, side, windowOf), id);
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
          {/* One hint line: what to do while stops wait, else the rule. */}
          <p className="page-sub" data-testid="tour-plan-hint">
            {unassignedCount ? copy.unassignedHint : copy.intro}
          </p>
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
          ) : null}
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
                  busy={assign.isPending}
                  key={lane.key}
                  lane={lane}
                  onDiscardDriverOrder={() => setDiscarding(lane.key)}
                  onMove={(id, direction) =>
                    moveTo(
                      lane,
                      moveStop(shownOf(lane), id, direction, windowOf),
                      id,
                    )
                  }
                  onSuggest={(ids) => moveTo(lane, ids)}
                  onToggleSelected={toggleSelected}
                  onToggleViewing={() =>
                    setViewing((current) => {
                      const next = new Set(current);
                      if (next.has(lane.key)) next.delete(lane.key);
                      else next.add(lane.key);
                      return next;
                    })
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
    </div>
  );
}

interface LaneProps {
  readonly lane: PlanLane;
  readonly shown: readonly string[];
  readonly stops: ReadonlyMap<string, PlanStop>;
  readonly selected: ReadonlySet<string>;
  readonly viewingDriver: boolean;
  readonly busy: boolean;
  readonly zone: string;
  readonly onMove: (id: string, direction: -1 | 1) => void;
  readonly onSuggest: (ids: string[]) => void;
  readonly onToggleSelected: (id: string) => void;
  readonly onToggleViewing: () => void;
  readonly onDiscardDriverOrder: () => void;
}

/** One column: head with count, load per window and actions, then the windows. */
function Lane({
  busy,
  lane,
  onDiscardDriverOrder,
  onMove,
  onSuggest,
  onToggleSelected,
  onToggleViewing,
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
  // Coordinates arrive with geocoding (stage 1b); until then none.
  const points: TourPoint[] = shown.map((id) => ({
    id,
    windowId: stops.get(id)?.window.windowId ?? "",
    lat: null,
    lon: null,
  }));
  const suggestable = canSuggestOrder(points);
  const length = lengthLabel(points);
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
              {length ? (
                <>
                  <span data-testid="tour-length">Strecke {length}</span>
                  <span aria-hidden="true">·</span>
                </>
              ) : null}
              <span className="num">
                {done} von {count} erledigt
              </span>
            </p>
            <ul className="tour-lane-load" data-testid="tour-load">
              {lane.windows.map((window) => {
                const drops = shown
                  .map((id) => stops.get(id))
                  .filter(
                    (stop): stop is PlanStop =>
                      stop?.window.windowId === window.windowId,
                  )
                  .map((stop) => stop.drop);
                return drops.length ? (
                  <li className="num" key={window.windowId}>
                    {deliveryTimeRange(window, zone)}: {windowLoad(drops)}
                  </li>
                ) : null;
              })}
            </ul>
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
          {dropQuantities(drop)}
        </span>
      </label>
      {orderable ? (
        <span className="tour-stop-tools">
          <IconButton
            className={first ? "is-edge" : undefined}
            disabled={busy || first}
            focusableWhenDisabled
            icon={ArrowUp}
            label={`${name} nach oben`}
            onClick={() => onMove(-1)}
            size="sm"
          />
          <IconButton
            className={last ? "is-edge" : undefined}
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
