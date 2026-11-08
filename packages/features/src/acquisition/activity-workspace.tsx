/*
 * "Wiedervorlagen" of the acquisition app (prototype pwa/Acquire.tsx
 * FollowUps): the acquirer's follow-ups, grouped by when they are due.
 * Contacts are recorded on the sponsor (detail, "Kontakt erfassen").
 */
import { ListTodo } from "lucide-react";
import { useQueries } from "@tanstack/react-query";
import { useEffect } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { EmptyState } from "@leonaid/ui";

import { useOfflineRuntime } from "../offline/runtime";
import { isoDay, localIsoDate, relativeDay } from "../shared/dates";
import {
  ActionChoice,
  BoardFailed,
  BoardLoading,
  SponsorRow,
  navigateToScreen,
  sponsorBoardQuery,
  sponsorHref,
  useAcquirerAction,
  useScreenHeading,
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
  const heading = useScreenHeading();

  // Links with ?assignment= (the "Neues" next action) open that sponsor's
  // contact sheet. The link names no campaign, so the campaign holding the
  // assignment is looked up among the acquirer's campaigns.
  const linked = new URLSearchParams(window.location.search).get("assignment");
  const runtime = useOfflineRuntime();
  const boards = useQueries({
    queries: linked
      ? memberships.map((membership) =>
          sponsorBoardQuery(client, runtime, membership.actionId),
        )
      : [],
  });
  const settled = boards.every((result) => !result.isPending);
  const owner = memberships.find((_, index) =>
    boards[index]?.data?.workItems.some((item) => item.assignmentId === linked),
  )?.actionId;
  useEffect(() => {
    if (!linked || !settled) return;
    const target = owner ?? actionId;
    if (!target) return;
    navigateToScreen(`${sponsorHref(target, linked)}&contact=1`, {
      replace: true,
    });
  }, [linked, settled, owner, actionId]);

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
      <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
        Wiedervorlagen
      </h1>
      <ActionChoice
        actionId={actionId}
        memberships={memberships}
        onChange={choose}
      />
      {board.isPending ? (
        <BoardLoading label="Wiedervorlagen werden geladen" />
      ) : board.isError ? (
        <BoardFailed
          error={board.error}
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
