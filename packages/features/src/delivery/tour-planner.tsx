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
  MapPin,
  MapPinPlus,
  Route,
  Truck,
  Undo2,
  UserRound,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

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
import { DriverNote } from "./driver-note";
import {
  canSuggestOrder,
  moveStop,
  nearestNextOrder,
  placeStop,
  reconcileOrder,
  tourLengthKm,
  type TourPoint,
} from "./tour-model";
import { driverTone, TourMap, type TourMapPin } from "./tour-map";
import { useOrderAutosave } from "./use-order-autosave";

/*
 * "Touren" (spec krapfentaxi-touren §6): the manager's view of one delivery
 * day. "Nicht zugeordnet" and one column per driver; each column groups its
 * stops by window, and stops are ordered only inside their window. Every
 * move saves at once with "Rückgängig" on the toast, as in the driver view
 * (D16, D19 2a). Web only, "Sie".
 * The map on the right (§6.1): every stop of the day, coloured by driver,
 * numbered by effective order; list and pins select each other. A move
 * still saving shows as a dashed line. A stop without coordinates gets its
 * pin by a click on the map (§6.4).
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
  mapLabel: "Karte der Touren",
  mapHint: "Wählen Sie Stopps in der Liste oder auf der Karte.",
  noPins:
    "Noch kein Stopp hat einen Kartenpunkt. Die Adressen werden gerade gesucht, oder Sie setzen die Pins selbst.",
  notFound: "Adresse nicht gefunden",
  setPin: "Pin setzen",
  movePin: "Pin versetzen",
  placing: (name: string) => `Klicken Sie in die Karte, wo ${name} liegt.`,
  placeAtCenter: "Pin in Kartenmitte setzen",
  cancelPlacing: "Abbrechen",
  pinSet: (name: string) => `Pin für ${name} gesetzt.`,
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
  readonly lat: number | null;
  readonly lon: number | null;
}

/** Where a move was made: its save and cache update stay there. */
interface PlanContext {
  readonly day: string;
  /** The driver (the lane key). */
  readonly driverUserId: string;
  readonly laneName: string;
  readonly queryKey: readonly unknown[];
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
          lat: stop.lat,
          lon: stop.lon,
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
  /** The stop whose pin the next map click sets (§6.4). */
  const [placing, setPlacing] = useState<string | null>(null);
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
  // revision it started from, for the day and cache entry it was made in
  // (a day switch sends it first); a conflict reloads the columns.
  const autosave = useOrderAutosave<DeliveryTourResponse, PlanContext>({
    save: (_key, ids, revision, context) =>
      client.saveDeliveryTourOrder(actionId, context.driverUserId, {
        commitmentIds: [...ids],
        day: context.day,
        expectedRevision: revision,
      }),
    revisionOf: (saved) => saved.revision,
    onSaved: (_key, updated, context) => {
      queries.setQueryData<DeliveryDayToursResponse>(
        context.queryKey,
        (current) =>
          current && current.day === updated.day
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
    onFailed: (_key, error, context) => {
      showError(error);
      if (isStale(error)) {
        void Promise.all([
          queries.invalidateQueries({ queryKey: context.queryKey }),
          queries.invalidateQueries({ queryKey: ["delivery-board", actionId] }),
        ]);
      }
    },
    savedText: (_key, context) => copy.saved(context.laneName),
    undoneText: (_key, context) => copy.undone(context.laneName),
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
  /** The autosave key of a lane's tour: one per day and driver. */
  const saveKey = (lane: PlanLane) =>
    lane.tour ? `${lane.tour.day}|${lane.key}` : null;
  const pendingOf = (lane: PlanLane) => {
    const key = saveKey(lane);
    return key ? autosave.orderOf(key) : null;
  };

  const shownOf = (lane: PlanLane) => {
    if (viewing.has(lane.key) && lane.tour?.driverOrderedAt) {
      return lane.effective;
    }
    const pending = pendingOf(lane);
    return pending ? reconcileOrder(pending, lane.base, windowOf) : lane.base;
  };
  const isViewingDriver = (lane: PlanLane) =>
    viewing.has(lane.key) && Boolean(lane.tour?.driverOrderedAt);

  const moveTo = (lane: PlanLane, next: readonly string[], id?: string) => {
    if (!lane.tour) return;
    const current = shownOf(lane);
    if (sameOrder(next, current)) return;
    autosave.move(saveKey(lane)!, next, current, lane.tour.revision, {
      day: lane.tour.day,
      driverUserId: lane.key,
      laneName: lane.name,
      queryKey,
    });
    const stop = id ? model.stops.get(id) : undefined;
    if (stop && id) {
      setAnnouncement(
        `${stop.drop.buyerName} ist jetzt Stopp ${next.indexOf(id) + 1} bei ${lane.name}.`,
      );
    }
  };

  /** Sends waiting moves first, then runs `leave` (day or view change). */
  const guarded = (leave: () => void) => {
    for (const lane of lanes) {
      const key = saveKey(lane);
      if (key) void autosave.release(key);
    }
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

  const setPin = useMutation({
    ...mutationOptions,
    mutationFn: ({ id, lat, lon }: { id: string; lat: number; lon: number }) =>
      client.setDeliveryPin(actionId, id, { lat, lon }),
    onSuccess: (_stop, { id }) => {
      setPlacing(null);
      const name = model.stops.get(id)?.drop.buyerName ?? "den Stopp";
      toast?.show({ title: copy.pinSet(name), tone: "success" });
    },
    onError: showError,
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

  // The map: every stop with coordinates, by lane colour and effective
  // order; the lane with a move still saving draws its draft dashed, else
  // the lane of the chosen stops its effective order.
  const driverIndex = new Map(
    lanes
      .filter((lane) => lane.key !== UNASSIGNED)
      .map((lane, index) => [lane.key, index]),
  );
  const pins: TourMapPin[] = lanes.flatMap((lane) =>
    lane.effective.flatMap((id, index) => {
      const stop = model.stops.get(id);
      if (!stop || stop.lat === null || stop.lon === null) return [];
      const unassigned = lane.key === UNASSIGNED;
      const done =
        stop.drop.state !== "open" || stop.drop.orderStatus === "cancelled";
      return [
        {
          id,
          label: unassigned
            ? `${stop.drop.buyerName}, ${copy.unassigned}`
            : `${lane.name}, Stopp ${index + 1}: ${stop.drop.buyerName}`,
          lat: stop.lat,
          lon: stop.lon,
          rank: unassigned ? 0 : index + 1,
          selected: selected.has(id),
          tone: unassigned
            ? ("unassigned" as const)
            : done
              ? ("done" as const)
              : driverTone(driverIndex.get(lane.key) ?? 0),
        },
      ];
    }),
  );
  const draftLane = lanes.find((lane) => lane.tour && pendingOf(lane));
  const chosenLane =
    onlyLane && onlyLane !== UNASSIGNED ? laneByKey.get(onlyLane) : undefined;
  const mapLine = draftLane
    ? { ids: shownOf(draftLane), dashed: true }
    : chosenLane
      ? { ids: chosenLane.effective, dashed: false }
      : null;
  const start =
    data?.startPoint &&
    data.startPoint.lat !== null &&
    data.startPoint.lon !== null
      ? {
          lat: data.startPoint.lat,
          lon: data.startPoint.lon,
          label: data.startPoint.label,
        }
      : null;
  const placingStop = placing ? model.stops.get(placing) : undefined;
  const choosePin = (id: string) => {
    const stop = model.stops.get(id);
    if (!stop) return;
    if (!stop.window.closed) toggleSelected(id);
    [...document.querySelectorAll<HTMLElement>("li.tour-stop")]
      .find((row) => row.dataset.commitmentId === id)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

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
            <div className="tour-plan-body">
              <div className="tour-lanes">
                {lanes.map((lane) => (
                  <Lane
                    busy={assign.isPending}
                    key={lane.key}
                    lane={lane}
                    onDiscardDriverOrder={() => setDiscarding(lane.key)}
                    onPlacePin={(id) =>
                      setPlacing((current) => (current === id ? null : id))
                    }
                    placing={placing}
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
                    start={start}
                    stops={model.stops}
                    viewingDriver={isViewingDriver(lane)}
                    zone={zone}
                  />
                ))}
              </div>
              <aside className="tour-plan-map" data-testid="tour-plan-map">
                {placingStop ? (
                  <p className="tour-plan-map-bar is-placing" role="status">
                    <span>{copy.placing(placingStop.drop.buyerName)}</span>
                    <Button
                      onClick={() => setPlacing(null)}
                      size="sm"
                      variant="ghost"
                    >
                      {copy.cancelPlacing}
                    </Button>
                  </p>
                ) : (
                  <p className="tour-plan-map-bar">
                    {pins.length ? copy.mapHint : copy.noPins}
                  </p>
                )}
                <TourMap
                  label={copy.mapLabel}
                  line={mapLine}
                  onPlace={
                    placing && !setPin.isPending
                      ? (lat, lon) => setPin.mutate({ id: placing, lat, lon })
                      : undefined
                  }
                  onSelect={choosePin}
                  pins={pins}
                  placeAtCenterLabel={copy.placeAtCenter}
                  start={start}
                  tiles={{
                    url: data.map.tileUrl,
                    attribution: data.map.attribution,
                  }}
                />
              </aside>
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
  readonly onPlacePin: (id: string) => void;
  /** The stop whose pin the map is placing, if any. */
  readonly placing: string | null;
  readonly start: { readonly lat: number; readonly lon: number } | null;
}

/** One column: head with count, load per window and actions, then the windows. */
function Lane({
  busy,
  lane,
  onDiscardDriverOrder,
  onMove,
  onPlacePin,
  onSuggest,
  onToggleSelected,
  onToggleViewing,
  placing,
  selected,
  shown,
  start,
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
  const points: TourPoint[] = shown.map((id) => ({
    id,
    windowId: stops.get(id)?.window.windowId ?? "",
    lat: stops.get(id)?.lat ?? null,
    lon: stops.get(id)?.lon ?? null,
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
              onClick={() => onSuggest(nearestNextOrder(points, start))}
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
                  onPlacePin={() => onPlacePin(id)}
                  onToggleSelected={() => onToggleSelected(id)}
                  placing={placing === id}
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
  onPlacePin,
  onToggleSelected,
  orderable,
  placing,
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
  readonly onPlacePin: () => void;
  readonly placing: boolean;
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
  // A row moved to a window edge loses that arrow: focus goes to the other
  // one, so a keyboard user keeps their place.
  const up = useRef<HTMLButtonElement | null>(null);
  const down = useRef<HTMLButtonElement | null>(null);
  const pressed = useRef<-1 | 1 | null>(null);
  useEffect(() => {
    const direction = pressed.current;
    pressed.current = null;
    if (direction === -1 && first) down.current?.focus();
    if (direction === 1 && last) up.current?.focus();
  });
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
        <DriverNote className="tour-stop-note" drop={drop} />
      </label>
      {/* Ruling 18: a pin that is there can move; the click writes a manual pin. */}
      {stop.lat !== null && stop.lon !== null ? (
        <IconButton
          aria-pressed={placing}
          className="tour-stop-move-pin"
          data-testid="tour-move-pin"
          icon={MapPin}
          label={`${copy.movePin}: ${name}`}
          onClick={onPlacePin}
          size="sm"
          variant={placing ? "primary" : "ghost"}
        />
      ) : null}
      {drop.address && (stop.lat === null || stop.lon === null) ? (
        <span className="tour-stop-pin" data-testid="tour-stop-no-pin">
          <span className="small">{copy.notFound}</span>
          <Button
            aria-label={`${copy.setPin}: ${name}`}
            aria-pressed={placing}
            data-testid="tour-set-pin"
            icon={MapPinPlus}
            onClick={onPlacePin}
            size="sm"
            variant={placing ? "primary" : "secondary"}
          >
            {copy.setPin}
          </Button>
        </span>
      ) : null}
      {orderable ? (
        <span className="tour-stop-tools">
          {/* No arrow at a window edge: nothing to reach or to focus. */}
          {first ? (
            <span aria-hidden="true" className="tour-stop-tools-space" />
          ) : (
            <IconButton
              disabled={busy}
              focusableWhenDisabled
              icon={ArrowUp}
              label={`${name} nach oben`}
              onClick={() => {
                pressed.current = -1;
                onMove(-1);
              }}
              ref={up}
              size="sm"
            />
          )}
          {last ? (
            <span aria-hidden="true" className="tour-stop-tools-space" />
          ) : (
            <IconButton
              disabled={busy}
              focusableWhenDisabled
              icon={ArrowDown}
              label={`${name} nach unten`}
              onClick={() => {
                pressed.current = 1;
                onMove(1);
              }}
              ref={down}
              size="sm"
            />
          )}
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
