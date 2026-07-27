import {
  AddressBookIcon,
  ClockAlertIcon,
  Search01Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, EmptyState, StatusMessage } from "@leonaid/ui";

type AssignmentFilter =
  | "all"
  | "open"
  | "contacted"
  | "committed"
  | "declined"
  | "handed_over";

interface AcquisitionAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

const statusLabels = {
  committed: "Zugesagt",
  contacted: "Kontaktiert",
  declined: "Abgesagt",
  handed_over: "Übergeben",
  open: "Offen",
} as const;

function formatDue(item: AcquisitionActivityWorkItemResponse) {
  if (!item.dueAt) return "Nicht terminiert";
  const date = new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeZone: "Europe/Berlin",
  }).format(new Date(item.dueAt));
  if (item.urgency === "overdue") return `Überfällig · ${date}`;
  if (item.urgency === "today") return `Heute · ${date}`;
  return date;
}

export function AcquisitionAdminPage({
  client,
  identity,
}: AcquisitionAdminPageProps) {
  const memberships = useMemo(
    () => [
      ...new Map(
        identity.actionMemberships
          .filter((membership) => membership.role === "charity_admin")
          .map((membership) => [membership.actionId, membership]),
      ).values(),
    ],
    [identity.actionMemberships],
  );
  const query = new URLSearchParams(window.location.search);
  const requestedAction = query.get("action");
  const requestedStatus = query.get("status");
  const [actionId, setActionId] = useState(
    memberships.find((item) => item.actionId === requestedAction)?.actionId ??
      memberships[0]?.actionId ??
      "",
  );
  const [filter, setFilter] = useState<AssignmentFilter>(
    ["open", "contacted", "committed", "declined", "handed_over"].includes(
      requestedStatus ?? "",
    )
      ? (requestedStatus as AssignmentFilter)
      : "all",
  );
  const [search, setSearch] = useState("");
  const board = useQuery({
    enabled: Boolean(actionId),
    queryFn: () =>
      client.getAcquisitionActivityBoard(actionId, {
        limit: 100,
        scope: "action",
      }),
    queryKey: ["acquisition-admin-board", actionId],
  });
  const normalizedSearch = search.trim().toLocaleLowerCase("de-DE");
  const visible =
    board.data?.workItems.filter((item) => {
      if (filter !== "all" && item.status !== filter) return false;
      if (!normalizedSearch) return true;
      return [
        item.partyDisplayName,
        item.postalCode,
        item.city,
        ...item.assignedAcquirers.map((acquirer) => acquirer.displayName),
      ]
        .filter(Boolean)
        .some((value) =>
          value?.toLocaleLowerCase("de-DE").includes(normalizedSearch),
        );
    }) ?? [];

  if (memberships.length === 0) {
    return (
      <EmptyState
        description="Sobald du eine Charity-Aktion verwaltest, erscheint hier ihre aktionsweite Sponsor-Pipeline."
        icon={
          <HugeiconsIcon icon={AddressBookIcon} size={24} strokeWidth={1.7} />
        }
        title="Keine verwaltete Akquise-Aktion"
      />
    );
  }

  return (
    <div className="acq-admin-page">
      <header className="acq-page__header acq-page__header--with-action">
        <div>
          <p className="acq-eyebrow">Aktionsweite Akquise</p>
          <h1>Sponsor-Pipeline</h1>
          <p>
            Zuständigkeiten und Status aller Akquisiteure in einer prüfbaren
            Arbeitsliste.
          </p>
        </div>
        <label className="acq-action-picker">
          <span>Charity-Aktion</span>
          <select
            data-testid="acquisition-admin-action"
            onChange={(event) => {
              setActionId(event.target.value);
              const url = new URL(window.location.href);
              url.searchParams.set("action", event.target.value);
              window.history.replaceState(
                {},
                "",
                `${url.pathname}${url.search}`,
              );
            }}
            value={actionId}
          >
            {memberships.map((membership) => (
              <option key={membership.actionId} value={membership.actionId}>
                {membership.actionName}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="acq-admin-toolbar">
        <div
          aria-label="Pipeline nach Status filtern"
          className="acq-tabs"
          role="tablist"
        >
          {(
            [
              ["all", "Alle"],
              ["open", "Offen"],
              ["contacted", "Kontaktiert"],
              ["committed", "Zugesagt"],
              ["declined", "Abgesagt"],
              ["handed_over", "Übergeben"],
            ] as const
          ).map(([value, label]) => (
            <button
              aria-selected={filter === value}
              data-testid={`admin-pipeline-filter-${value}`}
              key={value}
              onClick={() => {
                setFilter(value);
                const url = new URL(window.location.href);
                if (value === "all") url.searchParams.delete("status");
                else url.searchParams.set("status", value);
                window.history.replaceState(
                  {},
                  "",
                  `${url.pathname}${url.search}`,
                );
              }}
              role="tab"
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <label className="acq-search">
          <HugeiconsIcon
            aria-hidden="true"
            icon={Search01Icon}
            size={19}
            strokeWidth={1.8}
          />
          <span className="sr-only">Pipeline durchsuchen</span>
          <input
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Sponsor, Ort oder Akquisiteur"
            type="search"
            value={search}
          />
        </label>
      </div>

      {board.isPending ? (
        <div aria-live="polite" className="acq-skeleton" role="status">
          <span />
          <span />
          <span />
          <p className="sr-only">Sponsor-Pipeline wird geladen</p>
        </div>
      ) : board.isError ? (
        <StatusMessage tone="error">
          <strong>Sponsor-Pipeline nicht erreichbar</strong>
          <p>Die aktionsweiten Zuständigkeiten konnten nicht geladen werden.</p>
          <Button onClick={() => void board.refetch()} variant="secondary">
            Erneut laden
          </Button>
        </StatusMessage>
      ) : (
        <>
          <p aria-live="polite" className="acq-admin-result-count">
            {visible.length}{" "}
            {visible.length === 1 ? "Zuordnung" : "Zuordnungen"}
          </p>

          {visible.length ? (
            <div
              className="acq-admin-table-wrap"
              data-testid="acquisition-admin-list"
            >
              <table>
                <caption className="sr-only">
                  Sponsor-Zuordnungen der ausgewählten Charity-Aktion
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Sponsor</th>
                    <th scope="col">Akquisiteure</th>
                    <th scope="col">Status</th>
                    <th scope="col">Nächster Schritt</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((item) => (
                    <tr
                      data-assignment-id={item.assignmentId}
                      data-status={item.status}
                      key={item.assignmentId}
                    >
                      <th scope="row">
                        <strong>{item.partyDisplayName}</strong>
                        <span>
                          {[item.postalCode, item.city]
                            .filter(Boolean)
                            .join(" ") || "Ort nicht gepflegt"}
                        </span>
                      </th>
                      <td>
                        <span className="acq-admin-assignees">
                          <HugeiconsIcon
                            aria-hidden="true"
                            icon={UserMultiple02Icon}
                            size={17}
                            strokeWidth={1.8}
                          />
                          {item.assignedAcquirers
                            .map((person) => person.displayName)
                            .join(", ")}
                        </span>
                      </td>
                      <td>
                        <span className="acq-admin-status">
                          {statusLabels[item.status]}
                        </span>
                      </td>
                      <td>
                        <strong>
                          {item.nextAction ?? "Noch nicht geplant"}
                        </strong>
                        <span
                          className="acq-admin-due"
                          data-urgency={item.urgency}
                        >
                          <HugeiconsIcon
                            aria-hidden="true"
                            icon={ClockAlertIcon}
                            size={16}
                            strokeWidth={1.8}
                          />
                          {formatDue(item)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              description="Ändere Status oder Suchbegriff. Die zugrunde liegenden Zuordnungen bleiben unverändert."
              title="Keine Zuordnung in dieser Ansicht"
            />
          )}
        </>
      )}
    </div>
  );
}
