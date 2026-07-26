import {
  ArrowRight02Icon,
  CheckmarkCircle02Icon,
  InboxUnreadIcon,
  PackageReceive01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  type ActivityFeedItemResponse,
  type ActivityFeedResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

interface ActivityFeedPageProps {
  readonly client: LeonAidApiClient;
  readonly surface: "pwa" | "web";
}

type FeedFilter = "all" | "unread";

function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

function quantityCopy(item: ActivityFeedItemResponse) {
  const boxes = `${item.totalBoxes} ${item.totalBoxes === 1 ? "Box" : "Boxen"}`;
  return `${boxes} · ${item.totalPieces} Stück`;
}

function updatedPage(
  current: ActivityFeedResponse,
  updated: ActivityFeedItemResponse,
  filter: FeedFilter,
): ActivityFeedResponse {
  const existing = current.items.find((item) => item.id === updated.id);
  if (!existing) return current;
  const becameRead = !existing.isRead && updated.isRead;
  const becameUnread = existing.isRead && !updated.isRead;
  return {
    ...current,
    items:
      filter === "unread" && updated.isRead
        ? current.items.filter((item) => item.id !== updated.id)
        : current.items.map((item) =>
            item.id === updated.id ? updated : item,
          ),
    unreadCount: Math.max(
      0,
      current.unreadCount - (becameRead ? 1 : 0) + (becameUnread ? 1 : 0),
    ),
  };
}

function ActivityFeedEntry({
  item,
  onToggleRead,
  pending,
}: {
  readonly item: ActivityFeedItemResponse;
  readonly onToggleRead: (item: ActivityFeedItemResponse) => void;
  readonly pending: boolean;
}) {
  return (
    <li
      className="activity-feed-entry"
      data-event-id={item.id}
      data-read={item.isRead}
      data-testid="activity-feed-entry"
    >
      <span aria-hidden="true" className="activity-feed-entry__marker">
        <HugeiconsIcon
          icon={PackageReceive01Icon}
          size={20}
          strokeWidth={1.8}
        />
      </span>
      <article>
        <div className="activity-feed-entry__meta">
          {!item.isRead ? (
            <span className="activity-feed-entry__new">Neu</span>
          ) : null}
          <time dateTime={item.occurredAt}>
            {formatDateTime(item.occurredAt)}
          </time>
          <span>{item.actionName}</span>
        </div>
        <h2>Neue öffentliche Bestellung</h2>
        <p>
          <strong>{item.partyDisplayName}</strong> hat {quantityCopy(item)} im
          Wert von {formatMoney(item.totalMinor, item.currency)} bestellt.
        </p>
        <dl className="activity-feed-entry__facts">
          <div>
            <dt>Bestellreferenz</dt>
            <dd>{item.publicReference}</dd>
          </div>
          <div>
            <dt>Kontaktart</dt>
            <dd>{item.partyKind === "company" ? "Firma" : "Person"}</dd>
          </div>
        </dl>
        <footer>
          <a
            className="activity-feed-entry__next"
            data-testid="activity-feed-next-action"
            href={item.nextActionHref}
          >
            {item.nextActionLabel}
            <HugeiconsIcon
              aria-hidden="true"
              icon={ArrowRight02Icon}
              size={18}
              strokeWidth={1.8}
            />
          </a>
          <button
            aria-label={
              item.isRead
                ? `${item.partyDisplayName} als ungelesen markieren`
                : `${item.partyDisplayName} als gelesen markieren`
            }
            className="activity-feed-entry__read-toggle"
            data-testid="activity-feed-read-toggle"
            disabled={pending}
            onClick={() => onToggleRead(item)}
            type="button"
          >
            <HugeiconsIcon
              aria-hidden="true"
              icon={CheckmarkCircle02Icon}
              size={18}
              strokeWidth={1.8}
            />
            {pending
              ? "Wird gespeichert …"
              : item.isRead
                ? "Als ungelesen"
                : "Als gelesen"}
          </button>
        </footer>
      </article>
    </li>
  );
}

export function ActivityFeedPage({ client, surface }: ActivityFeedPageProps) {
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const feed = useQuery({
    queryFn: () => client.getActivityFeed({ limit: 50, status: filter }),
    queryKey: ["activity-feed", filter],
  });
  const updateReadState = useMutation({
    mutationFn: ({
      eventId,
      read,
    }: {
      readonly eventId: string;
      readonly read: boolean;
    }) => client.updateActivityFeedItem(eventId, { read }),
    onError: () => setPendingId(null),
    onSuccess: (updated) => {
      queryClient.setQueryData<ActivityFeedResponse>(
        ["activity-feed", filter],
        (current) =>
          current ? updatedPage(current, updated, filter) : current,
      );
      setPendingId(null);
      void queryClient.invalidateQueries({ queryKey: ["activity-feed"] });
    },
  });

  function toggleRead(item: ActivityFeedItemResponse) {
    setPendingId(item.id);
    updateReadState.mutate({ eventId: item.id, read: !item.isRead });
  }

  const updateError =
    updateReadState.error instanceof ApiError &&
    updateReadState.error.status === 404
      ? "Dieser Eintrag ist nicht mehr verfügbar. Die Liste wurde aktualisiert."
      : "Der Lesestatus konnte nicht gespeichert werden. Versuche es erneut.";

  return (
    <div className="activity-feed-page" data-surface={surface}>
      <header className="activity-feed-page__header">
        <div>
          <p className="activity-feed-eyebrow">Dein Arbeitsvorrat</p>
          <h1>Neues &amp; Aktivitäten</h1>
          <p>
            Öffentliche Bestellungen deiner Sponsoren und der nächste sinnvolle
            Schritt – aktuell und ohne Doppelarbeit.
          </p>
        </div>
        <div
          aria-label={`${feed.data?.unreadCount ?? 0} ungelesene Einträge`}
          className="activity-feed-unread"
          data-testid="activity-feed-unread-count"
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={InboxUnreadIcon}
            size={22}
            strokeWidth={1.8}
          />
          <strong>{feed.data?.unreadCount ?? "–"}</strong>
          <span>ungelesen</span>
        </div>
      </header>

      <div className="activity-feed-toolbar">
        <div
          aria-label="Aktivitäten filtern"
          className="activity-feed-filter"
          role="tablist"
        >
          <button
            aria-selected={filter === "all"}
            onClick={() => setFilter("all")}
            role="tab"
            type="button"
          >
            Alle
          </button>
          <button
            aria-selected={filter === "unread"}
            onClick={() => setFilter("unread")}
            role="tab"
            type="button"
          >
            Ungelesen
            {feed.data?.unreadCount ? (
              <span>{feed.data.unreadCount}</span>
            ) : null}
          </button>
        </div>
        {feed.data ? (
          <span aria-live="polite">
            {feed.data.items.length}{" "}
            {feed.data.items.length === 1 ? "Eintrag" : "Einträge"}
          </span>
        ) : null}
      </div>

      {updateReadState.isError ? (
        <StatusMessage tone="error">{updateError}</StatusMessage>
      ) : null}

      {feed.isPending ? (
        <div
          aria-label="Aktivitäten werden geladen"
          className="activity-feed-loading"
          role="status"
        >
          <span />
          <span />
          <span />
        </div>
      ) : feed.isError ? (
        <StatusMessage tone="error">
          <div>
            <strong>Aktivitäten nicht erreichbar</strong>
            <p>
              Der Arbeitsvorrat konnte nicht geladen werden. Prüfe deine
              Verbindung und versuche es erneut.
            </p>
            <Button onClick={() => void feed.refetch()} variant="secondary">
              Erneut laden
            </Button>
          </div>
        </StatusMessage>
      ) : feed.data?.items.length ? (
        <ol className="activity-feed-list" data-testid="activity-feed-list">
          {feed.data.items.map((item) => (
            <ActivityFeedEntry
              item={item}
              key={item.id}
              onToggleRead={toggleRead}
              pending={pendingId === item.id}
            />
          ))}
        </ol>
      ) : (
        <div className="activity-feed-empty" data-testid="activity-feed-empty">
          <span aria-hidden="true">
            <HugeiconsIcon icon={InboxUnreadIcon} size={24} strokeWidth={1.8} />
          </span>
          <div>
            <strong>
              {filter === "unread"
                ? "Alles gelesen"
                : "Noch keine neuen Bestellungen"}
            </strong>
            <p>
              {filter === "unread"
                ? "Als ungelesen markierte Einträge erscheinen hier wieder."
                : "Neue öffentliche Bestellungen erscheinen hier automatisch und nennen direkt den nächsten Schritt."}
            </p>
          </div>
          {filter === "unread" ? (
            <Button onClick={() => setFilter("all")} variant="secondary">
              Alle Aktivitäten zeigen
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}
