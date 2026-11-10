import {
  Check,
  ChevronDown,
  EllipsisVertical,
  LocateFixed,
  Map as MapIcon,
  Navigation,
  Phone,
  Truck,
  Undo2,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";

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
  Meter,
  PageBarPortal,
  Popover,
  SkeletonRows,
  StatusIcon,
  cn,
  useOptionalToast,
  usePageBar,
} from "@leonaid/ui";

import { replaceActionInUrl } from "../action-admin/action-location";
import { actionErrorMessage } from "../action-admin/errors";
import {
  isNetworkFailure,
  useOfflineRuntime,
  useQueueSnapshot,
} from "../offline/runtime";
import { isTourEntry, sameAction } from "../offline/queue";
import {
  loadOfflineTour,
  saveTour,
  withDrop,
  withQueuedWrites,
  type CachedTour,
} from "../offline/tour-cache";
import { TaskOrderHandle, TaskOrdering } from "../tasks/task-ordering";
import {
  clockMinutes,
  deliveryTimeRange,
  dropAddress,
  dropQuantities,
  dropQuantitiesShort,
} from "./delivery-shared";
import { DriverNote } from "./driver-note";
import { TourMap, type TourMapPin } from "./tour-map";
import { TourMapSlot } from "./tour-map-slot";
import {
  callHref,
  devicePlatform,
  navigationHref,
  placeStop,
  reconcileOrder,
  windowHint,
  type WindowHint,
} from "./tour-model";
import { useOrderAutosave } from "./use-order-autosave";

/*
 * "Meine Tour" (spec krapfentaxi-touren §7, D15–D19, critique-driver.md §3):
 * one task per screen, deliver the next stop. The app bar carries the day,
 * progress and a small menu; the list of stops scrolls behind a fixed dock
 * with the next stop, its map and "Zugestellt" in thumb reach. Open stops
 * are reordered at their grip and every move saves at once. Done stops stay
 * in place as one grey line (D15). Behind the flag `delivery.tours`.
 * Offline, with `pwa.offline_queue` on too, the device's copy of today's
 * tour shows under "Offline – Stand HH:MM" (§9): marks and moves go to the
 * offline queue and show at once; "Du" lists them until Core has them.
 */

const copy = {
  title: "Meine Tour",
  ownOrder: "Eigene Reihenfolge",
  next: "Nächster Stopp",
  stop: (position: number) => `Stopp ${position}`,
  toNext: "Zum nächsten Stopp",
  ended: "Fenster vorbei",
  isNew: "neu",
  closed: "Abgeschlossen",
  delivered: "Zugestellt",
  missed: "Nicht angetroffen",
  missedShort: "Nicht da",
  open: "Offen",
  cancelled: "storniert",
  menu: "Tour-Menü",
  reset: "Zurück zur Planung",
  saved: "Reihenfolge gespeichert.",
  undone: "Vorherige Reihenfolge wiederhergestellt.",
  resetDone: "Es gilt wieder die Reihenfolge der Planung.",
  allDelivered: (total: number) => `Alle ${total} zugestellt. Danke!`,
  allSettled: (delivered: number, total: number) =>
    `Alle Stopps erledigt, ${delivered} von ${total} zugestellt.`,
  tellLead: "Gib der Aktionsleitung Bescheid, dass du fertig bist.",
  onlyClosedLeft:
    "Keine offenen Stopps in offenen Fenstern. Für Änderungen wende dich an die Aktionsleitung.",
  closedWindow:
    "Dieses Fenster ist abgeschlossen. Für Änderungen wende dich an die Aktionsleitung.",
  cancelledOrder: "Diese Bestellung wird nicht (mehr) ausgeliefert.",
  map: "Karte",
  mapLabel: "Karte der Tour",
  myLocation: "Mein Standort",
  noLocation: "Dein Standort ist gerade nicht verfügbar.",
  noPins: "Noch kein Stopp hat einen Kartenpunkt.",
  closeSheet: "Stoppkarte schließen",
  noAddress: "Keine Lieferadresse hinterlegt.",
  error: "Deine Tour konnte nicht geladen werden.",
  errorHint: "Prüfe deine Verbindung und versuche es erneut.",
  notEnabled: "Für diese Aktion ist keine Lieferplanung aktiv.",
  nothing: "Dir ist noch keine Tour zugewiesen",
  nothingHint: "Sobald dir jemand Stopps zuweist, erscheinen sie hier.",
  noAction: "Dir ist noch keine Aktion als Ausfahrer zugeordnet.",
  offline:
    "Ohne Verbindung zeigen wir deine Tour nicht. Sobald du wieder online bist, lädt sie neu.",
  offlineEmpty:
    "Auf diesem Gerät ist keine Tour für heute gespeichert. Sobald du wieder online bist, lädt sie neu.",
  offlineStand: (time: string) => `Offline – Stand ${time}`,
  offlineHint: "Zustellen und Umsortieren geht wieder, sobald du online bist.",
  offlineQueueHint:
    "Zustellungen und Umsortieren speichert LeonAid auf diesem Gerät und sendet sie, sobald du online bist.",
  toast: {
    delivered: (name: string) => `${name}: zugestellt.`,
    missed: (name: string) => `${name}: nicht angetroffen.`,
    open: (name: string) => `${name} ist wieder offen.`,
  },
  /** Marks and moves kept for the queue: never "gespeichert" (§9). */
  queued: {
    delivered: (name: string) =>
      `${name}: zugestellt. Wird gesendet, sobald du online bist.`,
    missed: (name: string) =>
      `${name}: nicht angetroffen. Wird gesendet, sobald du online bist.`,
    open: (name: string) =>
      `${name} ist wieder offen. Wird gesendet, sobald du online bist.`,
    order: "Reihenfolge gemerkt. Sie wird gesendet, sobald du online bist.",
    orderSending: "Reihenfolge wird gesendet.",
    orderUndone: "Vorherige Reihenfolge wiederhergestellt.",
    failed: "Das konnte auf diesem Gerät nicht gespeichert werden.",
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
/** The autosave key of the driver's tour: one per action and day. */
const orderKey = (actionId: string, day: string) => `${actionId}|${day}`;
/** The dock's folded state lives for the session (critique §3 C). */
const DOCK_FOLDED_KEY = "leonaid.tour.dockFolded";
/** A drag on the dock grip further than this folds or unfolds it. */
const DOCK_SWIPE_PX = 24;

type Target = "delivered" | "missed" | "open";

/** Where a move was made: its save and cache update stay there. */
interface OrderContext {
  readonly actionId: string;
  readonly day: string;
  readonly queryKey: readonly unknown[];
}

interface TourStop {
  readonly drop: DeliveryDropResponse;
  readonly window: DeliveryTourWindowResponse;
  readonly newForDriver: boolean;
  /** The pin, once geocoded or set by the manager (§6.4). */
  readonly lat: number | null;
  readonly lon: number | null;
}

/** In the map view: the sheet shows the dock's stop or a done stop. */
type MapSheet =
  | { readonly kind: "stop" }
  | { readonly kind: "done"; readonly id: string };

type MapStart = {
  readonly lat: number;
  readonly lon: number;
  readonly label: string;
};

interface DockMap {
  readonly tiles: { readonly url: string; readonly attribution: string };
  readonly onOpen: () => void;
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

/** "14:05" of an instant, in the action's zone. */
function clockTime(at: string, zone: string) {
  const options: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
  };
  try {
    return new Intl.DateTimeFormat("de-DE", {
      ...options,
      timeZone: zone,
    }).format(new Date(at));
  } catch {
    return new Intl.DateTimeFormat("de-DE", options).format(new Date(at));
  }
}

const deliverable = (drop: DeliveryDropResponse) =>
  drop.orderStatus !== "cancelled";

const stopName = (drop: DeliveryDropResponse) =>
  drop.address?.recipientName || drop.buyerName;

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

/**
 * The device copy with the order and revision of an own save; stops and
 * windows stay as the copy keeps them (purged, minimized).
 */
function withSavedOrder(
  copy: CachedTour,
  saved: DeliveryTourResponse,
): CachedTour {
  const tour = copy.tour.tour;
  if (!tour || tour.day !== saved.day) return copy;
  const stops = new Map(
    saved.windows.flatMap((window) =>
      window.stops.map((stop) => [stop.drop.commitmentId, stop] as const),
    ),
  );
  return {
    ...copy,
    tour: {
      ...copy.tour,
      tour: {
        ...tour,
        driverOrderedAt: saved.driverOrderedAt,
        revision: saved.revision,
        windows: tour.windows.map((window) => ({
          ...window,
          stops: window.stops.map((stop) => {
            const next = stops.get(stop.drop.commitmentId);
            return next
              ? {
                  ...stop,
                  driverRank: next.driverRank,
                  effectiveRank: next.effectiveRank,
                  newForDriver: next.newForDriver,
                }
              : stop;
          }),
        })),
      },
    },
  };
}

const sameOrder = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((id, index) => id === b[index]);

/** The stop ids of a tour in the order it shows. */
function shownOrder(tour: DeliveryTourResponse): string[] {
  return orderedWindows(tour).flatMap((group) => group.ids);
}

/** The town most stops share; other towns show in the dock's address. */
function homeTown(tour: DeliveryTourResponse | null) {
  const counts = new Map<string, number>();
  for (const window of tour?.windows ?? []) {
    for (const stop of window.stops) {
      const city = stop.drop.address?.city;
      if (city) counts.set(city, (counts.get(city) ?? 0) + 1);
    }
  }
  let best: string | null = null;
  let most = 0;
  for (const [city, count] of counts) {
    if (count > most) {
      best = city;
      most = count;
    }
  }
  return best;
}

const windowOfStop = (stops: ReadonlyMap<string, TourStop>, id: string) =>
  stops.get(id)?.window.windowId ?? "";

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function readFolded() {
  try {
    return window.sessionStorage.getItem(DOCK_FOLDED_KEY) === "1";
  } catch {
    return false;
  }
}

function storeFolded(folded: boolean) {
  try {
    if (folded) window.sessionStorage.setItem(DOCK_FOLDED_KEY, "1");
    else window.sessionStorage.removeItem(DOCK_FOLDED_KEY);
  } catch {
    // Private mode or blocked storage: the fold lasts until reload.
  }
}

/**
 * The dock's height as `--tour-dock-h` on <html>: the list scrolls clear
 * of it and the toaster sits above it. CSSOM only (strict CSP).
 */
function useDockHeight(dock: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const element = dock.current;
    const root = document.documentElement;
    if (!element) return;
    const write = () =>
      root.style.setProperty(
        "--tour-dock-h",
        `${Math.ceil(element.getBoundingClientRect().height)}px`,
      );
    write();
    if (typeof ResizeObserver === "undefined") {
      return () => root.style.removeProperty("--tour-dock-h");
    }
    const observer = new ResizeObserver(write);
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--tour-dock-h");
    };
  }, [dock]);
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
   * The device is offline. The page drops Core's answer from memory and
   * shows the device's tour copy read-only (both flags on, §9), else no
   * stops.
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
  const runtime = useOfflineRuntime();
  // The device keeps the tour only while pwa.offline_queue is on (runtime)
  // and the page itself shows only with delivery.tours (D14 g).
  const deviceStore = runtime.enabled ? runtime.store : null;
  // Offline marks and moves go through the queue (§9).
  const queue = runtime.enabled ? runtime.queue : null;
  const snapshot = useQueueSnapshot();
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
  // The map view lives in the URL too (?view=map).
  const [mapView, setMapViewState] = useState(
    () => new URLSearchParams(window.location.search).get("view") === "map",
  );
  const [sheet, setSheet] = useState<MapSheet | null>(null);
  /** The driver allowed the device location (this page view only). */
  const [locating, setLocating] = useState(false);
  const setMapView = (value: boolean) => {
    setMapViewState(value);
    setSheet(null);
    if (!value) setLocating(false);
    const url = new URL(window.location.href);
    if (value) url.searchParams.set("view", "map");
    else url.searchParams.delete("view");
    window.history.replaceState(window.history.state, "", url);
  };
  /** An open stop the driver tapped: the dock shows it instead of the next. */
  const [shownId, setShownId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  /** Fully done windows the driver opened again. */
  const [openedWindows, setOpenedWindows] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [announcement, setAnnouncement] = useState("");
  const dockHeading = useRef<HTMLHeadingElement | null>(null);
  const focusDock = useRef(false);

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
  // No answer from Core: the device's copy, as without network.
  const unreachable = tourQuery.isError && isNetworkFailure(tourQuery.error);
  const deviceMode = offline || unreachable;
  const deviceQuery = useQuery({
    enabled: deviceMode && Boolean(actionId) && Boolean(deviceStore),
    gcTime: 0,
    networkMode: "always",
    // The view counts as a read; it is sent with the next sync (§10).
    queryFn: () => loadOfflineTour(deviceStore!, actionId, new Date()),
    queryKey: ["my-tour-device", actionId],
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const cachedTour = deviceMode ? (deviceQuery.data ?? null) : null;
  /** The device's copy shows: Core cannot take a write now. */
  const readOnly = Boolean(cachedTour);
  /** Writes wait in the queue: offline copy with a queue. */
  const queued = readOnly && Boolean(queue);
  /** No write at all: the copy without a queue. */
  const locked = readOnly && !queue;
  // Core's answer of today's tour goes to the device (§9), also after a
  // mark or move changed it in place.
  const served = deviceMode ? undefined : tourQuery.data;
  const servedAt = tourQuery.dataUpdatedAt;
  useEffect(() => {
    if (!deviceStore?.open || !served) return;
    void saveTour(
      deviceStore,
      served.actionId,
      served,
      new Date(servedAt),
    ).catch(() => undefined);
  }, [deviceStore, served, servedAt]);
  useEffect(() => {
    if (!deviceMode) queries.removeQueries({ queryKey: ["my-tour-device"] });
  }, [deviceMode, queries]);
  useEffect(() => {
    if (!offline) return;
    queries.removeQueries({ queryKey: ["my-tour"] });
    // Finished commands keep the returned drop (address, phone) as data.
    const mutations = queries.getMutationCache();
    for (const mutation of mutations.findAll({ mutationKey: ["my-tour"] })) {
      mutations.remove(mutation);
    }
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

  const loaded = deviceMode ? cachedTour?.tour : tourQuery.data;
  // The queue's marks and moves of this tour, until Core has them.
  const queueEntries = queue ? snapshot.entries : null;
  const data = useMemo(
    () =>
      loaded && queueEntries ? withQueuedWrites(loaded, queueEntries) : loaded,
    [loaded, queueEntries],
  );
  const tour = data?.tour ?? null;
  // A mark or move left the queue (Core took or refused it): Core's tour
  // shows what came of it.
  const waiting = (queueEntries ?? [])
    .filter(
      (entry) =>
        isTourEntry(entry) &&
        sameAction(entry.actionId, actionId) &&
        (entry.state === "queued" || entry.state === "sending"),
    )
    .map((entry) => entry.entryId)
    .join(",");
  const waited = useRef(waiting);
  useEffect(() => {
    const before = waited.current.split(",").filter(Boolean);
    waited.current = waiting;
    const still = new Set(waiting.split(","));
    if (!deviceMode && before.some((entryId) => !still.has(entryId))) {
      void queries.invalidateQueries({ queryKey: ["my-tour", actionId] });
    }
  }, [actionId, deviceMode, queries, waiting]);
  /** A mark of this stop or a move of this day still waits in the queue. */
  const waits = (
    match: (entry: (typeof snapshot.entries)[number]) => boolean,
  ) =>
    Boolean(
      queueEntries?.some(
        (entry) =>
          sameAction(entry.actionId, actionId) &&
          (entry.state === "queued" || entry.state === "sending") &&
          match(entry),
      ),
    );
  const zone = data?.timezone ?? "Europe/Berlin";
  const tiles = useMemo(
    () =>
      data?.map
        ? { url: data.map.tileUrl, attribution: data.map.attribution }
        : null,
    [data?.map],
  );
  const startPoint = data?.startPoint;
  const start = useMemo<MapStart | null>(
    () =>
      startPoint && startPoint.lat !== null && startPoint.lon !== null
        ? { lat: startPoint.lat, lon: startPoint.lon, label: startPoint.label }
        : null,
    [startPoint],
  );

  const model = useMemo(() => {
    const stops = new Map<string, TourStop>();
    const windows = tour ? orderedWindows(tour) : [];
    for (const { window } of windows) {
      for (const stop of window.stops) {
        stops.set(stop.drop.commitmentId, {
          drop: stop.drop,
          lat: stop.lat,
          lon: stop.lon,
          newForDriver: stop.newForDriver,
          window,
        });
      }
    }
    return {
      stops,
      windows,
      order: windows.flatMap((group) => group.ids),
      town: homeTown(tour),
    };
  }, [tour]);
  const windowOf = (id: string) => windowOfStop(model.stops, id);

  // Each move saves at once (D16); a conflict reloads the tour.
  // Day, action and cache entry are those of the move, never of the page
  // at the time the save goes out (the driver may switch the day first).
  const autosave = useOrderAutosave<DeliveryTourResponse, OrderContext>({
    save: (_key, ids, revision, context) =>
      client.saveMyTourOrder(context.actionId, {
        commitmentIds: [...ids],
        day: context.day,
        expectedRevision: revision,
      }),
    revisionOf: (saved) => saved.revision,
    onSaved: (_key, saved, context) => {
      queries.setQueryData<MyTourResponse>(context.queryKey, (current) =>
        current?.tour?.day === saved.day
          ? { ...current, tour: saved }
          : current,
      );
      // Offline meanwhile: the device copy takes Core's answer too, so the
      // saved order stays on screen and later moves build on it.
      const deviceKey = ["my-tour-device", context.actionId];
      const shown = queries.getQueryData<CachedTour | null>(deviceKey);
      if (!shown) return;
      const patched = withSavedOrder(shown, saved);
      if (patched === shown) return;
      queries.setQueryData(deviceKey, patched);
      if (deviceStore?.open) {
        void saveTour(
          deviceStore,
          context.actionId,
          patched.tour,
          new Date(patched.fetchedAt),
        ).catch(() => undefined);
      }
    },
    onFailed: (_key, error, context) => {
      toast?.show({ title: errorText(error), tone: "error" });
      if (isStale(error)) {
        void queries.invalidateQueries({ queryKey: context.queryKey });
      }
    },
    // No answer from Core (network gone, gateway error): the order goes to
    // the offline queue as one that may be at Core already (§9).
    // The sent order is its own entry (Core takes it again without a
    // conflict if it got there); a move made while it ran follows it as a
    // normal entry, which takes the revision Core returns for the first.
    divert: async (_key, error, draft) => {
      if (!queue || !isNetworkFailure(error)) return false;
      const later = !sameOrder(draft.ids, draft.sent);
      await queueOrder(
        {
          commitmentIds: draft.sent,
          day: draft.context.day,
          everSent: true,
          expectedRevision: draft.revision,
          fromOrder: draft.confirmed,
        },
        draft.baseline,
        {
          offlineText: true,
          silent: draft.silent || later,
          undo: draft.undo,
        },
      );
      if (later) {
        await queueOrder(
          {
            commitmentIds: draft.ids,
            day: draft.context.day,
            expectedRevision: draft.revision,
            fromOrder: draft.sent,
          },
          draft.baseline,
          { offlineText: true, silent: draft.silent, undo: draft.undo },
        );
      }
      return true;
    },
    savedText: () => copy.saved,
    undoneText: () => copy.undone,
  });

  // Null without a tour: nothing to move or to send.
  const tourKey = tour ? orderKey(actionId, tour.day) : null;
  // The order on screen: a move that is saving, kept to the known stops
  // (the server may add or drop one meanwhile), else the server's.
  // An offline move waiting for a running save of its day shows at once,
  // over the save's own order (it is newer).
  const [queuing, setQueuing] = useState<{
    readonly day: string;
    readonly order: readonly string[];
    readonly seq: number;
  } | null>(null);
  const pending =
    queuing && tour && queuing.day === tour.day
      ? queuing.order
      : tourKey
        ? autosave.orderOf(tourKey)
        : null;
  const order = useMemo(
    () =>
      pending
        ? reconcileOrder(pending, model.order, (id) =>
            windowOfStop(model.stops, id),
          )
        : model.order,
    [pending, model],
  );

  const counted = order
    .map((id) => model.stops.get(id)!)
    .filter((stop) => deliverable(stop.drop));
  const deliveredCount = counted.filter(
    (stop) => stop.drop.state === "delivered",
  ).length;
  const settled =
    counted.length > 0 && counted.every((stop) => stop.drop.state !== "open");
  const isOpenStop = (id: string) => {
    const stop = model.stops.get(id);
    return Boolean(
      stop && stop.drop.state === "open" && deliverable(stop.drop),
    );
  };
  const nextId = order.find(
    (id) => isOpenStop(id) && !model.stops.get(id)!.window.closed,
  );
  const dockId = shownId && isOpenStop(shownId) ? shownId : nextId;

  // After a mark the dock shows the next stop; focus follows it.
  useEffect(() => {
    if (!focusDock.current) return;
    focusDock.current = false;
    dockHeading.current?.focus();
  }, [dockId]);

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

  /** The stop as shown now (queued marks included). */
  const shownDrop = (commitmentId: string) =>
    latest.current?.tour?.windows
      .flatMap((window) => window.stops)
      .find((stop) => stop.drop.commitmentId === commitmentId)?.drop;

  /**
   * Offline (or while an earlier mark of the stop still waits): the mark
   * goes to the queue and shows at once. An undo of an unsent mark deletes
   * it (§9).
   */
  const markQueued = (drop: DeliveryDropResponse, target: Target) => {
    if (!queue) return;
    const name = stopName(drop);
    const leavesDock = target !== "open" && drop.commitmentId === dockId;
    void queue
      .queueDeliveryState({
        actionId,
        commitmentId: drop.commitmentId,
        displayName: name,
        expectedRevision: drop.revision,
        fromState: drop.state,
        target,
      })
      .then(
        (outcome) => {
          // A repeated tap: the queue holds this already.
          if (outcome === "unchanged") return;
          if (leavesDock) {
            // The dock moves on to the next open stop, without scrolling.
            setShownId(null);
            focusDock.current = true;
          }
          toast?.show({
            // Cleared: the unsent mark is gone, nothing is to be sent.
            // Online behind an earlier mark of the stop: it goes out now.
            title:
              queued && outcome === "queued"
                ? copy.queued[target](name)
                : copy.toast[target](name),
            tone: target === "delivered" ? "success" : "info",
            timeout: TOUR_UNDO_MS,
            action:
              target === "open"
                ? undefined
                : {
                    label: "Rückgängig",
                    run: () => {
                      const current = shownDrop(drop.commitmentId);
                      if (current) mark(current, "open");
                    },
                  },
          });
        },
        () => toast?.show({ title: copy.queued.failed, tone: "error" }),
      );
  };

  const mark = (drop: DeliveryDropResponse, target: Target) => {
    if (locked || !deliverable(drop)) return;
    if (
      queued ||
      waits(
        (entry) =>
          entry.kind === "delivery-state" &&
          entry.commitmentId === drop.commitmentId,
      )
    ) {
      markQueued(drop, target);
      return;
    }
    if (ticking.current) return;
    ticking.current = true;
    const name = stopName(drop);
    setState.mutate(
      { drop, target },
      {
        onSuccess: (updated) => {
          if (target !== "open" && drop.commitmentId === dockId) {
            // The dock moves on to the next open stop, without scrolling.
            setShownId(null);
            focusDock.current = true;
          }
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
          });
        },
      },
    );
  };

  const resetOrder = useMutation({
    ...mutationOptions,
    mutationFn: (current: DeliveryTourResponse) =>
      client.saveMyTourOrder(actionId, {
        commitmentIds: [],
        day: current.day,
        expectedRevision: current.revision,
      }),
    onSuccess: (updated) => {
      queries.setQueryData<MyTourResponse>(queryKey, (current) =>
        current ? { ...current, tour: updated } : current,
      );
      toast?.show({ title: copy.resetDone, tone: "success" });
    },
    onError: (error) => {
      toast?.show({ title: errorText(error), tone: "error" });
      if (isStale(error)) void refresh();
    },
  });

  /** The toast of the last queued move; the next move replaces it. */
  const orderToast = useRef<string | null>(null);
  /**
   * One order into the queue, with its toast; "Rückgängig" goes back to
   * `before`, the order the driver saw before the move.
   */
  const queueOrder = (
    request: {
      readonly commitmentIds: readonly string[];
      readonly day: string;
      readonly expectedRevision: string;
      readonly fromOrder: readonly string[];
      readonly everSent?: boolean;
    },
    before: readonly string[],
    {
      offlineText,
      silent = false,
      undo = false,
    }: { offlineText: boolean; silent?: boolean; undo?: boolean },
  ) => {
    if (!queue) return Promise.resolve();
    return queue
      .queueTourOrder({
        ...request,
        actionId,
        displayName: shortDay(request.day),
      })
      .then(
        (outcome) => {
          if (outcome === "unchanged" || silent) return;
          // Cleared: back at the order Core has, nothing is to be sent.
          const back = undo || outcome === "cleared";
          if (orderToast.current) toast?.dismiss(orderToast.current);
          orderToast.current =
            toast?.show({
              title: back
                ? copy.queued.orderUndone
                : offlineText
                  ? copy.queued.order
                  : copy.queued.orderSending,
              tone: "success",
              timeout: TOUR_UNDO_MS,
              action: back
                ? undefined
                : {
                    label: "Rückgängig",
                    // The tour as it is then: the move may have reached
                    // Core meanwhile, with a new revision.
                    run: () => {
                      const shown = latest.current?.tour;
                      if (!shown || shown.day !== request.day) return;
                      void moveQueued(shown, before, shownOrder(shown), true);
                    },
                  },
            }) ?? null;
        },
        () => {
          toast?.show({ title: copy.queued.failed, tone: "error" });
        },
      );
  };
  /**
   * Offline (or while an earlier move of the day still waits): the order
   * goes to the queue; a newer move replaces an unsent one (§9). A save of
   * the day still running first: the move builds on what it returns, so
   * the driver's own order never counts as the planner's change.
   */
  const queuingSeq = useRef(0);
  /** Offline moves go to the queue one after the other. */
  const queuingChain = useRef<Promise<void>>(Promise.resolve());
  const moveQueued = (
    current: DeliveryTourResponse,
    next: readonly string[],
    before: readonly string[],
    undo = false,
  ) => {
    if (!queue) return Promise.resolve();
    const offlineText = queued;
    // The copy or answer the move was made on, and when Core gave it.
    const baseAt = cachedTour
      ? Date.parse(cachedTour.fetchedAt)
      : tourQuery.dataUpdatedAt;
    // Shows at once; a next move builds on it and queues behind it.
    const seq = (queuingSeq.current += 1);
    setQueuing({ day: current.day, order: [...next], seq });
    const run = queuingChain.current
      .then(async () => {
        const own = await autosave.settle(orderKey(actionId, current.day));
        const fresh = own && own.at > baseAt ? own : null;
        await queueOrder(
          {
            commitmentIds: next,
            day: current.day,
            expectedRevision: fresh?.revision ?? current.revision,
            fromOrder: fresh?.order ?? shownOrder(current),
          },
          before,
          { offlineText, undo },
        );
      })
      // The queue shows it now (or refused it): the local order goes.
      .finally(() =>
        setQueuing((shown) => (shown?.seq === seq ? null : shown)),
      );
    queuingChain.current = run.catch(() => undefined);
    return run;
  };

  const moveStopTo = (
    id: string,
    targetId: string,
    side: "before" | "after",
  ) => {
    if (!tour || locked) return;
    const next = placeStop(order, id, targetId, side, windowOf);
    if (next.every((value, index) => value === order[index])) return;
    if (
      queued ||
      waits(
        (entry) =>
          entry.kind === "tour-order" && entry.request.day === tour.day,
      )
    ) {
      void moveQueued(tour, next, order);
    } else {
      autosave.move(orderKey(actionId, tour.day), next, order, tour.revision, {
        actionId,
        day: tour.day,
        queryKey,
      });
    }
    const stop = model.stops.get(id);
    if (stop) {
      setAnnouncement(
        `${stopName(stop.drop)} ist jetzt Stopp ${next.indexOf(id) + 1}.`,
      );
    }
  };

  const toggle = (setter: typeof setExpanded) => (id: string) =>
    setter((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleExpanded = toggle(setExpanded);
  const toggleWindow = toggle(setOpenedWindows);

  // A waiting move goes out first, for the day and action it was made in;
  // every tour's, also one a refetch took off the screen meanwhile.
  const chooseAction = (value: string) => {
    autosave.releaseAll();
    setDay(null);
    setShownId(null);
    replaceActionInUrl(value);
  };
  const chooseDay = (value: string) => {
    autosave.releaseAll();
    setDay(value);
    setShownId(null);
  };

  const bar = (
    <TourBar
      actionId={actionId}
      actions={actions}
      data={data}
      delivered={deliveredCount}
      mapView={mapView}
      onAction={chooseAction}
      onDay={chooseDay}
      onToggleMap={tour && order.length ? () => setMapView(!mapView) : null}
      readOnly={readOnly}
      onReset={() => {
        // The reset replaces a waiting move; it waits for a running save
        // and then uses the revision that save returned.
        if (!tourKey) return;
        void autosave.cancel(tourKey).then(() => {
          const current =
            queries.getQueryData<MyTourResponse>(queryKey)?.tour ?? tour;
          if (current) resetOrder.mutate(current);
        });
      }}
      resetting={resetOrder.isPending}
      total={counted.length}
    />
  );

  const frame = (children: ReactNode) => (
    <div className="delivery tour" data-zone="delivery">
      <h1 className="sr-only">{copy.title}</h1>
      {bar}
      {cachedTour ? (
        <p className="tour-offline" data-testid="tour-offline" role="status">
          <strong>
            {copy.offlineStand(clockTime(cachedTour.fetchedAt, zone))}
          </strong>
          <span>{queued ? copy.offlineQueueHint : copy.offlineHint}</span>
        </p>
      ) : null}
      {children}
    </div>
  );

  // Someone who drives for no action (a manager on /app/delivery), also
  // offline: no tour to look for on the device.
  if (!actionId) {
    return frame(
      <EmptyState
        description={copy.noAction}
        headingLevel={2}
        icon={Truck}
        title="Keine Aktion gewählt"
      />,
    );
  }

  if (deviceMode && !cachedTour) {
    if (deviceStore && actionId && deviceQuery.isPending) {
      return frame(<SkeletonRows rows={5} />);
    }
    // Online with Core out of reach and no copy: the error state below.
    if (offline) {
      return frame(
        <EmptyState
          description={deviceStore ? copy.offlineEmpty : copy.offline}
          headingLevel={2}
          icon={Truck}
          title="Keine Verbindung"
        />,
      );
    }
  }

  const notEnabled =
    tourQuery.error instanceof ApiError &&
    ["delivery_not_enabled", "feature_flag_disabled"].includes(
      tourQuery.error.detail.code,
    );

  if (!readOnly && tourQuery.isPending) return frame(<SkeletonRows rows={5} />);
  if (!readOnly && notEnabled) {
    return frame(
      <EmptyState
        description={copy.notEnabled}
        headingLevel={2}
        icon={Truck}
        title="Keine Lieferplanung"
      />,
    );
  }
  if (!readOnly && tourQuery.isError) {
    return frame(
      <ErrorState onRetry={() => void tourQuery.refetch()} title={copy.error}>
        {copy.errorHint}
      </ErrorState>,
    );
  }
  if (!tour || order.length === 0) {
    return frame(
      <EmptyState
        description={copy.nothingHint}
        headingLevel={2}
        icon={Truck}
        title={copy.nothing}
      />,
    );
  }

  const dockStop = dockId ? model.stops.get(dockId) : undefined;
  const dockWindowEnded = dockStop
    ? windowHint(dockStop.window.startsAt, dockStop.window.endsAt, now).kind ===
      "ended"
    : false;
  const dock = (sheetMode: boolean) => (
    <TourDock
      busy={setState.isPending || locked}
      delivered={deliveredCount}
      headingRef={dockHeading}
      isNext={dockId === nextId}
      map={
        sheetMode || !tiles
          ? null
          : {
              onOpen: () => {
                setMapView(true);
                setSheet({ kind: "stop" });
              },
              tiles,
            }
      }
      onClose={sheetMode ? () => setSheet(null) : undefined}
      onMark={(target) => {
        if (dockStop) mark(dockStop.drop, target);
      }}
      onShowNext={() => setShownId(null)}
      position={dockId ? order.indexOf(dockId) + 1 : 0}
      settled={settled}
      stop={dockStop}
      total={counted.length}
      town={model.town}
      windowEnded={dockWindowEnded}
    />
  );

  if (mapView && tiles) {
    // §7.2: numbered pins in effective order, the start point, a line
    // through the open stops; a tapped pin opens its stop as a sheet.
    const selectedId =
      sheet?.kind === "done" ? sheet.id : sheet ? dockId : nextId;
    const pins: TourMapPin[] = order.flatMap((id, index) => {
      const stop = model.stops.get(id)!;
      if (stop.lat === null || stop.lon === null) return [];
      return [
        {
          id,
          label: `${copy.stop(index + 1)}: ${stopName(stop.drop)}`,
          lat: stop.lat,
          lon: stop.lon,
          rank: index + 1,
          selected: id === selectedId,
          tone: isOpenStop(id) ? ("driver-0" as const) : ("done" as const),
        },
      ];
    });
    const sheetStop =
      sheet?.kind === "done" ? model.stops.get(sheet.id) : undefined;
    return frame(
      <>
        <div className="tour-mapview" data-testid="tour-mapview">
          <TourMap
            label={copy.mapLabel}
            line={{ ids: order.filter(isOpenStop), dashed: false }}
            onLocationError={() => {
              setLocating(false);
              toast?.show({ title: copy.noLocation, tone: "info" });
            }}
            onSelect={(id) => {
              if (isOpenStop(id)) {
                setShownId(id === nextId ? null : id);
                setSheet({ kind: "stop" });
              } else {
                setSheet({ kind: "done", id });
              }
            }}
            pins={pins}
            showLocation={locating}
            start={start}
            tiles={tiles}
          />
          {pins.length ? null : (
            <p className="tour-mapview-empty">{copy.noPins}</p>
          )}
          <div className="tour-mapview-tools">
            <Button
              aria-pressed={locating}
              icon={LocateFixed}
              onClick={() => setLocating((value) => !value)}
              size="lg"
              variant="secondary"
            >
              {copy.myLocation}
            </Button>
          </div>
        </div>
        {sheet?.kind === "stop" ? dock(true) : null}
        {sheetStop ? (
          <DoneSheet
            busy={setState.isPending || locked}
            onClose={() => setSheet(null)}
            onUndo={() => {
              setSheet(null);
              mark(sheetStop.drop, "open");
            }}
            position={order.indexOf(sheetStop.drop.commitmentId) + 1}
            stop={sheetStop}
            zone={zone}
          />
        ) : null}
      </>,
    );
  }

  return frame(
    <>
      <p aria-live="polite" className="sr-only" role="status">
        {announcement}
      </p>
      <div className="tour-list">
        {model.windows.map(({ window }) => {
          const ids = order.filter((id) => windowOf(id) === window.windowId);
          const active = ids
            .map((id) => model.stops.get(id)!.drop)
            .filter(deliverable);
          const done = active.filter(
            (drop) => drop.state === "delivered",
          ).length;
          const allDone =
            active.length > 0 && active.every((drop) => drop.state !== "open");
          const hint = windowHint(window.startsAt, window.endsAt, now);
          const folded = allDone && !openedWindows.has(window.windowId);
          const movable =
            window.closed || locked ? [] : ids.filter((id) => isOpenStop(id));
          const rows = (
            <ol
              className="tour-rows"
              hidden={folded}
              id={`tour-rows-${window.windowId}`}
            >
              {ids.map((id) => {
                const stop = model.stops.get(id)!;
                const position = order.indexOf(id) + 1;
                return isOpenStop(id) ? (
                  <OpenRow
                    current={id === dockId}
                    key={id}
                    movable={movable.length > 1 && movable.includes(id)}
                    onShow={() => setShownId(id === nextId ? null : id)}
                    position={position}
                    stop={stop}
                  />
                ) : (
                  <DoneRow
                    busy={setState.isPending || locked}
                    expanded={expanded.has(id)}
                    key={id}
                    onToggle={() => toggleExpanded(id)}
                    onUndo={() => mark(stop.drop, "open")}
                    position={position}
                    stop={stop}
                    zone={zone}
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
              <WindowLabel
                allDone={allDone}
                closed={window.closed}
                count={active.length}
                delivered={done}
                folded={folded}
                hint={hint}
                id={`tour-win-${window.windowId}`}
                label={`${deliveryTimeRange(window, zone)} Uhr`}
                onToggle={() => toggleWindow(window.windowId)}
                rowsId={`tour-rows-${window.windowId}`}
              />
              {movable.length > 1 ? (
                <TaskOrdering
                  ids={movable}
                  noun="Stopp"
                  onCancel={() => setAnnouncement("Verschieben abgebrochen.")}
                  onMove={moveStopTo}
                  touch="handle"
                >
                  {rows}
                </TaskOrdering>
              ) : (
                rows
              )}
            </section>
          );
        })}
      </div>
      {dock(false)}
    </>,
  );
}

/**
 * The app bar part of the page (critique §3 A): "Meine Tour · Sa 05.12."
 * under the action name, then "2/7" and the ⋮ menu; the meter is the bar's
 * lower edge. Inside the PWA shell it fills the shell's bar; elsewhere
 * (tests, previews) it renders as the page's own bar.
 */
function TourBar({
  actionId,
  actions,
  data,
  delivered,
  mapView,
  onAction,
  onDay,
  onReset,
  onToggleMap,
  readOnly,
  resetting,
  total,
}: {
  readonly actionId: string;
  readonly actions: readonly {
    readonly actionId: string;
    readonly actionName: string;
  }[];
  readonly data: MyTourResponse | undefined;
  readonly delivered: number;
  readonly mapView: boolean;
  readonly onAction: (actionId: string) => void;
  readonly onDay: (day: string) => void;
  readonly onReset: () => void;
  /** Null without stops: nothing to show on a map. */
  readonly onToggleMap: (() => void) | null;
  /** The device's copy offline: no order changes. */
  readonly readOnly: boolean;
  readonly resetting: boolean;
  readonly total: number;
}) {
  const shell = usePageBar();
  const tour = data?.tour ?? null;
  const own = Boolean(tour?.driverOrderedAt);
  const sub = (
    <span className="tour-bar-sub" data-testid="tour-bar-sub">
      {copy.title}
      {tour ? (
        <>
          {" · "}
          <span data-testid="tour-day">{shortDay(tour.day)}</span>
        </>
      ) : null}
      {own ? ` · ${copy.ownOrder}` : null}
    </span>
  );
  const end = (
    <>
      {tour && total > 0 ? (
        <>
          <span
            aria-label={`${delivered} von ${total} zugestellt`}
            className="tour-bar-count num"
            data-testid="tour-progress"
            role="img"
          >
            {delivered}/{total}
          </span>
          <span className="tour-bar-meter" data-zone="delivery">
            <Meter
              label={`${delivered} von ${total} zugestellt`}
              max={total}
              tone={delivered === total ? "ok" : "zone"}
              value={delivered}
            />
          </span>
        </>
      ) : null}
      {onToggleMap ? (
        <button
          aria-pressed={mapView}
          className="tour-bar-toggle"
          data-testid="tour-map-toggle"
          onClick={onToggleMap}
          title={copy.map}
          type="button"
        >
          <MapIcon aria-hidden="true" size={20} />
          <span className="sr-only">{copy.map}</span>
        </button>
      ) : null}
      <TourMenu
        actionId={actionId}
        actions={actions}
        days={data?.days ?? []}
        day={tour?.day ?? null}
        onAction={onAction}
        onDay={onDay}
        onReset={own && !readOnly ? onReset : null}
        resetting={resetting}
      />
    </>
  );
  if (shell?.sub && shell.end) {
    return (
      <>
        <PageBarPortal slot="sub">{sub}</PageBarPortal>
        <PageBarPortal slot="end">{end}</PageBarPortal>
      </>
    );
  }
  return (
    <header className="tour-bar is-inline">
      <span className="tour-bar-title">
        <span className="tour-bar-name">{data?.actionName ?? copy.title}</span>
        {sub}
      </span>
      <span className="tour-bar-end">{end}</span>
    </header>
  );
}

/** ⋮: "Zurück zur Planung" (own order only), day and action (several). */
function TourMenu({
  actionId,
  actions,
  day,
  days,
  onAction,
  onDay,
  onReset,
  resetting,
}: {
  readonly actionId: string;
  readonly actions: readonly {
    readonly actionId: string;
    readonly actionName: string;
  }[];
  readonly day: string | null;
  readonly days: readonly string[];
  readonly onAction: (actionId: string) => void;
  readonly onDay: (day: string) => void;
  readonly onReset: (() => void) | null;
  readonly resetting: boolean;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  if (!onReset && days.length <= 1 && actions.length <= 1) return null;
  return (
    <>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={copy.menu}
        className="tour-bar-menu"
        data-testid="tour-menu"
        onClick={() => setOpen((value) => !value)}
        ref={anchor}
        title={copy.menu}
        type="button"
      >
        <EllipsisVertical aria-hidden="true" size={20} />
      </button>
      <Popover
        align="end"
        anchor={anchor}
        label={copy.menu}
        onClose={() => setOpen(false)}
        open={open}
      >
        <div className="tour-menu">
          {actions.length > 1 ? (
            <label className="tour-menu-field">
              <span>Aktion</span>
              <select
                className="input select"
                data-testid="tour-action"
                onChange={(event) => {
                  setOpen(false);
                  onAction(event.target.value);
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
          {days.length > 1 ? (
            <label className="tour-menu-field">
              <span>Liefertag</span>
              <select
                className="input select"
                data-testid="tour-day-select"
                onChange={(event) => {
                  setOpen(false);
                  onDay(event.target.value);
                }}
                value={day ?? ""}
              >
                {days.map((item) => (
                  <option key={item} value={item}>
                    {shortDay(item)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {onReset ? (
            <Button
              data-testid="tour-reset-order"
              icon={Undo2}
              loading={resetting}
              onClick={() => {
                setOpen(false);
                onReset();
              }}
              size="lg"
              variant="secondary"
            >
              {copy.reset}
            </Button>
          ) : null}
        </div>
      </Popover>
    </>
  );
}

/**
 * The sticky label of a window (critique §3 B): "08–10 Uhr · 2/3", the
 * time hint, and "Abgeschlossen". A fully done window folds to one line
 * that opens on tap.
 */
function WindowLabel({
  allDone,
  closed,
  count,
  delivered,
  folded,
  hint,
  id,
  label,
  onToggle,
  rowsId,
}: {
  readonly allDone: boolean;
  readonly closed: boolean;
  readonly count: number;
  readonly delivered: number;
  readonly folded: boolean;
  readonly hint: WindowHint;
  readonly id: string;
  readonly label: string;
  readonly onToggle: () => void;
  readonly rowsId: string;
}) {
  const extra = (
    <>
      {hint.kind === "running" && !allDone ? (
        <span className="tour-label-hint">noch {hint.minutesLeft} min</span>
      ) : null}
      {hint.kind === "ended" && !allDone && !closed ? (
        <span className="tour-label-hint is-warn">{copy.ended}</span>
      ) : null}
      {closed ? <span className="stamp tone-ok">{copy.closed}</span> : null}
    </>
  );
  if (allDone) {
    const summary =
      delivered === count
        ? `alle ${count} zugestellt`
        : `alle ${count} erledigt`;
    return (
      <h2 className="tour-label" id={id}>
        <button
          aria-controls={rowsId}
          aria-expanded={!folded}
          className="tour-label-toggle"
          onClick={onToggle}
          type="button"
        >
          <span>
            {label} · {summary}
          </span>
          <Icon className="tour-label-chevron" icon={ChevronDown} size={16} />
        </button>
        {extra}
      </h2>
    );
  }
  return (
    <h2 className="tour-label" id={id}>
      <span>
        {label} ·{" "}
        <span className="num">
          {delivered}/{count}
        </span>
      </span>
      {extra}
    </h2>
  );
}

function stateLabel(drop: DeliveryDropResponse) {
  if (!deliverable(drop)) return copy.cancelled;
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

/**
 * An open stop, 56 px: grip, number, name over street, quantity. A tap
 * shows it in the dock; the stop in the dock carries the zone line.
 */
function OpenRow({
  current,
  movable,
  onShow,
  position,
  stop,
}: {
  readonly current: boolean;
  readonly movable: boolean;
  readonly onShow: () => void;
  readonly position: number;
  readonly stop: TourStop;
}) {
  const { drop } = stop;
  const name = stopName(drop);
  return (
    <li
      className={cn("row tour-row", current && "is-current")}
      data-commitment-id={drop.commitmentId}
      data-testid="tour-stop"
    >
      {movable ? (
        <TaskOrderHandle
          disabled={false}
          id={drop.commitmentId}
          noun="Stopp"
          title={name}
        />
      ) : (
        <span aria-hidden="true" className="tour-handle-space" />
      )}
      <span className="tour-pos num">{position}</span>
      <button
        aria-current={current ? "true" : undefined}
        className="tour-row-main"
        onClick={onShow}
        type="button"
      >
        <span className="tour-row-head">
          <span className="tour-row-name" data-testid="tour-stop-name">
            {name}
          </span>
          {stop.newForDriver ? <Badge tone="zone">{copy.isNew}</Badge> : null}
        </span>
        <span className="tour-row-street">
          {drop.address?.streetLine1 ?? copy.noAddress}
        </span>
        <DriverNote className="tour-row-note" drop={drop} />
      </button>
      <span className="tour-row-qty num">{dropQuantitiesShort(drop)}</span>
    </li>
  );
}

/**
 * A done, missed or cancelled stop, 48 px and grey (D15). A tap opens a
 * compact panel: address, quantity, time of the mark and "Rückgängig".
 */
function DoneRow({
  busy,
  expanded,
  onToggle,
  onUndo,
  position,
  stop,
  zone,
}: {
  readonly busy: boolean;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly onUndo: () => void;
  readonly position: number;
  readonly stop: TourStop;
  readonly zone: string;
}) {
  const { drop, window } = stop;
  const id = drop.commitmentId;
  const name = stopName(drop);
  const address = dropAddress(drop);
  const undoable = deliverable(drop) && !window.closed;
  return (
    <li
      className={cn(
        "row tour-row is-done",
        !deliverable(drop) && "is-cancelled",
        expanded && "is-expanded",
      )}
      data-commitment-id={id}
      data-testid="tour-stop-done"
    >
      <span aria-hidden="true" className="tour-handle-space" />
      <span className="tour-pos num">{position}</span>
      <button
        aria-controls={expanded ? `tour-done-${id}` : undefined}
        aria-expanded={expanded}
        className="tour-row-main"
        onClick={onToggle}
        type="button"
      >
        <span className="tour-row-name" data-testid="tour-stop-name">
          {name}
        </span>
      </button>
      <span className="tour-row-state">
        <StatusIcon
          label={stateLabel(drop)}
          size={20}
          status={stateShape(drop)}
        />
      </span>
      {expanded ? (
        <div className="tour-done-panel" id={`tour-done-${id}`}>
          <p>{address ?? copy.noAddress}</p>
          <DriverNote drop={drop} full />
          <p className="num">{dropQuantities(drop)}</p>
          <p className="tour-done-state">
            {stateLabel(drop)}
            {drop.stateChangedAt
              ? ` um ${clockMinutes(drop.stateChangedAt, zone)} Uhr`
              : ""}
          </p>
          {undoable ? (
            <Button
              className="tour-done-undo"
              disabled={busy}
              icon={Undo2}
              onClick={onUndo}
              size="lg"
              variant="secondary"
            >
              Rückgängig
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * The fixed "Nächster Stopp" dock (critique §3 C): name and quantity,
 * address, map, Navigation / Anrufen / Nicht da, and "Zugestellt" in thumb
 * reach. It folds to name, quantity and "Zugestellt" for scanning the list.
 */
function TourDock({
  busy,
  delivered,
  headingRef,
  isNext,
  map,
  onClose,
  onMark,
  onShowNext,
  position,
  settled,
  stop,
  total,
  town,
  windowEnded,
}: {
  readonly busy: boolean;
  readonly delivered: number;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly isNext: boolean;
  /** The inline map; null in the map view's sheet. */
  readonly map: DockMap | null;
  /** Set: the dock is the map view's sheet and can close. */
  readonly onClose?: () => void;
  readonly onMark: (target: Target) => void;
  readonly onShowNext: () => void;
  readonly position: number;
  readonly settled: boolean;
  readonly stop: TourStop | undefined;
  readonly total: number;
  readonly town: string | null;
  readonly windowEnded: boolean;
}) {
  const dock = useRef<HTMLElement | null>(null);
  useDockHeight(dock);
  const [folded, setFolded] = useState(readFolded);
  const swipe = useRef<{ start: number; end: number } | null>(null);
  const fold = (value: boolean) => {
    setFolded(value);
    storeFolded(value);
  };
  const onGripDown = (event: PointerEvent<HTMLButtonElement>) => {
    swipe.current = { start: event.clientY, end: event.clientY };
  };
  const onGripUp = (event: PointerEvent<HTMLButtonElement>) => {
    if (swipe.current) swipe.current.end = event.clientY;
  };
  const onGripClick = () => {
    const moved = swipe.current ? swipe.current.end - swipe.current.start : 0;
    swipe.current = null;
    if (moved > DOCK_SWIPE_PX) fold(true);
    else if (moved < -DOCK_SWIPE_PX) fold(false);
    else fold(!folded);
  };

  const drop = stop?.drop;
  const body =
    !stop || !drop ? (
      <div className="tour-dock-body tour-dock-done" key="done">
        <p className="tour-dock-done-title" ref={headingRef} tabIndex={-1}>
          {settled
            ? delivered === total
              ? copy.allDelivered(total)
              : copy.allSettled(delivered, total)
            : copy.onlyClosedLeft}
        </p>
        {settled ? <p className="tour-dock-muted">{copy.tellLead}</p> : null}
      </div>
    ) : (
      <DockStop
        busy={busy}
        folded={folded}
        headingRef={headingRef}
        isNext={isNext}
        key={drop.commitmentId}
        map={map}
        onMark={onMark}
        onShowNext={onShowNext}
        position={position}
        stop={stop}
        town={town}
        windowEnded={windowEnded}
      />
    );
  return (
    <section
      aria-label={isNext || !stop ? copy.next : copy.stop(position)}
      className={cn("tour-dock", folded && stop && "is-folded")}
      data-testid="tour-dock"
      ref={dock}
    >
      {onClose ? (
        <Button
          aria-label={copy.closeSheet}
          className="tour-dock-close"
          icon={X}
          onClick={onClose}
          size="lg"
          title={copy.closeSheet}
          variant="ghost"
        />
      ) : null}
      {stop ? (
        <button
          aria-expanded={!folded}
          aria-label={
            folded ? "Stoppkarte aufklappen" : "Stoppkarte einklappen"
          }
          className="tour-dock-grip"
          onClick={onGripClick}
          onPointerDown={onGripDown}
          onPointerUp={onGripUp}
          type="button"
        >
          <span aria-hidden="true" />
        </button>
      ) : null}
      {body}
    </section>
  );
}

function DockStop({
  busy,
  folded,
  headingRef,
  isNext,
  map,
  onMark,
  onShowNext,
  position,
  stop,
  town,
  windowEnded,
}: {
  readonly busy: boolean;
  readonly folded: boolean;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly isNext: boolean;
  readonly map: DockMap | null;
  readonly onMark: (target: Target) => void;
  readonly onShowNext: () => void;
  readonly position: number;
  readonly stop: TourStop;
  readonly town: string | null;
  readonly windowEnded: boolean;
}) {
  const { drop, window } = stop;
  const name = stopName(drop);
  const address = dropAddress(drop);
  const tel = callHref(drop.contact?.phone ?? null, null);
  const contactName = drop.contact?.name || name;
  const navigation = address
    ? navigationHref(
        { address, lat: stop.lat, lon: stop.lon },
        devicePlatform(navigator.userAgent),
      )
    : null;
  const external = navigation?.startsWith("https:") ?? false;
  const canMark = deliverable(drop) && !window.closed;
  const deliver = (
    <Button
      className="tour-go"
      disabled={busy}
      icon={Check}
      onClick={() => onMark("delivered")}
      size="lg"
      variant="primary"
    >
      {copy.delivered}
    </Button>
  );
  const head = (
    <div className="tour-dock-head">
      <span className="tour-pos num">{position}</span>
      <div className="tour-dock-title">
        <h2 id="tour-dock-name" ref={headingRef} tabIndex={-1}>
          {name}
        </h2>
        {!folded && name !== drop.buyerName ? (
          <p className="tour-dock-muted">für {drop.buyerName}</p>
        ) : null}
      </div>
      <span className="tour-qty num" data-testid="tour-dock-qty">
        {dropQuantitiesShort(drop)}
      </span>
    </div>
  );
  if (folded) {
    return (
      <div className="tour-dock-body is-folded" data-testid="tour-next-stop">
        {head}
        {canMark ? deliver : null}
      </div>
    );
  }
  return (
    <div className="tour-dock-body" data-testid="tour-next-stop">
      {isNext ? null : (
        <p className="tour-dock-eyebrow">
          <span>{copy.stop(position)}</span>
          <button className="tour-dock-back" onClick={onShowNext} type="button">
            {copy.toNext}
          </button>
        </p>
      )}
      {head}
      {stop.newForDriver || (windowEnded && !window.closed) ? (
        <p className="tour-dock-flags">
          {stop.newForDriver ? <Badge tone="zone">{copy.isNew}</Badge> : null}
          {windowEnded && !window.closed ? (
            <Badge tone="warn">{copy.ended}</Badge>
          ) : null}
        </p>
      ) : null}
      {drop.address ? (
        <p className="tour-dock-address">
          {drop.address.streetLine1}
          {drop.address.city !== town ? (
            <span>
              , {drop.address.postalCode} {drop.address.city}
            </span>
          ) : (
            <span className="sr-only">
              , {drop.address.postalCode} {drop.address.city}
            </span>
          )}
        </p>
      ) : (
        <p className="tour-dock-muted">{copy.noAddress}</p>
      )}
      <DriverNote drop={drop} full key={drop.commitmentId} />
      {address && map ? (
        <TourMapSlot
          address={address}
          lat={stop.lat}
          lon={stop.lon}
          onOpen={map.onOpen}
          position={position}
          tiles={map.tiles}
        />
      ) : null}
      {canMark ? (
        <>
          <div className="tour-dock-actions">
            {navigation ? (
              <a
                className={cn(
                  buttonClassName({ size: "lg", variant: "secondary" }),
                  "tour-nav",
                )}
                href={navigation}
                {...(external ? { rel: "noopener", target: "_blank" } : {})}
              >
                <Icon icon={Navigation} size={18} />
                <span className="btn-label">Navigation</span>
              </a>
            ) : null}
            {tel ? (
              <a
                aria-label={`${contactName} anrufen`}
                className={cn(
                  buttonClassName({ size: "lg", variant: "secondary" }),
                  "btn-icon tour-call",
                )}
                href={tel}
                title={`${contactName} anrufen`}
              >
                <Icon icon={Phone} size={20} />
              </a>
            ) : null}
            <Button
              aria-label={`${copy.missedShort} (${copy.missed.toLowerCase()})`}
              className="tour-missed"
              disabled={busy}
              icon={X}
              onClick={() => onMark("missed")}
              size="lg"
              title={copy.missed}
              variant="secondary"
            >
              {copy.missedShort}
            </Button>
          </div>
          {deliver}
        </>
      ) : (
        <p className="tour-dock-muted tour-dock-reason">
          {deliverable(drop) ? copy.closedWindow : copy.cancelledOrder}
        </p>
      )}
    </div>
  );
}

/**
 * The map view's sheet for a done, missed or cancelled stop: what the
 * list's done panel shows (address, quantity, time) and "Rückgängig".
 */
function DoneSheet({
  busy,
  onClose,
  onUndo,
  position,
  stop,
  zone,
}: {
  readonly busy: boolean;
  readonly onClose: () => void;
  readonly onUndo: () => void;
  readonly position: number;
  readonly stop: TourStop;
  readonly zone: string;
}) {
  const dock = useRef<HTMLElement | null>(null);
  useDockHeight(dock);
  const { drop, window } = stop;
  const name = stopName(drop);
  const undoable = deliverable(drop) && !window.closed;
  return (
    <section
      aria-label={copy.stop(position)}
      className="tour-dock"
      data-testid="tour-done-sheet"
      ref={dock}
    >
      <Button
        aria-label={copy.closeSheet}
        className="tour-dock-close"
        icon={X}
        onClick={onClose}
        size="lg"
        title={copy.closeSheet}
        variant="ghost"
      />
      <div className="tour-dock-body">
        <div className="tour-dock-head">
          <span className="tour-pos num">{position}</span>
          <div className="tour-dock-title">
            <h2>{name}</h2>
          </div>
          <StatusIcon
            label={stateLabel(drop)}
            size={20}
            status={stateShape(drop)}
          />
        </div>
        <p className="tour-dock-address">
          {dropAddress(drop) ?? copy.noAddress}
        </p>
        <p className="tour-dock-muted num">
          {dropQuantities(drop)} · {stateLabel(drop)}
          {drop.stateChangedAt
            ? ` um ${clockMinutes(drop.stateChangedAt, zone)} Uhr`
            : ""}
        </p>
        {undoable ? (
          <Button
            className="tour-done-undo"
            disabled={busy}
            icon={Undo2}
            onClick={onUndo}
            size="lg"
            variant="secondary"
          >
            Rückgängig
          </Button>
        ) : null}
      </div>
    </section>
  );
}
