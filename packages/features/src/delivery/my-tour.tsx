import {
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Check,
  ChevronDown,
  MapPin,
  Navigation,
  Phone,
  Truck,
  Undo2,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  ApiError,
  type DeliveryDropResponse,
  type DeliveryTourResponse,
  type DeliveryTourWindowResponse,
  type LeonAidApiClient,
  type MyTourResponse,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  buttonClassName,
  EmptyState,
  ErrorState,
  Icon,
  IconButton,
  Meter,
  SkeletonRows,
  StatusIcon,
  StatusMessage,
  cn,
  useOptionalToast,
} from "@leonaid/ui";

import { replaceActionInUrl } from "../action-admin/action-location";
import { actionErrorMessage } from "../action-admin/errors";
import { quantityLabel } from "../commitments/quantities";
import { TaskOrderHandle, TaskOrdering } from "../tasks/task-ordering";
import { deliveryTimeRange, dropAddress } from "./delivery-board";
import {
  callHref,
  devicePlatform,
  moveStop,
  navigationHref,
  osmHref,
  placeStop,
  windowHint,
  windowHintLabel,
} from "./tour-model";

/*
 * "Meine Tour" (spec krapfentaxi-touren §7): the driver's stops of one day
 * in effective order, grouped by window. The next open stop is the large
 * card; done stops stay in place as one greyed line (D15). Behind the flag
 * `delivery.tours`; without it the PWA keeps the delivery board.
 */

const copy = {
  title: "Meine Tour",
  progress: (done: number, total: number) => `${done} von ${total} zugestellt`,
  ownOrder: "Eigene Reihenfolge",
  planOrder: "Reihenfolge der Planung",
  next: "Nächster Stopp",
  stop: "Stopp",
  ended: "Fenster vorbei",
  isNew: "neu",
  closed: "Abgeschlossen",
  delivered: "Zugestellt",
  missed: "Nicht angetroffen",
  open: "Offen",
  cancelled: "storniert",
  reorder: "Reihenfolge ändern",
  editHint:
    "Zieh die Stopps am Griff oder nutze die Pfeile. Sortieren geht nur innerhalb eines Fensters.",
  done: "Fertig",
  reset: "Zurück zur Planung",
  cancel: "Abbrechen",
  saved: "Deine Reihenfolge ist gespeichert. Die Planung sieht sie.",
  unchanged: "Reihenfolge unverändert.",
  resetDone: "Es gilt wieder die Reihenfolge der Planung.",
  allDone:
    "Alles erledigt. Gib der Aktionsleitung Bescheid, dass du fertig bist.",
  closedWindow:
    "Dieses Fenster ist abgeschlossen. Für Änderungen wende dich an die Aktionsleitung.",
  cancelledOrder: "Diese Bestellung wird nicht (mehr) ausgeliefert.",
  noAddress: "Keine Lieferadresse hinterlegt.",
  noPhone: "Keine Nummer",
  contact: "Lieferkontakt",
  error: "Deine Tour konnte nicht geladen werden.",
  errorHint: "Prüfe deine Verbindung und versuche es erneut.",
  notEnabled: "Für diese Aktion ist keine Lieferplanung aktiv.",
  nothing: "Dir ist noch keine Tour zugewiesen",
  nothingHint: "Sobald dir jemand Stopps zuweist, erscheinen sie hier.",
  noAction: "Dir ist noch keine Aktion als Ausfahrer zugeordnet.",
  offline:
    "Ohne Verbindung zeigen wir deine Tour nicht. Sobald du wieder online bist, lädt sie neu.",
  toast: {
    delivered: (name: string) => `${name}: zugestellt.`,
    missed: (name: string) => `${name}: nicht angetroffen.`,
    open: (name: string) => `${name} ist wieder offen.`,
  },
  codes: {
    delivery_window_closed:
      "Dieses Lieferfenster ist abgeschlossen. Wende dich an die Aktionsleitung.",
    delivery_state_conflict:
      "Dieser Stopp wurde inzwischen geändert. Du siehst jetzt den aktuellen Stand.",
    delivery_not_assigned: "Dieser Stopp ist dir nicht zugewiesen.",
    delivery_order_not_deliverable:
      "Diese Bestellung wird nicht (mehr) ausgeliefert.",
    tour_revision_conflict: "Die Tour wurde inzwischen geändert.",
    tour_order_stale: "Die Tour wurde inzwischen geändert.",
  },
} as const;

type ErrorCode = keyof typeof copy.codes;

/** Server answers that mean "what you see is old": reload the tour. */
const STALE_CODES: ReadonlySet<string> = new Set([
  "delivery_state_conflict",
  "tour_revision_conflict",
  "tour_order_stale",
]);

/** How long "Rückgängig" stays on the toast (spec §7.4). */
export const TOUR_UNDO_MS = 10_000;
/** How often the window hints ("noch 35 min") move on. No server polling. */
const CLOCK_TICK_MS = 30_000;

type Target = "delivered" | "missed" | "open";

interface TourStop {
  readonly drop: DeliveryDropResponse;
  readonly window: DeliveryTourWindowResponse;
  readonly newForDriver: boolean;
}

/** "Sa 05.12." for an ISO day. */
function shortDay(day: string) {
  const date = new Date(`${day}T12:00:00Z`);
  const weekday = new Intl.DateTimeFormat("de-DE", {
    timeZone: "UTC",
    weekday: "short",
  })
    .format(date)
    .replace(".", "");
  const dayMonth = new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "UTC",
  }).format(date);
  return `${weekday} ${dayMonth}`;
}

const deliverable = (drop: DeliveryDropResponse) =>
  drop.orderStatus !== "cancelled";

const stopName = (drop: DeliveryDropResponse) =>
  drop.address?.recipientName || drop.buyerName;

/** "3 Boxen, 12 Stück" in the action's units. */
function quantities(drop: DeliveryDropResponse) {
  const parts = drop.quantities.map(
    (item) => `${item.quantity} ${quantityLabel(item.quantity, item.unit)}`,
  );
  return parts.length
    ? parts.join(", ")
    : `${drop.totalBoxes} ${quantityLabel(drop.totalBoxes, "box")}`;
}

const byStart = (
  a: DeliveryTourWindowResponse,
  b: DeliveryTourWindowResponse,
) => Date.parse(a.startsAt) - Date.parse(b.startsAt);

/** The windows by start, each with its stops in effective order. */
function orderedWindows(tour: DeliveryTourResponse) {
  return [...tour.windows].sort(byStart).map((window) => ({
    window,
    ids: [...window.stops]
      .sort((a, b) => a.effectiveRank - b.effectiveRank)
      .map((stop) => stop.drop.commitmentId),
  }));
}

/** The response with one drop replaced by its newer state. */
function withDrop(
  response: MyTourResponse,
  drop: DeliveryDropResponse,
): MyTourResponse {
  if (!response.tour) return response;
  return {
    ...response,
    tour: {
      ...response.tour,
      windows: response.tour.windows.map((window) => ({
        ...window,
        stops: window.stops.map((stop) =>
          stop.drop.commitmentId === drop.commitmentId &&
          stop.drop.revision <= drop.revision
            ? { ...stop, drop }
            : stop,
        ),
      })),
    },
  };
}

const sameOrder = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((id, index) => id === b[index]);

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

export interface MyTourPageProps {
  readonly client: LeonAidApiClient;
  readonly actionId: string;
  /** The actions this driver drives for; a switch shows for several. */
  readonly actions?: readonly {
    readonly actionId: string;
    readonly actionName: string;
  }[];
  /**
   * The device is offline. The page then shows no stops and drops its
   * cached copy (addresses and phones stay off a lost phone).
   */
  readonly offline?: boolean;
}

export function MyTourPage({
  actionId,
  actions = [],
  client,
  offline = false,
}: MyTourPageProps) {
  const queries = useQueryClient();
  const toast = useOptionalToast();
  const now = useNow(CLOCK_TICK_MS);
  // The chosen day lives in the URL (?day=), so a reload keeps it.
  const [day, setDayState] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("day"),
  );
  const setDay = (value: string | null) => {
    setDayState(value);
    const url = new URL(window.location.href);
    if (value) url.searchParams.set("day", value);
    else url.searchParams.delete("day");
    window.history.replaceState(window.history.state, "", url);
  };
  /** Edit mode: the draft order of all stops; null outside edit mode. */
  const [draft, setDraft] = useState<readonly string[] | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [announcement, setAnnouncement] = useState("");

  const queryKey = ["my-tour", actionId, day] as const;
  const tourQuery = useQuery({
    enabled: Boolean(actionId) && !offline,
    // Nothing stays in memory once the page is left; no background loads.
    gcTime: 0,
    queryFn: () => client.getMyTour(actionId, { day }),
    queryKey,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  useEffect(() => {
    if (!offline) return;
    queries.removeQueries({ queryKey: ["my-tour"] });
    // Finished commands keep the returned drop (address, phone) as data.
    const mutations = queries.getMutationCache();
    for (const mutation of mutations.findAll({ mutationKey: ["my-tour"] })) {
      mutations.remove(mutation);
    }
    setDraft(null);
  }, [offline, queries]);
  const mutationOptions = { gcTime: 0, mutationKey: ["my-tour", actionId] };
  const refresh = () =>
    queries.invalidateQueries({ queryKey: ["my-tour", actionId] });

  const errorText = (error: unknown) => {
    const shared = actionErrorMessage(error, { address: "du" });
    const code = shared.code as ErrorCode | null;
    return code && code in copy.codes ? copy.codes[code] : shared.message;
  };
  const isStale = (error: unknown) =>
    error instanceof ApiError && STALE_CODES.has(error.detail.code);

  const data = tourQuery.data;
  const tour = data?.tour ?? null;
  const zone = data?.timezone ?? "Europe/Berlin";

  const model = useMemo(() => {
    const stops = new Map<string, TourStop>();
    const windows = tour ? orderedWindows(tour) : [];
    for (const { window } of windows) {
      for (const stop of window.stops) {
        stops.set(stop.drop.commitmentId, {
          drop: stop.drop,
          newForDriver: stop.newForDriver,
          window,
        });
      }
    }
    return { stops, windows, order: windows.flatMap((group) => group.ids) };
  }, [tour]);
  const windowOf = (id: string) => model.stops.get(id)?.window.windowId ?? "";

  // A stop the server added or removed while editing: keep the draft to
  // the known stops and append new ones; the save then says what changed.
  const draftIds = useMemo(() => {
    if (!draft) return null;
    const known = draft.filter((id) => model.stops.has(id));
    return [...known, ...model.order.filter((id) => !known.includes(id))];
  }, [draft, model]);

  const counted = model.order
    .map((id) => model.stops.get(id)!)
    .filter((stop) => deliverable(stop.drop));
  const deliveredCount = counted.filter(
    (stop) => stop.drop.state === "delivered",
  ).length;
  const nextId = model.order.find((id) => {
    const stop = model.stops.get(id)!;
    return (
      stop.drop.state === "open" &&
      deliverable(stop.drop) &&
      !stop.window.closed
    );
  });

  // One command at a time, set before "pending" shows in a later render.
  const ticking = useRef(false);
  const setState = useMutation({
    ...mutationOptions,
    mutationFn: ({
      drop,
      target,
    }: {
      drop: DeliveryDropResponse;
      target: Target;
    }) =>
      client.setDeliveryState(actionId, drop.commitmentId, {
        delivered: target === "delivered",
        expectedRevision: drop.revision,
        missed: target === "missed",
      }),
    onMutate: () => {
      ticking.current = true;
    },
    // Show the returned drop at once; the refetch then confirms the tour.
    onSuccess: (updated) =>
      queries.setQueryData<MyTourResponse>(queryKey, (current) =>
        current ? withDrop(current, updated) : current,
      ),
    onSettled: () => {
      ticking.current = false;
      void refresh();
    },
    onError: (error) => toast?.show({ title: errorText(error), tone: "error" }),
  });

  const latest = useRef<MyTourResponse | undefined>(undefined);
  latest.current = data;
  /** The newer of a drop as returned and as currently loaded. */
  const freshest = (drop: DeliveryDropResponse) => {
    const loaded = latest.current?.tour?.windows
      .flatMap((window) => window.stops)
      .find((stop) => stop.drop.commitmentId === drop.commitmentId)?.drop;
    return loaded && loaded.revision > drop.revision ? loaded : drop;
  };

  const mark = (drop: DeliveryDropResponse, target: Target) => {
    if (ticking.current || !deliverable(drop)) return;
    ticking.current = true;
    const name = stopName(drop);
    setState.mutate(
      { drop, target },
      {
        onSuccess: (updated) =>
          toast?.show({
            title: copy.toast[target](name),
            tone: target === "delivered" ? "success" : "info",
            timeout: TOUR_UNDO_MS,
            // Undo uses the same rule as any change (decide_state_change).
            action:
              target === "open"
                ? undefined
                : {
                    label: "Rückgängig",
                    run: () => mark(freshest(updated), "open"),
                  },
          }),
      },
    );
  };

  const saveOrder = useMutation({
    ...mutationOptions,
    mutationFn: ({
      ids,
      current,
    }: {
      ids: readonly string[];
      current: DeliveryTourResponse;
    }) =>
      client.saveMyTourOrder(actionId, {
        commitmentIds: [...ids],
        day: current.day,
        expectedRevision: current.revision,
      }),
    onSuccess: (updated, { ids }) => {
      queries.setQueryData<MyTourResponse>(queryKey, (current) =>
        current ? { ...current, tour: updated } : current,
      );
      setDraft(null);
      toast?.show({
        title: ids.length ? copy.saved : copy.resetDone,
        tone: "success",
      });
    },
    onError: (error) => {
      toast?.show({ title: errorText(error), tone: "error" });
      // A changed tour: leave edit mode and show the current one. Other
      // failures (network) keep the draft for another try.
      if (isStale(error)) {
        setDraft(null);
        void refresh();
      }
    },
  });

  const finishEdit = () => {
    if (!draftIds || !tour) return;
    if (sameOrder(draftIds, model.order)) {
      setDraft(null);
      toast?.show({ title: copy.unchanged, tone: "info" });
      return;
    }
    saveOrder.mutate({ ids: draftIds, current: tour });
  };

  const moveInDraft = (next: string[], id: string) => {
    setDraft(next);
    const stop = model.stops.get(id);
    if (stop) {
      setAnnouncement(
        `${stopName(stop.drop)} ist jetzt Stopp ${next.indexOf(id) + 1}.`,
      );
    }
  };

  const toggleExpanded = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const header = (
    <header className="page-header">
      <div>
        <div className="page-heading">
          <h1>{copy.title}</h1>
          {tour && data && data.days.length <= 1 ? (
            <span className="page-count" data-testid="tour-day">
              {shortDay(tour.day)}
            </span>
          ) : null}
        </div>
        {tour ? (
          <p className="page-sub tour-sub">
            <span className="num">
              {copy.progress(deliveredCount, counted.length)}
            </span>
            <span aria-hidden="true">·</span>
            <span>{tour.driverOrderedAt ? copy.ownOrder : copy.planOrder}</span>
          </p>
        ) : null}
      </div>
      {data && (data.days.length > 1 || actions.length > 1) ? (
        <div className="delivery-filters">
          {actions.length > 1 ? (
            <label className="driver-filter">
              <span>Aktion</span>
              <select
                className="input select"
                data-testid="tour-action"
                onChange={(event) => {
                  setDay(null);
                  setDraft(null);
                  replaceActionInUrl(event.target.value);
                }}
                value={actionId}
              >
                {actions.map((item) => (
                  <option key={item.actionId} value={item.actionId}>
                    {item.actionName}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {data.days.length > 1 ? (
            <label className="driver-filter">
              <span>Liefertag</span>
              <select
                className="input select"
                data-testid="tour-day"
                onChange={(event) => {
                  setDay(event.target.value);
                  setDraft(null);
                }}
                value={tour?.day ?? ""}
              >
                {data.days.map((item) => (
                  <option key={item} value={item}>
                    {shortDay(item)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      ) : null}
    </header>
  );

  if (offline) {
    return (
      <div className="delivery tour" data-zone="delivery">
        <header className="page-header">
          <div className="page-heading">
            <h1>{copy.title}</h1>
          </div>
        </header>
        <EmptyState
          description={copy.offline}
          headingLevel={2}
          icon={Truck}
          title="Keine Verbindung"
        />
      </div>
    );
  }

  if (!actionId) {
    return (
      <div className="delivery tour" data-zone="delivery">
        <EmptyState
          description={copy.noAction}
          headingLevel={2}
          icon={Truck}
          title="Keine Aktion gewählt"
        />
      </div>
    );
  }

  const notEnabled =
    tourQuery.error instanceof ApiError &&
    ["delivery_not_enabled", "feature_flag_disabled"].includes(
      tourQuery.error.detail.code,
    );
  const reorderable = model.windows.some(
    (group) => !group.window.closed && group.ids.length > 1,
  );

  return (
    <div className="delivery tour" data-zone="delivery">
      {header}
      {tourQuery.isPending ? (
        <SkeletonRows rows={5} />
      ) : notEnabled ? (
        <EmptyState
          description={copy.notEnabled}
          headingLevel={2}
          icon={Truck}
          title="Keine Lieferplanung"
        />
      ) : tourQuery.isError ? (
        <ErrorState onRetry={() => void tourQuery.refetch()} title={copy.error}>
          {copy.errorHint}
        </ErrorState>
      ) : !tour || model.order.length === 0 ? (
        <EmptyState
          description={copy.nothingHint}
          headingLevel={2}
          icon={Truck}
          title={copy.nothing}
        />
      ) : (
        <>
          <Meter
            label={copy.progress(deliveredCount, counted.length)}
            max={Math.max(1, counted.length)}
            tone={
              deliveredCount === counted.length && counted.length > 0
                ? "ok"
                : "zone"
            }
            value={deliveredCount}
          />
          {draftIds ? (
            <div
              aria-label={copy.reorder}
              className="tour-edit-bar"
              role="region"
            >
              <p>{copy.editHint}</p>
              <div className="tour-edit-actions">
                <Button
                  data-testid="tour-reorder-done"
                  icon={Check}
                  loading={saveOrder.isPending}
                  onClick={finishEdit}
                  size="lg"
                  variant="primary"
                >
                  {copy.done}
                </Button>
                {tour.driverOrderedAt ? (
                  <Button
                    data-testid="tour-reset-order"
                    disabled={saveOrder.isPending}
                    onClick={() => saveOrder.mutate({ ids: [], current: tour })}
                    size="lg"
                    variant="secondary"
                  >
                    {copy.reset}
                  </Button>
                ) : null}
                <Button
                  disabled={saveOrder.isPending}
                  onClick={() => setDraft(null)}
                  size="lg"
                  variant="ghost"
                >
                  {copy.cancel}
                </Button>
              </div>
            </div>
          ) : (
            <>
              {counted.length > 0 &&
              counted.every((stop) => stop.drop.state !== "open") ? (
                <StatusMessage className="tour-all-done" tone="success">
                  {copy.allDone}
                </StatusMessage>
              ) : null}
              {reorderable ? (
                <div className="tour-list-head">
                  <Button
                    data-testid="tour-reorder"
                    icon={ArrowDownUp}
                    onClick={() => {
                      setExpanded(new Set());
                      setDraft(model.order);
                    }}
                    variant="ghost"
                  >
                    {copy.reorder}
                  </Button>
                </div>
              ) : null}
            </>
          )}
          <p aria-live="polite" className="sr-only" role="status">
            {announcement}
          </p>

          {model.windows.map(({ window, ids }) => {
            const order = draftIds ?? model.order;
            const groupIds = draftIds
              ? draftIds.filter((id) => windowOf(id) === window.windowId)
              : ids;
            const active = groupIds
              .map((id) => model.stops.get(id)!.drop)
              .filter(deliverable);
            const done = active.filter(
              (drop) => drop.state === "delivered",
            ).length;
            const hint = windowHint(window.startsAt, window.endsAt, now);
            const label = `${deliveryTimeRange(window, zone)} Uhr`;
            const movable = Boolean(draftIds) && !window.closed;
            const list = (
              <ol className="tour-rows">
                {groupIds.map((id, index) => {
                  const stop = model.stops.get(id)!;
                  const position = order.indexOf(id) + 1;
                  const ended = hint.kind === "ended";
                  if (draftIds) {
                    return (
                      <EditRow
                        disabled={saveOrder.isPending}
                        first={index === 0}
                        key={id}
                        last={index === groupIds.length - 1}
                        movable={movable}
                        onMove={(direction) =>
                          moveInDraft(
                            moveStop(draftIds, id, direction, windowOf),
                            id,
                          )
                        }
                        position={position}
                        stop={stop}
                      />
                    );
                  }
                  const card = (next: boolean) => (
                    <StopCard
                      busy={setState.isPending}
                      ended={ended}
                      label={label}
                      next={next}
                      onMark={(target) => mark(stop.drop, target)}
                      position={position}
                      stop={stop}
                    />
                  );
                  if (id === nextId) {
                    return (
                      <li className="tour-next" key={id}>
                        {card(true)}
                      </li>
                    );
                  }
                  return (
                    <StopRow
                      card={card(false)}
                      ended={ended}
                      expanded={expanded.has(id)}
                      key={id}
                      onToggle={() => toggleExpanded(id)}
                      position={position}
                      stop={stop}
                    />
                  );
                })}
              </ol>
            );
            return (
              <section
                aria-labelledby={`tour-win-${window.windowId}`}
                className={cn("tour-window", window.closed && "is-closed")}
                key={window.windowId}
              >
                <header className="tour-window-head">
                  <h2 id={`tour-win-${window.windowId}`}>
                    {windowHintLabel(label, hint)}
                  </h2>
                  <span className="small muted num">
                    {done} von {active.length} zugestellt
                  </span>
                  {window.closed ? (
                    <span className="stamp tone-ok">{copy.closed}</span>
                  ) : null}
                </header>
                {movable && draftIds ? (
                  <TaskOrdering
                    ids={groupIds}
                    noun="Stopp"
                    onCancel={() => setAnnouncement("Verschieben abgebrochen.")}
                    onMove={(id, targetId, side) =>
                      moveInDraft(
                        placeStop(draftIds, id, targetId, side, windowOf),
                        id,
                      )
                    }
                  >
                    {list}
                  </TaskOrdering>
                ) : (
                  list
                )}
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}

function StateFlags({
  ended,
  stop,
}: {
  readonly ended: boolean;
  readonly stop: TourStop;
}) {
  const open = stop.drop.state === "open" && deliverable(stop.drop);
  return (
    <>
      {stop.newForDriver ? <Badge tone="zone">{copy.isNew}</Badge> : null}
      {open && ended && !stop.window.closed ? (
        <Badge tone="warn">{copy.ended}</Badge>
      ) : null}
      {!deliverable(stop.drop) ? (
        <Badge tone="neutral">{copy.cancelled}</Badge>
      ) : null}
    </>
  );
}

function stateLabel(drop: DeliveryDropResponse) {
  return drop.state === "delivered"
    ? copy.delivered
    : drop.state === "missed"
      ? copy.missed
      : copy.open;
}

function stateShape(drop: DeliveryDropResponse) {
  if (!deliverable(drop)) return "cancelled" as const;
  return drop.state === "delivered"
    ? ("done" as const)
    : drop.state === "missed"
      ? ("alert" as const)
      : ("open" as const);
}

/** The full card: the next stop, or a row or done line tapped open. */
function StopCard({
  busy,
  ended,
  label,
  next,
  onMark,
  position,
  stop,
}: {
  readonly busy: boolean;
  readonly ended: boolean;
  /** Window label, "08–10 Uhr". */
  readonly label: string;
  readonly next: boolean;
  readonly onMark: (target: Target) => void;
  readonly position: number;
  readonly stop: TourStop;
}) {
  const { drop, window } = stop;
  const id = drop.commitmentId;
  const name = stopName(drop);
  const address = dropAddress(drop);
  const located = { lat: null, lon: null, address: address ?? "" };
  const tel = callHref(drop.contact?.phone ?? null, null);
  const contactName = drop.contact?.name || copy.contact;
  const navigation = navigationHref(
    located,
    devicePlatform(navigator.userAgent),
  );
  const external = navigation.startsWith("https:");
  const open = drop.state === "open";
  return (
    <article
      aria-labelledby={`tour-card-${id}`}
      className={cn("tour-card", next && "is-next", !open && "is-done")}
      data-testid={next ? "tour-next-stop" : undefined}
      id={`tour-stop-${id}`}
    >
      <p className="tour-card-eyebrow">
        <span className="tour-pos num">{position}</span>
        <span>
          {next ? copy.next : copy.stop} · {label}
        </span>
        <StateFlags ended={ended} stop={stop} />
      </p>
      <h3 id={`tour-card-${id}`}>{name}</h3>
      {name !== drop.buyerName ? (
        <p className="tour-card-buyer">für {drop.buyerName}</p>
      ) : null}
      {address && drop.address ? (
        <a
          className="tour-address"
          href={osmHref(located)}
          rel="noopener"
          target="_blank"
        >
          <Icon icon={MapPin} size={16} />
          <span>
            {drop.address.streetLine1}
            <br />
            {drop.address.postalCode} {drop.address.city}
          </span>
        </a>
      ) : (
        <p className="tour-card-muted">{copy.noAddress}</p>
      )}
      {/* The driver note (spec §5.1) joins here with Task 12. */}
      <div className="tour-contact">
        <div className="tour-contact-text">
          <strong>{contactName}</strong>
          <span className="num">
            {drop.contact?.phone ?? "Lieferkontakt ohne Telefon"}
          </span>
        </div>
        {tel ? (
          <a
            aria-label={`${contactName} anrufen`}
            className={cn(
              buttonClassName({ size: "lg", variant: "secondary" }),
              "btn-icon",
            )}
            href={tel}
            title={`${contactName} anrufen`}
          >
            <Icon icon={Phone} size={18} />
          </a>
        ) : (
          <Badge tone="neutral">{copy.noPhone}</Badge>
        )}
      </div>
      <p className="tour-qty num">{quantities(drop)}</p>
      <div className="tour-card-actions">
        {address ? (
          <a
            className={cn(
              buttonClassName({ size: "lg", variant: "secondary" }),
              "tour-wide",
            )}
            href={navigation}
            {...(external ? { rel: "noopener", target: "_blank" } : {})}
          >
            <Icon icon={Navigation} size={16} />
            <span className="btn-label">Navigation</span>
          </a>
        ) : null}
        {!deliverable(drop) ? (
          <p className="tour-wide tour-card-muted">{copy.cancelledOrder}</p>
        ) : window.closed ? (
          <p className="tour-wide tour-card-muted">
            {open ? copy.closedWindow : `${stateLabel(drop)}.`}
          </p>
        ) : open ? (
          <>
            <Button
              disabled={busy}
              icon={Check}
              onClick={() => onMark("delivered")}
              size="lg"
              variant="primary"
            >
              {copy.delivered}
            </Button>
            <Button
              disabled={busy}
              icon={X}
              onClick={() => onMark("missed")}
              size="lg"
              variant="secondary"
            >
              {copy.missed}
            </Button>
          </>
        ) : (
          <>
            <p className="tour-card-state">
              <StatusIcon
                label={stateLabel(drop)}
                size={18}
                status={stateShape(drop)}
              />
              <span>{stateLabel(drop)}.</span>
            </p>
            <Button
              disabled={busy}
              icon={Undo2}
              onClick={() => onMark("open")}
              size="lg"
              variant="secondary"
            >
              Rückgängig
            </Button>
          </>
        )}
      </div>
    </article>
  );
}

/** An open row (number, name, street, quantity) or a done line; taps open. */
function StopRow({
  card,
  ended,
  expanded,
  onToggle,
  position,
  stop,
}: {
  readonly card: ReactNode;
  readonly ended: boolean;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly position: number;
  readonly stop: TourStop;
}) {
  const { drop } = stop;
  const done = drop.state !== "open";
  const address = dropAddress(drop);
  const id = drop.commitmentId;
  const name = stopName(drop);
  return (
    <li
      className={cn(
        "row tour-row",
        done && "is-done",
        !deliverable(drop) && "is-cancelled",
        expanded && "is-expanded",
      )}
      data-testid={done ? "tour-stop-done" : "tour-stop"}
    >
      <div className="tour-row-line">
        <span className="tour-pos num">{position}</span>
        <div className="tour-row-main">
          <button
            aria-controls={expanded ? `tour-stop-${id}` : undefined}
            aria-expanded={expanded}
            className="tour-row-toggle"
            onClick={onToggle}
            type="button"
          >
            <span className="tour-row-name" data-testid="tour-stop-name">
              {name}
            </span>
            <Icon className="tour-row-chevron" icon={ChevronDown} size={16} />
          </button>
          {done ? null : (
            <p className="tour-row-sub">
              {address && drop.address ? (
                <a
                  aria-label={`${address} in OpenStreetMap`}
                  className="tour-row-map"
                  href={osmHref({ lat: null, lon: null, address })}
                  rel="noopener"
                  target="_blank"
                >
                  <Icon icon={MapPin} size={14} />
                  <span>{drop.address.streetLine1}</span>
                </a>
              ) : null}
              <span className="num">{quantities(drop)}</span>
              <StateFlags ended={ended} stop={stop} />
            </p>
          )}
        </div>
        <span className="tour-row-state">
          <StatusIcon
            label={stateLabel(drop)}
            size={20}
            status={stateShape(drop)}
          />
          {done ? <span aria-hidden="true">{stateLabel(drop)}</span> : null}
        </span>
      </div>
      {expanded ? card : null}
    </li>
  );
}

/** Edit mode: grip, number, name, up and down (inside the window only). */
function EditRow({
  disabled,
  first,
  last,
  movable,
  onMove,
  position,
  stop,
}: {
  readonly disabled: boolean;
  readonly first: boolean;
  readonly last: boolean;
  readonly movable: boolean;
  readonly onMove: (direction: -1 | 1) => void;
  readonly position: number;
  readonly stop: TourStop;
}) {
  const { drop } = stop;
  const name = stopName(drop);
  const done = drop.state !== "open";
  return (
    <li
      className={cn("row tour-row is-editing", done && "is-done")}
      data-testid={done ? "tour-stop-done" : "tour-stop"}
    >
      <div className="tour-row-line">
        {movable ? (
          <TaskOrderHandle
            disabled={disabled}
            id={drop.commitmentId}
            noun="Stopp"
            title={name}
          />
        ) : null}
        <span className="tour-pos num">{position}</span>
        <div className="tour-row-main">
          <span className="tour-row-name" data-testid="tour-stop-name">
            {name}
          </span>
          <span className="tour-row-sub">{drop.address?.streetLine1}</span>
        </div>
        {movable ? (
          <span className="tour-row-tools">
            <IconButton
              disabled={disabled || first}
              focusableWhenDisabled
              icon={ArrowUp}
              label={`${name} nach oben`}
              onClick={() => onMove(-1)}
              size="lg"
              variant="secondary"
            />
            <IconButton
              disabled={disabled || last}
              focusableWhenDisabled
              icon={ArrowDown}
              label={`${name} nach unten`}
              onClick={() => onMove(1)}
              size="lg"
              variant="secondary"
            />
          </span>
        ) : null}
      </div>
    </li>
  );
}
