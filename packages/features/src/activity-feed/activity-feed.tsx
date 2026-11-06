import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity as ActivityIcon,
  ArrowRight,
  CheckCheck,
  Circle,
  CircleDot,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import {
  ApiError,
  type ActivityFeedItemResponse,
  type ActivityFeedResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  cn,
  Icon,
  Kbd,
  EmptyState,
  ErrorState,
  SkeletonRows,
  StatusMessage,
  useHotkeys,
  useToast,
} from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";
import { formatQuantities } from "../commitments/quantities";
import { zoneForNavKey } from "../navigation/zones";
import { isoDay, localIsoDate } from "../shared/dates";

interface ActivityFeedPageProps {
  readonly client: LeonAidApiClient;
  readonly surface: "pwa" | "web";
}

type FeedFilter = "all" | "unread";

/** Public orders are the feed's one event type; they belong to "orders". */
const FEED_ZONE = "orders";
const PAGE_SIZE = 50;

function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

/** "Heute", "Gestern" or "Montag, 2. November" (Berlin day, prototype). */
export function feedDayLabel(occurredAt: string, today = localIsoDate()) {
  const day = isoDay(occurredAt);
  const diff = Math.round((Date.parse(today) - Date.parse(day)) / 86_400_000);
  if (diff === 0) return "Heute";
  if (diff === 1) return "Gestern";
  return new Intl.DateTimeFormat("de-DE", {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
    weekday: "long",
  }).format(new Date(`${day}T12:00:00Z`));
}

function groupByDay(items: readonly ActivityFeedItemResponse[]) {
  const groups = new Map<string, ActivityFeedItemResponse[]>();
  for (const item of items) {
    const key = feedDayLabel(item.occurredAt);
    const group = groups.get(key);
    if (group) group.push(item);
    else groups.set(key, [item]);
  }
  return [...groups.entries()];
}

/** Applies one changed entry to every loaded page and the unread count. */
export function withReadState(
  current: InfiniteData<ActivityFeedResponse, number>,
  updated: ActivityFeedItemResponse,
): InfiniteData<ActivityFeedResponse, number> {
  const existing = current.pages
    .flatMap((page) => page.items)
    .find((item) => item.id === updated.id);
  if (!existing) return current;
  const delta =
    !existing.isRead && updated.isRead
      ? -1
      : existing.isRead && !updated.isRead
        ? 1
        : 0;
  return {
    ...current,
    pages: current.pages.map((page) => ({
      ...page,
      items: page.items.map((item) =>
        item.id === updated.id ? updated : item,
      ),
      unreadCount: Math.max(0, page.unreadCount + delta),
    })),
  };
}

export function ActivityFeedPage({ client, surface }: ActivityFeedPageProps) {
  const du = surface === "pwa";
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [focusId, setFocusId] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const links = useRef(new Map<string, HTMLAnchorElement>());
  const queryClient = useQueryClient();
  const toast = useToast();
  const queryKey = ["activity-feed", filter] as const;
  const feed = useInfiniteQuery({
    queryFn: ({ pageParam }) =>
      client.getActivityFeed({
        limit: PAGE_SIZE,
        offset: pageParam,
        status: filter,
      }),
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total
        ? last.offset + last.items.length
        : undefined,
    initialPageParam: 0,
    queryKey,
  });

  const updateReadState = useMutation({
    mutationFn: ({
      id,
      read,
    }: {
      readonly id: string;
      readonly read: boolean;
    }) => client.updateActivityFeedItem(id, { read }),
    onError: () => setPendingId(null),
    onSuccess: (updated) => {
      queryClient.setQueryData<InfiniteData<ActivityFeedResponse, number>>(
        queryKey,
        (current) => (current ? withReadState(current, updated) : current),
      );
      setPendingId(null);
      void queryClient.invalidateQueries({ queryKey: ["activity-feed"] });
    },
  });
  const markAll = useMutation({
    mutationFn: () => client.markActivityFeedRead(),
    onSuccess: () => {
      toast.show({ title: "Alles als gelesen markiert.", tone: "success" });
      void queryClient.invalidateQueries({ queryKey: ["activity-feed"] });
    },
  });

  const items = useMemo(
    () => feed.data?.pages.flatMap((page) => page.items) ?? [],
    [feed.data],
  );
  // The newest page carries the current count.
  const unread = feed.data?.pages.at(-1)?.unreadCount ?? 0;
  const groups = useMemo(() => groupByDay(items), [items]);
  const zone = zoneForNavKey(FEED_ZONE);

  function toggleRead(item: ActivityFeedItemResponse) {
    setPendingId(item.id);
    updateReadState.mutate({ id: item.id, read: !item.isRead });
  }
  function markAllRead() {
    if (unread > 0 && !markAll.isPending) markAll.mutate();
  }
  function move(delta: number) {
    if (!items.length) return;
    const index = items.findIndex((item) => item.id === focusId);
    const next =
      items[
        Math.max(
          0,
          Math.min(items.length - 1, index === -1 ? 0 : index + delta),
        )
      ];
    if (!next) return;
    setFocusId(next.id);
    links.current.get(next.id)?.focus();
  }

  useHotkeys([
    {
      keys: "j",
      label: "Nächster Eintrag",
      group: "Aktivität",
      run: () => move(1),
    },
    {
      keys: "k",
      label: "Vorheriger Eintrag",
      group: "Aktivität",
      run: () => move(-1),
    },
    {
      keys: "u",
      label: "Gelesen/ungelesen",
      group: "Aktivität",
      run: () => {
        const item = items.find((entry) => entry.id === focusId);
        if (item) toggleRead(item);
      },
    },
    {
      keys: "shift+u",
      label: "Alle als gelesen markieren",
      group: "Aktivität",
      run: markAllRead,
    },
  ]);
  useContextCommands([
    {
      id: "feed-read-all",
      label: "Alle als gelesen markieren",
      group: "Aktivität",
      icon: CheckCheck,
      keys: "shift+u",
      run: markAllRead,
    },
  ]);

  const filtered = filter === "unread";
  const readError =
    updateReadState.error instanceof ApiError &&
    updateReadState.error.status === 404
      ? "Dieser Eintrag ist nicht mehr verfügbar. Die Liste wurde aktualisiert."
      : du
        ? "Der Lesestatus konnte nicht gespeichert werden. Versuche es erneut."
        : "Der Lesestatus konnte nicht gespeichert werden. Versuchen Sie es erneut.";

  return (
    <div className="activity" data-surface={surface} data-zone={FEED_ZONE}>
      <header className="page-header">
        <div className="page-heading">
          <h1>{du ? "Neues" : "Aktivität"}</h1>
          <span
            aria-live="polite"
            className="page-count num"
            data-testid="activity-feed-unread-count"
          >
            {feed.data
              ? unread
                ? `${unread} ungelesen`
                : "Alles gelesen"
              : ""}
          </span>
        </div>
        <Button
          disabled={!unread || markAll.isPending}
          icon={CheckCheck}
          loading={markAll.isPending}
          onClick={markAllRead}
          variant="secondary"
        >
          Alle als gelesen markieren
        </Button>
      </header>

      <div
        aria-label="Nach Bereich filtern"
        className="feed-filters"
        role="group"
      >
        <button
          aria-pressed={filtered}
          className={cn("feed-chip", filtered && "is-on")}
          onClick={() => setFilter(filtered ? "all" : "unread")}
          type="button"
        >
          <Icon icon={CircleDot} size={12} /> Nur ungelesene
        </button>
        {filtered ? (
          <button
            className="chip-clear"
            onClick={() => setFilter("all")}
            type="button"
          >
            Zurücksetzen
          </button>
        ) : null}
      </div>

      {updateReadState.isError || markAll.isError ? (
        <StatusMessage tone="error">{readError}</StatusMessage>
      ) : null}

      {feed.isPending ? (
        <SkeletonRows rows={5} />
      ) : feed.isError ? (
        <ErrorState
          onRetry={() => void feed.refetch()}
          title="Aktivitäten nicht erreichbar"
        >
          {du
            ? "Prüfe deine Verbindung und versuche es erneut."
            : "Prüfen Sie die Verbindung und versuchen Sie es erneut."}
        </ErrorState>
      ) : items.length === 0 ? (
        <div data-testid="activity-feed-empty">
          <EmptyState
            description={
              filtered
                ? du
                  ? "Entferne den Filter, um mehr zu sehen."
                  : "Entfernen Sie den Filter, um mehr zu sehen."
                : "Neue öffentliche Bestellungen erscheinen hier und nennen den nächsten Schritt."
            }
            headingLevel={2}
            icon={ActivityIcon}
            title={filtered ? "Nichts in dieser Auswahl" : "Alles erledigt"}
          />
        </div>
      ) : (
        <div data-testid="activity-feed-list">
          {groups.map(([day, dayItems]) => (
            <section aria-label={day} className="feed-day" key={day}>
              <h2 className="feed-day-title">{day}</h2>
              <ol className="feed">
                {dayItems.map((item) => (
                  <li
                    className={cn(
                      "feed-item",
                      !item.isRead && "is-unread",
                      focusId === item.id && "is-focused",
                    )}
                    data-event-id={item.id}
                    data-read={item.isRead}
                    data-testid="activity-feed-entry"
                    data-zone={FEED_ZONE}
                    key={item.id}
                  >
                    <span aria-hidden="true" className="feed-zone">
                      {zone ? <Icon icon={zone.icon} size={14} /> : null}
                    </span>
                    <a
                      className="feed-link"
                      data-testid="activity-feed-next-action"
                      href={item.nextActionHref}
                      title={`Bestellreferenz ${item.publicReference}`}
                      onClick={() => {
                        // Opening an entry reads it; the link still navigates.
                        if (!item.isRead) {
                          // The link is a full-page navigation, which aborts
                          // a normal fetch mid-request (the API then sees a
                          // half-read body, 400). keepalive lets the write
                          // finish after the page is gone.
                          void client
                            .updateActivityFeedItem(
                              item.id,
                              { read: true },
                              { keepalive: true },
                            )
                            .catch(() => undefined)
                            .finally(
                              () =>
                                void queryClient.invalidateQueries({
                                  queryKey: ["activity-feed"],
                                }),
                            );
                        }
                      }}
                      onFocus={() => setFocusId(item.id)}
                      ref={(element) => {
                        if (element) links.current.set(item.id, element);
                        else links.current.delete(item.id);
                      }}
                      tabIndex={item.id === (focusId ?? items[0]?.id) ? 0 : -1}
                    >
                      <span className="feed-text">
                        <strong>{item.partyDisplayName}</strong> hat öffentlich
                        bestellt
                      </span>
                      <span className="feed-object">
                        {formatQuantities(item.quantities, item.totalPieces)} ·{" "}
                        {formatMoney(item.totalMinor, item.currency)} ·{" "}
                        {item.actionName}
                      </span>
                      <span className="feed-next">
                        {item.nextActionLabel}
                        <Icon icon={ArrowRight} size={12} />
                      </span>
                    </a>
                    <time className="feed-time num" dateTime={item.occurredAt}>
                      {formatTime(item.occurredAt)}
                    </time>
                    <button
                      aria-label={
                        item.isRead
                          ? `${item.partyDisplayName} als ungelesen markieren`
                          : `${item.partyDisplayName} als gelesen markieren`
                      }
                      className="feed-read"
                      data-testid="activity-feed-read-toggle"
                      disabled={pendingId === item.id}
                      onClick={() => toggleRead(item)}
                      title={
                        item.isRead
                          ? "Als ungelesen markieren (U)"
                          : "Als gelesen markieren (U)"
                      }
                      type="button"
                    >
                      <Icon icon={item.isRead ? Circle : CircleDot} size={14} />
                    </button>
                    {!item.isRead ? (
                      <span className="sr-only">ungelesen</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </section>
          ))}
          {feed.hasNextPage ? (
            <Button
              className="feed-more"
              loading={feed.isFetchingNextPage}
              onClick={() => void feed.fetchNextPage()}
              variant="ghost"
            >
              Ältere Einträge laden
            </Button>
          ) : null}
        </div>
      )}
      <p aria-hidden="true" className="list-hint">
        <Kbd announce={false} keys="j" /> <Kbd announce={false} keys="k" />{" "}
        bewegen · <Kbd announce={false} keys="enter" /> öffnen ·{" "}
        <Kbd announce={false} keys="u" /> gelesen/ungelesen ·{" "}
        <Kbd announce={false} keys="shift+u" /> alle gelesen
      </p>
    </div>
  );
}
