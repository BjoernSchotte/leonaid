import { ClockAlert, Contact, Search, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, EmptyState, Icon, Modal, StatusMessage } from "@leonaid/ui";

import { CampaignEditorLink } from "../action-admin/campaign-editor-link";
import {
  requestedUnlistedAction,
  useActionInUrl,
} from "../action-admin/action-location";
import { AssignmentDetail, assignmentStatusLabels } from "./assignment-detail";

type AssignmentFilter =
  | "all"
  | "open"
  | "contacted"
  | "committed"
  | "declined"
  | "handed_over";

const PIPELINE_FILTERS: readonly (readonly [AssignmentFilter, string])[] = [
  ["all", "Alle"],
  ["open", "Offen"],
  ["contacted", "Kontaktiert"],
  ["committed", "Zugesagt"],
  ["declined", "Abgesagt"],
  ["handed_over", "Übergeben"],
];

interface AcquisitionAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

const statusLabels = assignmentStatusLabels;

const ASSIGNMENT_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The assignment a link asks to open (`?open=<id>`, e.g. a search hit). */
function requestedAssignment(): string | null {
  const value = new URLSearchParams(window.location.search).get("open");
  return value && ASSIGNMENT_ID.test(value) ? value : null;
}

/** Keeps `?open=` in step with the detail, without a history entry. */
function replaceOpenInUrl(assignmentId: string | null) {
  const url = new URL(window.location.href);
  if (assignmentId) url.searchParams.set("open", assignmentId);
  else url.searchParams.delete("open");
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

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
  const memberActions = useMemo(
    () => [
      ...new Map(
        identity.actionMemberships
          .filter((membership) => membership.role === "charity_admin")
          .map((membership) => [membership.actionId, membership]),
      ).values(),
    ],
    [identity.actionMemberships],
  );
  // A system admin manages every action. A search hit links to
  // ?action=<id>; keep that action selectable for the whole visit.
  const [unlistedActionId] = useState(() =>
    requestedUnlistedAction(
      memberActions,
      identity.globalRoles.includes("system_admin"),
    ),
  );
  const unlistedAction = useQuery({
    enabled: Boolean(unlistedActionId),
    queryFn: () => client.getCharityAction(unlistedActionId!),
    queryKey: ["charity-action", unlistedActionId],
  });
  const memberships = useMemo(
    () =>
      unlistedActionId
        ? [
            {
              actionId: unlistedActionId,
              actionName: unlistedAction.data?.name ?? "Charity-Aktion",
            },
            ...memberActions,
          ]
        : memberActions,
    [memberActions, unlistedAction.data?.name, unlistedActionId],
  );
  const query = new URLSearchParams(window.location.search);
  const requestedAction = query.get("action");
  const requestedStatus = query.get("status");
  const [actionId, setActionId] = useState(
    memberships.find((item) => item.actionId === requestedAction)?.actionId ??
      memberships[0]?.actionId ??
      "",
  );
  useActionInUrl(actionId);
  // The assignment whose detail is open. A link may ask for one of any
  // status, so it wins over a `?status=` in the same link.
  const [openId, setOpenId] = useState(requestedAssignment);
  // The row stays marked after its detail closes, so the eye finds it again.
  const [markedId, setMarkedId] = useState(openId);
  const [filter, setFilter] = useState<AssignmentFilter>(
    !openId &&
      ["open", "contacted", "committed", "declined", "handed_over"].includes(
        requestedStatus ?? "",
      )
      ? (requestedStatus as AssignmentFilter)
      : "all",
  );
  const filterTabs = useRef<(HTMLButtonElement | null)[]>([]);
  const chooseFilter = (value: AssignmentFilter) => {
    setFilter(value);
    const url = new URL(window.location.href);
    if (value === "all") url.searchParams.delete("status");
    else url.searchParams.set("status", value);
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  };
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
  const openItem = openId
    ? (board.data?.workItems.find((item) => item.assignmentId === openId) ??
      null)
    : null;
  const openMissing = Boolean(openId) && board.isSuccess && !openItem;
  const openAssignment = useCallback((assignmentId: string | null) => {
    setOpenId(assignmentId);
    if (assignmentId) setMarkedId(assignmentId);
    replaceOpenInUrl(assignmentId);
  }, []);
  // Bring the row of the open assignment into view once per assignment: a
  // link from the search lands on a long table.
  const openRow = useRef<HTMLTableRowElement | null>(null);
  const scrolledTo = useRef<string | null>(null);
  const openRowId = openItem?.assignmentId ?? null;
  useEffect(() => {
    if (!openRowId || scrolledTo.current === openRowId) return;
    scrolledTo.current = openRowId;
    openRow.current?.scrollIntoView({ block: "center" });
  }, [openRowId]);

  if (memberships.length === 0) {
    return (
      <EmptyState
        description="Sobald Sie eine Charity-Aktion verwalten, erscheint hier ihre aktionsweite Sponsor-Pipeline."
        headingLevel={2}
        icon={Contact}
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
        <div className="acq-field acq-action-picker">
          <label htmlFor="acquisition-admin-action">Charity-Aktion</label>
          <select
            data-testid="acquisition-admin-action"
            id="acquisition-admin-action"
            onChange={(event) => {
              // The open assignment belongs to the action that is left.
              openAssignment(null);
              setMarkedId(null);
              setActionId(event.target.value);
            }}
            value={actionId}
          >
            {memberships.map((membership) => (
              <option key={membership.actionId} value={membership.actionId}>
                {membership.actionName}
              </option>
            ))}
          </select>
          <CampaignEditorLink actionId={actionId} identity={identity} />
        </div>
      </header>

      <div className="acq-admin-toolbar">
        <div
          aria-label="Pipeline nach Status filtern"
          className="acq-tabs"
          role="tablist"
        >
          {PIPELINE_FILTERS.map(([value, label], index) => (
            <button
              aria-selected={filter === value}
              data-testid={`admin-pipeline-filter-${value}`}
              key={value}
              onClick={() => chooseFilter(value)}
              onKeyDown={(event) => {
                // ui Tabs pattern: arrows, Home and End move and select.
                const last = PIPELINE_FILTERS.length - 1;
                const next =
                  event.key === "ArrowRight"
                    ? index === last
                      ? 0
                      : index + 1
                    : event.key === "ArrowLeft"
                      ? index === 0
                        ? last
                        : index - 1
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? last
                          : -1;
                if (next < 0) return;
                event.preventDefault();
                chooseFilter(PIPELINE_FILTERS[next]![0]);
                filterTabs.current[next]?.focus();
              }}
              ref={(element) => {
                filterTabs.current[index] = element;
              }}
              role="tab"
              tabIndex={filter === value ? 0 : -1}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <label className="acq-search">
          <Icon icon={Search} size={18} />
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
          {openMissing ? (
            <StatusMessage tone="warning">
              <strong>Zuordnung nicht gefunden</strong>
              <p data-testid="acquisition-open-missing">
                Der Link verweist auf eine Zuordnung, die es in dieser
                Charity-Aktion nicht oder nicht mehr gibt.
              </p>
            </StatusMessage>
          ) : null}
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
                      aria-current={
                        item.assignmentId === markedId ? "true" : undefined
                      }
                      data-assignment-id={item.assignmentId}
                      data-status={item.status}
                      key={item.assignmentId}
                      ref={item.assignmentId === openId ? openRow : undefined}
                    >
                      <th scope="row">
                        <button
                          aria-haspopup="dialog"
                          className="acq-admin-open"
                          data-testid="acquisition-admin-open"
                          onClick={() => openAssignment(item.assignmentId)}
                          type="button"
                        >
                          {item.partyDisplayName}
                        </button>
                        <span>
                          {[item.postalCode, item.city]
                            .filter(Boolean)
                            .join(" ") || "Ort nicht gepflegt"}
                        </span>
                      </th>
                      <td>
                        <span className="acq-admin-assignees">
                          <Icon icon={Users} size={16} />
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
                          <Icon icon={ClockAlert} size={16} />
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
              description="Ändern Sie Status oder Suchbegriff. Die zugrunde liegenden Zuordnungen bleiben unverändert."
              title="Keine Zuordnung in dieser Ansicht"
            />
          )}
        </>
      )}
      <Modal
        footer={
          <Button onClick={() => openAssignment(null)} variant="secondary">
            Schließen
          </Button>
        }
        onClose={() => openAssignment(null)}
        open={Boolean(openItem)}
        size="lg"
        title={openItem?.partyDisplayName ?? ""}
      >
        {openItem ? (
          <AssignmentDetail
            actionId={actionId}
            client={client}
            item={openItem}
          />
        ) : null}
      </Modal>
    </div>
  );
}
