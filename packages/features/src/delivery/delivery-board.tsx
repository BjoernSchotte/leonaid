import {
  CheckCheck,
  MailPlus,
  MapPin,
  PackageCheck,
  Phone,
  RotateCcw,
  Truck,
  Undo2,
  UserRound,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  ApiError,
  type DeliveryBoardResponse,
  type DeliveryBoardWindowResponse,
  type DeliveryDropResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  Button,
  buttonClassName,
  EmptyState,
  ErrorState,
  Icon,
  Kbd,
  Meter,
  Modal,
  NextStep,
  OptionMenu,
  Popover,
  SkeletonRows,
  StatusIcon,
  StatusMessage,
  cn,
  useHotkeys,
  useMediaQuery,
  useOptionalHotkeyRegistry,
  useOptionalToast,
} from "@leonaid/ui";

import { replaceActionInUrl } from "../action-admin/action-location";
import { actionErrorMessage } from "../action-admin/errors";
import { useContextCommands } from "../command-palette/store";
import { formatDateTime } from "../shared/dates";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";
import {
  FEATURE_FLAGS,
  useLeonAidSettledFlag,
} from "../feature-flags/openfeature-provider";
import {
  BOARD_POLL_MS,
  dayMonth,
  deliveryTimeRange,
  dropAddress,
  longDay,
  weekday,
} from "./delivery-shared";
import {
  DeliveryViewSwitch,
  TourPlanner,
  type DeliveryView,
} from "./tour-planner";

export { BOARD_POLL_MS, deliveryTimeRange, dropAddress };

/*
 * The delivery day board (prototype pages/Delivery.tsx). Managers see every
 * drop of the day, assign drivers and close windows; drivers (PWA) see and
 * tick only the drops assigned to them. Admin copy uses "Sie", the PWA "Du".
 */

export type DeliverySurface = "web" | "pwa";

const NO_DRIVER = "none";
const ALL_DRIVERS = "all";

/** "Mi 11.11. · 07–09 Uhr" (prototype window label). */
export function deliveryWindowLabel(
  window: Pick<DeliveryBoardWindowResponse, "startsAt" | "endsAt">,
  zone: string,
) {
  return `${weekday(window.startsAt, zone)} ${dayMonth(window.startsAt, zone)} · ${deliveryTimeRange(window, zone)} Uhr`;
}

/** The board with one drop replaced by its newer state. */
export function withDrop(
  board: DeliveryBoardResponse,
  drop: DeliveryDropResponse,
): DeliveryBoardResponse {
  return {
    ...board,
    windows: board.windows.map((window) => ({
      ...window,
      drops: window.drops.map((item) =>
        item.commitmentId === drop.commitmentId &&
        item.revision <= drop.revision
          ? drop
          : item,
      ),
    })),
  };
}

/** Cancelled orders stay struck through but take no commands. */
const deliverable = (drop: DeliveryDropResponse) =>
  drop.orderStatus !== "cancelled";

/**
 * Whether the check is frozen. Open window: never. Closed window: drivers
 * always; managers may still tick open or missed drops (a later delivery)
 * and take back a later delivery of a drop missed at closure.
 */
function locked(drop: DeliveryDropResponse, closed: boolean, manager: boolean) {
  if (!closed) return false;
  if (!manager) return true;
  return drop.state === "delivered" && !drop.missedAtClosure;
}

const boxes = (count: number) => `${count} ${count === 1 ? "Box" : "Boxen"}`;

const copy = {
  web: {
    intro:
      "Pro Fenster abhaken, was angekommen ist. Alles bleibt bis zum Abschluss änderbar.",
    pickFirst: "Erst eine Lieferung mit J/K auswählen.",
    noDrops: "Für dieses Fenster ist nichts gebucht.",
    noDropsForDriver: "Für diesen Fahrer ist hier nichts eingeplant.",
    nothingAssigned: "Noch keine Lieferungen",
    notEnabled: "Für diese Aktion ist keine Lieferplanung aktiv.",
    error: "Die Auslieferung konnte nicht geladen werden.",
    stale: "Die Auslieferung konnte nicht aktualisiert werden.",
    codes: {
      delivery_window_closed:
        "Dieses Lieferfenster ist abgeschlossen. Zum Zurücknehmen öffnen Sie es wieder.",
      delivery_state_conflict:
        "Diese Lieferung wurde inzwischen geändert. Die Tafel zeigt jetzt den aktuellen Stand.",
      delivery_not_assigned: "Diese Lieferung ist Ihnen nicht zugewiesen.",
      delivery_order_not_deliverable:
        "Diese Bestellung wird nicht (mehr) ausgeliefert.",
      delivery_management_required: "Das darf nur, wer die Aktion verwaltet.",
    },
  },
  pwa: {
    intro: "Hake ab, was angekommen ist. Du siehst nur deine Lieferungen.",
    pickFirst: "Wähle erst eine Lieferung aus.",
    noDrops: "In diesem Fenster ist dir nichts zugewiesen.",
    noDropsForDriver: "In diesem Fenster ist dir nichts zugewiesen.",
    nothingAssigned: "Dir ist noch keine Lieferung zugewiesen",
    notEnabled: "Für diese Aktion ist keine Lieferplanung aktiv.",
    error: "Deine Lieferungen konnten nicht geladen werden.",
    stale: "Deine Lieferungen konnten nicht aktualisiert werden.",
    codes: {
      delivery_window_closed:
        "Dieses Lieferfenster ist abgeschlossen. Wende dich an die Aktionsleitung.",
      delivery_state_conflict:
        "Diese Lieferung wurde inzwischen geändert. Du siehst jetzt den aktuellen Stand.",
      delivery_not_assigned: "Diese Lieferung ist dir nicht zugewiesen.",
      delivery_order_not_deliverable:
        "Diese Bestellung wird nicht (mehr) ausgeliefert.",
      delivery_management_required: "Das darf nur, wer die Aktion verwaltet.",
    },
  },
} as const;

type BoardErrorCode = keyof (typeof copy)["web"]["codes"];

export interface DeliveryBoardPageProps {
  readonly client: LeonAidApiClient;
  readonly actionId: string;
  readonly surface: DeliverySurface;
  /**
   * PWA: the device is offline. The board then shows no drops and drops
   * its cached copy (addresses and phones stay off a lost phone).
   */
  readonly offline?: boolean;
  /** PWA: the actions this driver drives for; a switch shows for several. */
  readonly actions?: readonly {
    readonly actionId: string;
    readonly actionName: string;
  }[];
}

/**
 * The delivery page. On the web with the flag `delivery.tours` it offers
 * "Liste" and "Touren" (spec krapfentaxi-touren §6), kept in `?view=` as
 * the day is in `?day=`. Until the flag is known a `?view=tours` link shows
 * a skeleton, so neither view loads for nothing or flashes.
 */
export function DeliveryBoardPage(props: DeliveryBoardPageProps) {
  return props.surface === "web" ? (
    <WebDeliveryPage {...props} />
  ) : (
    <DeliveryListPage {...props} />
  );
}

const urlView = (): DeliveryView =>
  new URLSearchParams(window.location.search).get("view") === "tours"
    ? "tours"
    : "list";
const urlDay = () => new URLSearchParams(window.location.search).get("day");

function WebDeliveryPage(props: DeliveryBoardPageProps) {
  const tours = useLeonAidSettledFlag(FEATURE_FLAGS.deliveryTours);
  const [view, setViewState] = useState<DeliveryView>(urlView);
  // Read again on each switch: the list keeps its own day in the URL.
  const [day, setDayState] = useState<string | null>(urlDay);
  const setView = (next: DeliveryView) => {
    const url = new URL(window.location.href);
    if (next === "tours") url.searchParams.set("view", "tours");
    else url.searchParams.delete("view");
    window.history.replaceState(window.history.state, "", url);
    setDayState(urlDay());
    setViewState(next);
  };
  const setDay = (value: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("day", value);
    window.history.replaceState(window.history.state, "", url);
    setDayState(value);
  };
  if (view === "tours" && tours === null) {
    return (
      <div className="delivery" data-zone="delivery">
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (view === "tours" && tours) {
    // A campaign switch remounts the planner; as on a day switch, its
    // waiting moves go out first, without asking (useOrderAutosave).
    return (
      <TourPlanner
        actionId={props.actionId}
        client={props.client}
        day={day}
        key={props.actionId}
        onDayChange={setDay}
        onShowList={() => setView("list")}
      />
    );
  }
  return (
    <DeliveryListPage
      {...props}
      viewSwitch={
        tours ? (
          <DeliveryViewSwitch onChange={setView} view="list" />
        ) : undefined
      }
    />
  );
}

function DeliveryListPage({
  actionId,
  actions = [],
  client,
  offline = false,
  surface,
  viewSwitch,
}: DeliveryBoardPageProps & { readonly viewSwitch?: ReactNode }) {
  const text = copy[surface];
  const hideOffline = surface === "pwa" && offline;
  const queries = useQueryClient();
  const toast = useOptionalToast();
  // The chosen day lives in the URL (?day=), so a reload keeps it.
  const [day, setDayState] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("day"),
  );
  const setDay = (value: string) => {
    setDayState(value);
    const url = new URL(window.location.href);
    url.searchParams.set("day", value);
    window.history.replaceState(window.history.state, "", url);
  };
  const [driver, setDriver] = useState(ALL_DRIVERS);
  const [activeWindow, setActiveWindow] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<{
    readonly ids: readonly string[];
    readonly current: string | null;
  } | null>(null);
  const anchorRef = useRef<HTMLElement | null>(null);
  const openAssign = (
    ids: readonly string[],
    current: string | null,
    anchor: HTMLElement,
  ) => {
    anchorRef.current = anchor;
    setAssigning({ ids, current });
  };
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());
  const isMobile = useMediaQuery("(max-width: 720px)");

  const queryKey = ["delivery-board", actionId, day] as const;
  const board = useQuery({
    enabled: Boolean(actionId) && !hideOffline,
    // PWA: nothing stays in memory once the board is left.
    gcTime: surface === "pwa" ? 0 : undefined,
    queryFn: () => client.getDeliveryBoard(actionId, { day }),
    queryKey,
    // Managers follow the drivers' ticks: poll and refetch on focus. The
    // PWA (drivers, addresses and phones) keeps no background refetches.
    refetchInterval: surface === "web" ? BOARD_POLL_MS : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: surface === "web",
    retry: false,
  });
  useEffect(() => {
    if (!hideOffline) return;
    queries.removeQueries({ queryKey: ["delivery-board"] });
    // Finished commands keep the returned drop (address, phone) as data.
    const mutations = queries.getMutationCache();
    for (const mutation of mutations.findAll({
      mutationKey: ["delivery-board"],
    })) {
      mutations.remove(mutation);
    }
  }, [hideOffline, queries]);
  // PWA: finished commands are dropped at once, like the board query.
  const mutationOptions = {
    gcTime: surface === "pwa" ? 0 : undefined,
    mutationKey: ["delivery-board", actionId],
  };
  const refresh = () =>
    queries.invalidateQueries({ queryKey: ["delivery-board", actionId] });
  /** Shared error handling (fresh login, support code), board copy per code. */
  const errorText = (error: unknown) => {
    const shared = actionErrorMessage(error, {
      address: surface === "pwa" ? "du" : "Sie",
    });
    const code = shared.code as BoardErrorCode | null;
    return code && code in text.codes ? text.codes[code] : shared.message;
  };
  const showError = (error: unknown) =>
    toast?.show({ title: errorText(error), tone: "error" });

  const data = board.data;
  const zone = data?.timezone ?? "Europe/Berlin";
  const manager = data?.manager ?? surface === "web";

  const windows = useMemo(() => {
    if (!data) return [];
    return data.windows.map((window) => ({
      window,
      label: deliveryWindowLabel(window, zone),
      rows: window.drops.filter(
        (drop) =>
          driver === ALL_DRIVERS ||
          (driver === NO_DRIVER
            ? drop.driverUserId === null
            : drop.driverUserId === driver),
      ),
    }));
  }, [data, driver, zone]);

  const selectedWindow =
    windows.find((group) => group.window.id === activeWindow) ?? windows[0];
  const visible = isMobile && selectedWindow ? [selectedWindow] : windows;
  const flat = visible
    .filter((group) => !group.window.closure || manager)
    .flatMap((group) => group.rows);

  const focus = (id: string | undefined) => {
    if (!id) return;
    setFocusedId(id);
    rowRefs.current.get(id)?.focus();
  };
  const move = (delta: number) => {
    const index = flat.findIndex((drop) => drop.commitmentId === focusedId);
    focus(
      flat[
        Math.max(0, Math.min(flat.length - 1, index === -1 ? 0 : index + delta))
      ]?.commitmentId,
    );
  };

  // Set at once, before the mutation reports "pending" in a later render:
  // a second key press in the same moment must not send a second command.
  const ticking = useRef(false);
  const tick = (
    variables: { drop: DeliveryDropResponse; delivered: boolean },
    options?: { onSuccess?: (updated: DeliveryDropResponse) => void },
  ) => {
    if (ticking.current) return;
    ticking.current = true;
    setState.mutate(variables, options);
  };
  const setState = useMutation({
    ...mutationOptions,
    mutationFn: ({
      drop,
      delivered,
    }: {
      drop: DeliveryDropResponse;
      delivered: boolean;
    }) =>
      client.setDeliveryState(actionId, drop.commitmentId, {
        delivered,
        expectedRevision: drop.revision,
      }),
    onMutate: () => {
      ticking.current = true;
    },
    // Show the returned drop at once; the refetch then confirms the board.
    onSuccess: (updated) =>
      queries.setQueryData<DeliveryBoardResponse>(queryKey, (current) =>
        current ? withDrop(current, updated) : current,
      ),
    onSettled: () => {
      ticking.current = false;
      void refresh();
    },
    onError: showError,
  });

  const latest = useRef<DeliveryBoardResponse | undefined>(undefined);
  latest.current = board.data;
  /** The newer of a drop as returned and as currently on the board. */
  const freshest = (drop: DeliveryDropResponse) => {
    const onBoard = latest.current?.windows
      .flatMap((window) => window.drops)
      .find((item) => item.commitmentId === drop.commitmentId);
    return onBoard && onBoard.revision > drop.revision ? onBoard : drop;
  };

  const toggle = (drop: DeliveryDropResponse, closed: boolean) => {
    const delivered = drop.state !== "delivered";
    // The same guards as the check button, also for the "d" key: one
    // command at a time (so its toast and undo stay, see `tick`), none for
    // cancelled or frozen drops.
    if (!deliverable(drop) || locked(drop, closed, manager)) return;
    tick(
      { drop, delivered },
      {
        onSuccess: (updated) =>
          toast?.show({
            title: delivered
              ? `${drop.buyerName}: geliefert.`
              : closed
                ? `${drop.buyerName}: wieder unter „Nachliefern“.`
                : `${drop.buyerName}: wieder offen.`,
            tone: delivered ? "success" : "info",
            // In a closed window only a later delivery of a missed drop
            // can be taken back; anything else needs the window reopened.
            action:
              closed && !updated.missedAtClosure
                ? undefined
                : {
                    label: "Rückgängig",
                    // The freshest revision: the board may have reloaded.
                    run: () =>
                      tick({
                        drop: freshest(updated),
                        delivered: !delivered,
                      }),
                  },
          }),
      },
    );
  };

  const closeWindow = useMutation({
    ...mutationOptions,
    mutationFn: (windowId: string) =>
      client.closeDeliveryWindow(actionId, windowId),
    onSuccess: (result) => {
      setClosing(null);
      toast?.show({
        title: result.missedCount
          ? result.followUp === "tasks"
            ? `Fenster abgeschlossen. ${result.missedCount} nicht zugestellte Lieferungen als Aufgabe angelegt.`
            : `Fenster abgeschlossen. ${result.missedCount} nicht zugestellte Lieferungen bleiben mit dem Hinweis „Nachliefern“ auf dieser Tafel.`
          : "Fenster abgeschlossen. Alles geliefert.",
        tone: "success",
      });
    },
    onError: showError,
    onSettled: () => void refresh(),
  });

  const reopenWindow = useMutation({
    ...mutationOptions,
    mutationFn: (windowId: string) =>
      client.reopenDeliveryWindow(actionId, windowId),
    onSuccess: () =>
      toast?.show({ title: "Fenster wieder geöffnet.", tone: "info" }),
    onError: showError,
    onSettled: () => void refresh(),
  });

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
    onSuccess: (_result, variables) => {
      setAssigning(null);
      toast?.show({
        title: variables.driverUserId
          ? "Fahrer zugewiesen."
          : "Fahrer entfernt.",
        tone: "success",
      });
    },
    onError: showError,
    onSettled: () => void refresh(),
  });

  useContextCommands(
    manager
      ? windows
          .filter(
            (group) =>
              !group.window.closure && group.window.drops.some(deliverable),
          )
          .map((group) => ({
            id: `delivery:close:${group.window.id}`,
            label: `Fenster abschließen: ${group.label}`,
            group: "Auslieferung",
            icon: CheckCheck,
            run: () => setClosing(group.window.id),
          }))
      : [],
  );

  const closingGroup = windows.find((group) => group.window.id === closing);
  const openInClosing =
    closingGroup?.window.drops.filter(
      (drop) => drop.state === "open" && deliverable(drop),
    ) ?? [];

  const unassigned = manager
    ? windows.flatMap((group) =>
        group.window.closure
          ? []
          : group.window.drops.filter(
              (drop) =>
                drop.driverUserId === null &&
                drop.state === "open" &&
                deliverable(drop),
            ),
      )
    : [];
  // Booked after the window was closed and not yet delivered: no task
  // exists for them, so the board reminds the manager.
  const lateBookings = manager
    ? windows.flatMap((group) =>
        group.window.closure
          ? group.window.drops
              .filter((drop) => drop.state === "open" && deliverable(drop))
              .map((drop) => ({ drop, windowId: group.window.id }))
          : [],
      )
    : [];
  const showLate = () => {
    const first = lateBookings[0];
    if (!first) return;
    setDriver(ALL_DRIVERS);
    setActiveWindow(first.windowId);
    // The row renders after the filter and window change.
    window.requestAnimationFrame(() => focus(first.drop.commitmentId));
  };

  // A past, still open window with nothing left to tick: only closing it
  // remains (design §7).
  const now = Date.now();
  const readyToClose = manager
    ? windows.find(
        (group) =>
          !group.window.closure &&
          new Date(group.window.endsAt).getTime() < now &&
          group.window.drops.some(deliverable) &&
          group.window.drops.every(
            (drop) => !deliverable(drop) || drop.state === "delivered",
          ),
      )
    : undefined;

  const driverOptions = [
    ...(data?.drivers ?? []).map((item) => ({
      value: item.userId,
      label: item.displayName,
      icon: <Avatar name={item.displayName} size="xs" />,
    })),
    { value: NO_DRIVER, label: "Kein Fahrer" },
  ];

  if (hideOffline) {
    return (
      <div className="delivery">
        <header className="page-header">
          <div className="page-heading">
            <h1>Auslieferung</h1>
          </div>
        </header>
        <EmptyState
          headingLevel={2}
          icon={Truck}
          title="Keine Verbindung"
          description="Ohne Verbindung zeigen wir keine Lieferungen. Sobald du wieder online bist, lädt die Tafel neu."
        />
      </div>
    );
  }

  if (!actionId) {
    return (
      <div className="delivery">
        <EmptyState
          headingLevel={2}
          icon={Truck}
          title="Keine Aktion gewählt"
          description={
            surface === "web"
              ? "Wählen Sie eine Charity-Aktion, um die Auslieferung zu sehen."
              : "Dir ist noch keine Aktion als Ausfahrer zugeordnet."
          }
        />
      </div>
    );
  }

  const notEnabled =
    board.error instanceof ApiError &&
    board.error.detail.code === "delivery_not_enabled";

  return (
    <div className="delivery" data-zone="delivery">
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1>Auslieferung</h1>
            {data?.day ? (
              <span className="page-count">{longDay(data.day)}</span>
            ) : null}
          </div>
          <p className="page-sub">{text.intro}</p>
        </div>
        {data &&
        (data.days.length > 1 ||
          manager ||
          actions.length > 1 ||
          viewSwitch) ? (
          <div className="delivery-filters">
            {actions.length > 1 ? (
              <label className="driver-filter">
                <span>Aktion</span>
                <select
                  className="input select"
                  data-testid="delivery-action"
                  onChange={(event) => {
                    const url = new URL(window.location.href);
                    url.searchParams.delete("day");
                    window.history.replaceState(window.history.state, "", url);
                    setDayState(null);
                    setActiveWindow(null);
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
                  data-testid="delivery-day"
                  onChange={(event) => {
                    setDay(event.target.value);
                    setActiveWindow(null);
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
            {manager ? (
              <label className="driver-filter">
                <span>Fahrdienst</span>
                <select
                  className="input select"
                  data-testid="delivery-driver-filter"
                  onChange={(event) => setDriver(event.target.value)}
                  value={driver}
                >
                  <option value={ALL_DRIVERS}>Alle Fahrer</option>
                  {data.drivers.map((item) => (
                    <option key={item.userId} value={item.userId}>
                      {item.displayName}
                    </option>
                  ))}
                  <option value={NO_DRIVER}>Ohne Fahrer</option>
                </select>
              </label>
            ) : null}
            {viewSwitch}
          </div>
        ) : viewSwitch ? (
          <div className="delivery-filters">{viewSwitch}</div>
        ) : null}
      </header>

      {board.isPending ? (
        <SkeletonRows rows={6} />
      ) : notEnabled ? (
        <EmptyState
          headingLevel={2}
          icon={Truck}
          title="Keine Lieferplanung"
          description={text.notEnabled}
        />
      ) : board.isError && !board.data ? (
        <ErrorState onRetry={() => void board.refetch()} title={text.error}>
          {surface === "web"
            ? "Prüfen Sie die Verbindung und versuchen Sie es erneut."
            : "Prüfe deine Verbindung und versuche es erneut."}
        </ErrorState>
      ) : !windows.length ? (
        <EmptyState
          headingLevel={2}
          icon={Truck}
          title={text.nothingAssigned}
          description={
            manager
              ? "Legen Sie Lieferfenster in der Aktion an. Gebuchte Bestellungen erscheinen dann hier."
              : "Sobald dir jemand Lieferungen zuweist, erscheinen sie hier."
          }
        />
      ) : (
        <>
          {board.isError ? (
            // A failed poll keeps the last board; say how old it is.
            <StatusMessage className="delivery-stale" tone="warning">
              <strong>{text.stale}</strong>
              <p>
                Angezeigt wird der Stand von{" "}
                {formatDateTime(new Date(board.dataUpdatedAt).toISOString())}.
              </p>
              <Button
                loading={board.isFetching}
                onClick={() => void board.refetch()}
                size="sm"
                variant="secondary"
              >
                Jetzt neu laden
              </Button>
            </StatusMessage>
          ) : null}
          {lateBookings.length ? (
            <NextStep
              action={
                <Button
                  data-testid="delivery-next-late"
                  icon={PackageCheck}
                  onClick={showLate}
                  variant="primary"
                >
                  Zur Lieferung
                </Button>
              }
              consequence={`${lateBookings.length} ${lateBookings.length === 1 ? "Lieferung wurde" : "Lieferungen wurden"} nach dem Abschluss ins Fenster gebucht und ${lateBookings.length === 1 ? "ist" : "sind"} noch nicht abgehakt. Haken Sie sie nach der Lieferung ab, oder öffnen Sie das Fenster wieder, damit sie beim erneuten Abschluss als „Nachliefern“ zählen.`}
            />
          ) : null}
          {manager && unassigned.length && !data?.drivers.length ? (
            <NextStep
              action={
                <a
                  className={buttonClassName({ variant: "primary" })}
                  data-testid="delivery-next-invite"
                  href={`${ADMIN_BASE}members/invitations?action=${encodeURIComponent(actionId)}`}
                >
                  <Icon icon={MailPlus} size={16} />
                  <span>Ausfahrer einladen</span>
                </a>
              }
              consequence={`${unassigned.length} ${unassigned.length === 1 ? "Lieferung hat" : "Lieferungen haben"} noch keinen Fahrer, und die Aktion hat noch keine Ausfahrer. Laden Sie jemanden mit der Rolle „Ausfahrer“ ein.`}
            />
          ) : manager && readyToClose && !unassigned.length ? (
            <NextStep
              action={
                <Button
                  data-testid="delivery-next-close"
                  icon={CheckCheck}
                  onClick={() => setClosing(readyToClose.window.id)}
                  variant="primary"
                >
                  Fenster abschließen
                </Button>
              }
              consequence={`${readyToClose.label}: alles geliefert. Schließen Sie das Fenster ab, damit es als erledigt gilt.`}
            />
          ) : null}
          {manager && unassigned.length && data?.drivers.length ? (
            <NextStep
              action={
                <Button
                  data-testid="delivery-next-assign"
                  icon={UserRound}
                  onClick={(event) =>
                    openAssign(
                      unassigned.map((drop) => drop.commitmentId),
                      null,
                      event.currentTarget,
                    )
                  }
                  variant="primary"
                >
                  Fahrer zuweisen
                </Button>
              }
              consequence={`${unassigned.length} ${unassigned.length === 1 ? "Lieferung hat" : "Lieferungen haben"} noch keinen Fahrer. Ausfahrer sehen nur, was ihnen zugewiesen ist.`}
            />
          ) : null}

          <div
            aria-label="Lieferfenster wählen"
            className="segmented"
            role="radiogroup"
          >
            {windows.map(({ window }) => (
              <button
                aria-checked={selectedWindow?.window.id === window.id}
                className={cn(
                  "segment",
                  selectedWindow?.window.id === window.id && "is-active",
                )}
                key={window.id}
                onClick={() => setActiveWindow(window.id)}
                role="radio"
                type="button"
              >
                {deliveryTimeRange(window, zone)}
                <span className="segment-day">
                  {weekday(window.startsAt, zone)}{" "}
                  {dayMonth(window.startsAt, zone)}
                </span>
              </button>
            ))}
          </div>

          <div className="windows-board">
            {visible.map(({ window, label, rows }) => {
              // Cancelled orders stay listed but do not count.
              const active = rows.filter(deliverable);
              const delivered = active.filter(
                (drop) => drop.state === "delivered",
              ).length;
              const boxCount = active.reduce(
                (sum, drop) => sum + drop.totalBoxes,
                0,
              );
              const drivers = [
                ...new Set(
                  rows.flatMap((drop) =>
                    drop.driverName ? [drop.driverName] : [],
                  ),
                ),
              ];
              const closed = window.closure !== null;
              return (
                <section
                  aria-labelledby={`win-${window.id}`}
                  className={cn("window-section", closed && "is-closed")}
                  data-testid="delivery-window"
                  key={window.id}
                >
                  <header className="window-head">
                    <div className="window-title">
                      <h2 id={`win-${window.id}`}>
                        {label}
                        {manager && window.fullyBooked && !closed ? (
                          <>
                            {" "}
                            <Badge tone="warn">Ausgebucht</Badge>
                          </>
                        ) : null}
                      </h2>
                      <span className="small muted num">
                        {delivered} von {active.length} geliefert ·{" "}
                        {boxes(boxCount)}
                        {drivers.length ? ` · ${drivers.join(", ")}` : ""}
                      </span>
                    </div>
                    <div className="window-progress">
                      <Meter
                        label={`${label}: ${delivered} von ${active.length} geliefert`}
                        max={Math.max(1, active.length)}
                        tone={
                          delivered === active.length && active.length > 0
                            ? "ok"
                            : "zone"
                        }
                        value={delivered}
                      />
                    </div>
                    {closed ? (
                      <div className="window-closed">
                        <span className="stamp tone-ok">Abgeschlossen</span>
                        {manager ? (
                          <Button
                            disabled={reopenWindow.isPending}
                            icon={RotateCcw}
                            loading={reopenWindow.isPending}
                            onClick={() => reopenWindow.mutate(window.id)}
                            size="sm"
                            variant="ghost"
                          >
                            Wieder öffnen
                          </Button>
                        ) : null}
                      </div>
                    ) : manager ? (
                      <div className="window-actions">
                        {data?.drivers.length &&
                        window.drops.some(deliverable) ? (
                          <Button
                            icon={UserRound}
                            onClick={(event) =>
                              openAssign(
                                window.drops
                                  .filter(deliverable)
                                  .map((drop) => drop.commitmentId),
                                null,
                                event.currentTarget,
                              )
                            }
                            size="sm"
                            variant="ghost"
                          >
                            Fahrer für alle
                          </Button>
                        ) : null}
                        <Button
                          data-testid="delivery-close-window"
                          disabled={!window.drops.some(deliverable)}
                          icon={CheckCheck}
                          onClick={() => setClosing(window.id)}
                          size="sm"
                          variant="secondary"
                        >
                          Fenster abschließen
                        </Button>
                      </div>
                    ) : null}
                  </header>
                  {rows.length === 0 ? (
                    <EmptyState
                      icon={Truck}
                      title="Keine Lieferungen in diesem Fenster"
                      description={
                        driver === ALL_DRIVERS
                          ? text.noDrops
                          : text.noDropsForDriver
                      }
                    />
                  ) : (
                    <ul className="drops">
                      {rows.map((drop) => {
                        const done = drop.state === "delivered";
                        const missed = drop.state === "missed";
                        const cancelled = !deliverable(drop);
                        const frozen = locked(drop, closed, manager);
                        const disabled = frozen || cancelled;
                        const address = dropAddress(drop);
                        return (
                          <li
                            className={cn(
                              "drop",
                              done && "is-done",
                              missed && "is-missed",
                              cancelled && "is-cancelled",
                              focusedId === drop.commitmentId && "is-focused",
                            )}
                            data-commitment-id={drop.commitmentId}
                            data-testid="delivery-drop"
                            key={drop.commitmentId}
                          >
                            <button
                              aria-label={`${drop.buyerName}, ${boxes(drop.totalBoxes)}: ${
                                done
                                  ? frozen
                                    ? "geliefert, Fenster abgeschlossen"
                                    : "geliefert, zurücknehmen"
                                  : missed
                                    ? "nicht geliefert, jetzt als geliefert markieren"
                                    : "als geliefert markieren"
                              }`}
                              aria-pressed={done}
                              className="drop-check"
                              disabled={disabled || setState.isPending}
                              onClick={() => toggle(drop, closed)}
                              onFocus={() => setFocusedId(drop.commitmentId)}
                              ref={(element) => {
                                if (element)
                                  rowRefs.current.set(
                                    drop.commitmentId,
                                    element,
                                  );
                                else rowRefs.current.delete(drop.commitmentId);
                              }}
                              type="button"
                            >
                              <StatusIcon
                                label={
                                  done
                                    ? "Geliefert"
                                    : missed
                                      ? "Nachliefern"
                                      : "Offen"
                                }
                                size={20}
                                status={
                                  done ? "done" : missed ? "alert" : "open"
                                }
                              />
                            </button>
                            <div className="drop-main">
                              <p className="drop-name">
                                <span
                                  className={
                                    cancelled ? "is-struck" : undefined
                                  }
                                >
                                  {drop.buyerName}
                                </span>{" "}
                                <span className="num drop-boxes">
                                  {boxes(drop.totalBoxes)}
                                </span>
                                {missed ? (
                                  <span className="drop-flag">Nachliefern</span>
                                ) : null}
                                {closed &&
                                drop.state === "open" &&
                                !cancelled ? (
                                  <span className="drop-flag">
                                    nach Abschluss gebucht
                                  </span>
                                ) : null}
                                {cancelled ? (
                                  <span className="drop-flag">storniert</span>
                                ) : null}
                              </p>
                              {address ? (
                                <p className="drop-meta">
                                  <Icon icon={MapPin} size={12} />{" "}
                                  {drop.address?.recipientName &&
                                  drop.address.recipientName !== drop.buyerName
                                    ? `${drop.address.recipientName}, `
                                    : ""}
                                  {address}
                                </p>
                              ) : null}
                              {drop.contact?.name || drop.contact?.phone ? (
                                <p className="drop-meta">
                                  <Icon icon={Phone} size={12} />{" "}
                                  {drop.contact.name}
                                  {drop.contact.phone ? (
                                    <>
                                      {drop.contact.name ? " · " : ""}
                                      <a href={`tel:${drop.contact.phone}`}>
                                        {drop.contact.phone}
                                      </a>
                                    </>
                                  ) : null}
                                </p>
                              ) : null}
                            </div>
                            {manager ? (
                              <button
                                aria-label={
                                  drop.driverName
                                    ? `Fahrer: ${drop.driverName}, ändern`
                                    : "Fahrer zuweisen"
                                }
                                className="drop-driver"
                                disabled={closed}
                                onClick={(event) =>
                                  openAssign(
                                    [drop.commitmentId],
                                    drop.driverUserId,
                                    event.currentTarget,
                                  )
                                }
                                type="button"
                              >
                                {drop.driverName ? (
                                  <Avatar name={drop.driverName} size="sm" />
                                ) : (
                                  <span className="drop-driver-empty">
                                    <Icon icon={UserRound} size={14} />
                                  </span>
                                )}
                              </button>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
          {surface === "web" ? (
            <p aria-hidden="true" className="list-hint">
              <Kbd announce={false} keys="j" />{" "}
              <Kbd announce={false} keys="k" /> bewegen ·{" "}
              <Kbd announce={false} keys="d" /> geliefert ·{" "}
              <Kbd announce={false} keys="?" /> alle Kürzel
            </p>
          ) : null}
        </>
      )}

      <BoardHotkeys
        move={move}
        onDeliver={() => {
          const drop = flat.find((item) => item.commitmentId === focusedId);
          if (!drop) {
            toast?.show({ title: text.pickFirst, tone: "info" });
            return;
          }
          const group = windows.find((item) =>
            item.window.drops.includes(drop),
          );
          toggle(drop, group?.window.closure !== null);
        }}
      />

      <Popover
        anchor={anchorRef}
        label="Fahrer wählen"
        onClose={() => setAssigning(null)}
        open={assigning !== null}
      >
        <OptionMenu<string>
          onSelect={(value) => {
            if (!assigning) return;
            assign.mutate({
              ids: assigning.ids,
              driverUserId: value === NO_DRIVER ? null : value,
            });
          }}
          options={driverOptions}
          placeholder="Fahrer suchen"
          value={assigning?.current ?? NO_DRIVER}
        />
      </Popover>

      <Modal
        description="Danach lassen sich Lieferungen dieses Fensters nur noch nachliefern. Zum Zurücknehmen öffnen Sie das Fenster wieder."
        footer={
          <>
            <Button onClick={() => setClosing(null)} variant="ghost">
              Abbrechen
            </Button>
            <Button
              data-testid="delivery-close-confirm"
              icon={PackageCheck}
              loading={closeWindow.isPending}
              onClick={() => closing && closeWindow.mutate(closing)}
              variant="primary"
            >
              {openInClosing.length
                ? `Mit ${openInClosing.length} offenen abschließen`
                : "Abschließen"}
            </Button>
          </>
        }
        onClose={() => setClosing(null)}
        open={Boolean(closingGroup)}
        title={`${closingGroup?.label ?? ""} abschließen?`}
      >
        {openInClosing.length ? (
          <div className="stack">
            <p className="small">
              <strong>
                {openInClosing.length}{" "}
                {openInClosing.length === 1
                  ? "Lieferung ist"
                  : "Lieferungen sind"}{" "}
                noch nicht abgehakt.
              </strong>{" "}
              {data?.followUpTasks
                ? "Sie werden als Aufgabe „Nachliefern“ für Sie angelegt, damit nichts verloren geht."
                : "Sie bleiben mit dem Hinweis „Nachliefern“ auf dieser Tafel."}
            </p>
            <ul className="open-list">
              {openInClosing.map((drop) => (
                <li key={drop.commitmentId}>
                  <Icon icon={Undo2} size={12} /> {drop.buyerName} ·{" "}
                  {boxes(drop.totalBoxes)}
                  {dropAddress(drop) ? ` · ${dropAddress(drop)}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="small">
            Alle Lieferungen dieses Fensters sind abgehakt.
          </p>
        )}
      </Modal>
    </div>
  );
}

/** j/k/d on the board; only where a hotkey registry exists (admin shell). */
function BoardHotkeys(props: {
  readonly move: (delta: number) => void;
  readonly onDeliver: () => void;
}) {
  const registry = useOptionalHotkeyRegistry();
  return registry ? <RegisteredBoardHotkeys {...props} /> : null;
}

function RegisteredBoardHotkeys({
  move,
  onDeliver,
}: {
  readonly move: (delta: number) => void;
  readonly onDeliver: () => void;
}) {
  useHotkeys([
    {
      keys: "j",
      label: "Nächste Lieferung",
      group: "Auslieferung",
      run: () => move(1),
    },
    {
      keys: "k",
      label: "Vorherige Lieferung",
      group: "Auslieferung",
      run: () => move(-1),
    },
    {
      keys: "d",
      label: "Als geliefert markieren / zurücknehmen",
      group: "Auslieferung",
      run: onDeliver,
    },
  ]);
  return null;
}

export type { DeliveryBoardResponse };
