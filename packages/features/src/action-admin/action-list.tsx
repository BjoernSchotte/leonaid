import { useQuery } from "@tanstack/react-query";
import { CircleDot, Flag, Tag, UserRound } from "lucide-react";
import { useCallback, useMemo } from "react";

import type {
  ActionGoalResponse,
  CharityActionSummaryResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  fullBleedPage,
  ListView,
  StatusIcon,
  StatusLabel,
  statusShape,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";
import { shortDate } from "../shared/dates";
import { statusLabels } from "./manage-sections";

/*
 * "Aktionen verwalten" (prototype pages/Campaigns.tsx CampaignList): the
 * actions this account manages as a ListView, grouped by status, with the
 * views "Laufend und geplant", "Alle" and "Archiv". A row opens the action.
 */

type ActionStatus = CharityActionSummaryResponse["status"];

const STATUS_ORDER: readonly ActionStatus[] = [
  "active",
  "scheduled",
  "draft",
  "completed",
  "archived",
];

const NO_TEMPLATE = "none";
const NO_LEAD = "none";

/** "1.200 €", "350 Boxen" or null without a goal (as the action's overview). */
export function goalText(
  goal: ActionGoalResponse,
  value: string | null,
): string | null {
  if (value === null || value === "") return null;
  const number = Number(value);
  if (goal.currency) {
    return Number.isFinite(number)
      ? new Intl.NumberFormat("de-DE", {
          currency: goal.currency,
          style: "currency",
        }).format(number)
      : `${value} ${goal.currency}`;
  }
  const formatted = Number.isFinite(number)
    ? new Intl.NumberFormat("de-DE").format(number)
    : value;
  return goal.unit ? `${formatted} ${goal.unit}` : formatted;
}

const period = (row: CharityActionSummaryResponse) =>
  `${shortDate(row.startsOn)} – ${shortDate(row.endsOn)}`;

export interface ActionListPageProps {
  readonly client: LeonAidApiClient;
}

export function ActionListPage({ client }: ActionListPageProps) {
  const actions = useQuery({
    queryKey: ["charity-actions"],
    queryFn: () => client.listCharityActions(),
    retry: false,
  });
  const rows = useMemo(() => actions.data?.items ?? [], [actions.data]);

  const properties = useMemo<ListProperty<CharityActionSummaryResponse>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: STATUS_ORDER.map((status) => ({
          value: status,
          label: statusLabels[status],
          icon: (
            <StatusIcon
              label={statusLabels[status]}
              status={statusShape[statusLabels[status]] ?? "draft"}
            />
          ),
        })),
        chip: (row) => <StatusLabel status={statusLabels[row.status]} />,
      },
      {
        id: "kind",
        label: "Art",
        icon: Tag,
        get: (row) => row.templateName ?? NO_TEMPLATE,
        options: [
          ...[
            ...new Set(
              rows.flatMap((row) =>
                row.templateName ? [row.templateName] : [],
              ),
            ),
          ]
            .sort((a, b) => a.localeCompare(b, "de"))
            .map((name) => ({ value: name, label: name })),
          { value: NO_TEMPLATE, label: "Ohne Vorlage" },
        ],
        chip: (row) =>
          row.templateName ? <span>{row.templateName}</span> : null,
      },
      {
        id: "lead",
        label: "Leitung",
        icon: UserRound,
        get: (row) => (row.leadNames.length ? row.leadNames : [NO_LEAD]),
        groupable: false,
        options: [
          ...[...new Set(rows.flatMap((row) => row.leadNames))]
            .sort((a, b) => a.localeCompare(b, "de"))
            .map((name) => ({ value: name, label: name })),
          { value: NO_LEAD, label: "Ohne Leitung" },
        ],
      },
    ],
    [rows],
  );

  const sorts = useMemo<ListSort<CharityActionSummaryResponse>[]>(
    () => [
      {
        id: "start",
        label: "Beginn",
        compare: (a, b) => b.startsOn.localeCompare(a.startsOn),
      },
      {
        id: "name",
        label: "Name A–Z",
        compare: (a, b) => a.name.localeCompare(b.name, "de"),
      },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      {
        id: "active",
        label: "Laufend und geplant",
        filters: [{ prop: "status", values: ["active", "scheduled", "draft"] }],
        groupBy: "status",
        sort: "start",
      },
      { id: "all", label: "Alle", filters: [], groupBy: null, sort: "start" },
      {
        id: "archive",
        label: "Archiv",
        filters: [{ prop: "status", values: ["archived", "completed"] }],
        groupBy: null,
        sort: "start",
      },
    ],
    [],
  );

  const columns = useMemo<ListColumns<CharityActionSummaryResponse>>(
    () => ({
      primary: (row) => <span data-action-row={row.id}>{row.name}</span>,
      secondary: (row) =>
        row.leadNames.length
          ? `${period(row)} · Leitung ${row.leadNames.join(", ")}`
          : period(row),
      trailing: (row) => goalText(row.goal, row.goal.goalValue) ?? "–",
    }),
    [],
  );

  const getId = useCallback((row: CharityActionSummaryResponse) => row.id, []);
  const searchText = useCallback(
    (row: CharityActionSummaryResponse) =>
      `${row.name} ${row.templateName ?? ""} ${statusLabels[row.status]} ${row.leadNames.join(" ")}`,
    [],
  );
  const detailTitle = useCallback(
    (row: CharityActionSummaryResponse) => row.name,
    [],
  );
  const rowHref = useCallback(
    (row: CharityActionSummaryResponse) =>
      `/admin/actions/${encodeURIComponent(row.id)}`,
    [],
  );

  return (
    <div className="action-list-page" data-zone="actions" {...fullBleedPage}>
      <ListView<CharityActionSummaryResponse>
        className="action-list"
        columns={columns}
        createCommandId="create:action"
        createLabel="Aktion anlegen"
        detailTitle={detailTitle}
        emptyIcon={Flag}
        entityLabel={{ one: "Aktion", many: "Aktionen" }}
        getId={getId}
        id="actions"
        onCreate={() => window.location.assign("/admin/actions/new")}
        onRetry={() => void actions.refetch()}
        properties={properties}
        rowHref={rowHref}
        rows={rows}
        searchText={searchText}
        sorts={sorts}
        status={
          actions.isPending ? "loading" : actions.isError ? "error" : "ready"
        }
        title="Aktionen"
        useCommands={useContextCommands}
        views={views}
      />
    </div>
  );
}
