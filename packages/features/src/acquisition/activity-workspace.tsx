/*
 * "Wiedervorlagen" of the acquisition app (prototype pwa/Acquire.tsx
 * FollowUps): the acquirer's follow-ups, grouped by when they are due.
 * Contacts are recorded on the sponsor (detail, "Kontakt erfassen").
 */
import { ListTodo } from "lucide-react";
import { useEffect } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { EmptyState } from "@leonaid/ui";

import { isoDay, localIsoDate, relativeDay } from "../shared/dates";
import { navigateInPage } from "../shared/location";
import {
  ActionChoice,
  BoardFailed,
  BoardLoading,
  SponsorRow,
  sponsorHref,
  useAcquirerAction,
  useSponsorBoard,
} from "./pwa-common";

interface ActivityWorkspaceProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

function tomorrow(today: string) {
  const [year, month, day] = today.split("-").map(Number);
  return new Date(Date.UTC(year!, month! - 1, day! + 1))
    .toISOString()
    .slice(0, 10);
}

function Group({
  actionId,
  identity,
  items,
  testId,
  title,
}: {
  readonly actionId: string;
  readonly identity: CurrentIdentityResponse;
  readonly items: ReadonlyArray<AcquisitionActivityWorkItemResponse>;
  readonly testId: string;
  readonly title: string;
}) {
  if (!items.length) return null;
  return (
    <section aria-label={title} data-testid={testId}>
      <h2 className="pwa-h2">
        {title} <span className="muted num">{items.length}</span>
      </h2>
      <ul className="pwa-list">
        {items.map((item) => (
          <SponsorRow
            actionId={actionId}
            item={item}
            key={item.assignmentId}
            meta={[relativeDay(item.dueAt!), item.nextAction, item.contactName]
              .filter(Boolean)
              .join(" · ")}
            userId={identity.userId}
          />
        ))}
      </ul>
    </section>
  );
}

export function ActivityWorkspace({
  client,
  identity,
}: ActivityWorkspaceProps) {
  const { actionId, memberships, choose } = useAcquirerAction(identity);
  const board = useSponsorBoard(client, actionId);

  // Older links (?assignment=) recorded a contact here; that is the
  // sponsor's contact sheet now.
  const linked = new URLSearchParams(window.location.search).get("assignment");
  useEffect(() => {
    if (linked && actionId) {
      navigateInPage(`${sponsorHref(actionId, linked)}&contact=1`, {
        replace: true,
      });
    }
  }, [linked, actionId]);

  const today = localIsoDate();
  const next = tomorrow(today);
  const rows = (board.data?.workItems ?? [])
    .filter((item) => item.dueAt && item.nextAction)
    .sort((a, b) => (a.dueAt ?? "").localeCompare(b.dueAt ?? ""));
  const day = (item: AcquisitionActivityWorkItemResponse) =>
    isoDay(item.dueAt!);
  const overdue = rows.filter((item) => day(item) < today);
  const soon = rows.filter((item) => day(item) === today || day(item) === next);
  const later = rows.filter((item) => day(item) > next);

  return (
    <>
      <h1 className="pwa-h1">Wiedervorlagen</h1>
      <ActionChoice
        actionId={actionId}
        memberships={memberships}
        onChange={choose}
      />
      {board.isPending ? (
        <BoardLoading label="Wiedervorlagen werden geladen" />
      ) : board.isError ? (
        <BoardFailed
          onRetry={() => void board.refetch()}
          title="Wiedervorlagen nicht erreichbar"
        />
      ) : rows.length ? (
        <>
          <Group
            actionId={actionId}
            identity={identity}
            items={overdue}
            testId="follow-ups-overdue"
            title="Überfällig"
          />
          <Group
            actionId={actionId}
            identity={identity}
            items={soon}
            testId="follow-ups-soon"
            title="Heute und morgen"
          />
          <Group
            actionId={actionId}
            identity={identity}
            items={later}
            testId="follow-ups-later"
            title="Später"
          />
        </>
      ) : (
        <EmptyState
          description="Nach jedem Kontakt kannst du ein Datum setzen. Dann erinnert dich die App."
          icon={ListTodo}
          title="Keine Wiedervorlagen"
        />
      )}
    </>
  );
}
