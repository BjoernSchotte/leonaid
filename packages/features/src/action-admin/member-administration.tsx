import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  Search01Icon,
  UserAdd01Icon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  type LeonAidApiClient,
  type MemberDirectoryMemberResponse,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";
import { MemberInvitationPage } from "./member-invitation";

export interface MemberAdministrationPageProps {
  readonly client: LeonAidApiClient;
}

type MemberView = "directory" | "invite";
type MemberStatus = "" | "invited" | "active" | "suspended" | "archived";

const statusOptions: ReadonlyArray<{
  readonly label: string;
  readonly value: MemberStatus;
}> = [
  { label: "Alle Status", value: "" },
  { label: "Aktiv", value: "active" },
  { label: "Eingeladen", value: "invited" },
  { label: "Gesperrt", value: "suspended" },
  { label: "Archiviert", value: "archived" },
];

const dateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

function initialView(): MemberView {
  return new URLSearchParams(window.location.search).get("view") === "invite"
    ? "invite"
    : "directory";
}

function initials(displayName: string): string {
  return displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toLocaleUpperCase("de-DE") ?? "")
    .join("");
}

function MemberDetail({
  client,
  memberId,
  partial,
}: {
  readonly client: LeonAidApiClient;
  readonly memberId: string | undefined;
  readonly partial: boolean;
}) {
  const detail = useQuery({
    enabled: Boolean(memberId),
    queryFn: () => client.getMember(memberId ?? ""),
    queryKey: ["member-detail", memberId],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    staleTime: 15_000,
  });

  if (!memberId) {
    return (
      <aside className="member-detail member-detail--empty">
        <div aria-hidden="true" className="member-detail__empty-icon">
          <HugeiconsIcon icon={UserGroupIcon} size={25} strokeWidth={1.7} />
        </div>
        <h2>Mitglied auswählen</h2>
        <p>
          Öffne einen Eintrag, um Rollen, Aktionszuordnungen und Sitzungen zu
          sehen.
        </p>
      </aside>
    );
  }

  if (detail.isPending) {
    return (
      <aside
        aria-live="polite"
        className="member-detail member-detail--loading"
        role="status"
      >
        <span aria-hidden="true" />
        <p>Mitgliedsdetails werden geladen …</p>
      </aside>
    );
  }

  if (detail.isError) {
    const error = actionErrorMessage(detail.error);
    return (
      <aside className="member-detail">
        <StatusMessage tone="error">
          <strong>Details nicht erreichbar</strong>
          <p>{error.message}</p>
          <Button onClick={() => void detail.refetch()} variant="secondary">
            Erneut versuchen
          </Button>
        </StatusMessage>
      </aside>
    );
  }

  const member = detail.data;
  return (
    <aside
      aria-label={`Details zu ${member.displayName}`}
      className="member-detail"
      data-testid="member-detail"
    >
      <div className="member-detail__identity">
        <span aria-hidden="true" className="member-avatar member-avatar--large">
          {initials(member.displayName)}
        </span>
        <div>
          <span
            className="member-status"
            data-status={member.status}
            data-testid="member-detail-status"
          >
            {member.statusLabel}
          </span>
          <h2>{member.displayName}</h2>
          <a href={`mailto:${member.email}`}>{member.email}</a>
        </div>
      </div>

      <dl className="member-detail__facts">
        <div>
          <dt>Letzte Anmeldung</dt>
          <dd>
            {member.lastLoginAt
              ? dateTime.format(new Date(member.lastLoginAt))
              : "Noch keine Anmeldung"}
          </dd>
        </div>
        <div>
          <dt>Aktive Sitzungen</dt>
          <dd>
            {member.activeSessionCount === 1
              ? "1 Sitzung"
              : `${member.activeSessionCount} Sitzungen`}
          </dd>
        </div>
      </dl>

      {member.globalRoleLabels.length > 0 ? (
        <section className="member-detail__section">
          <h3>Globale Rollen</h3>
          <div className="member-chip-list">
            {member.globalRoleLabels.map((role) => (
              <span className="member-chip member-chip--global" key={role}>
                {role}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <section className="member-detail__section">
        <h3>Charity-Aktionen</h3>
        {member.actionMemberships.length > 0 ? (
          <ul className="member-memberships">
            {member.actionMemberships.map((membership) => (
              <li
                key={`${membership.actionId}:${membership.role}`}
                data-testid="member-membership"
              >
                <span>{membership.actionName}</span>
                <strong>{membership.roleLabel}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p>Derzeit keiner Charity-Aktion zugeordnet.</p>
        )}
      </section>

      {partial ? (
        <p className="member-detail__scope-note">
          Du siehst ausschließlich Rollen in deinen verwalteten Aktionen.
          Globale Rollen bleiben ausgeblendet.
        </p>
      ) : null}
    </aside>
  );
}

function MemberCard({
  member,
  selected,
  onSelect,
}: {
  readonly member: MemberDirectoryMemberResponse;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  const roleLabels = [
    ...member.globalRoleLabels,
    ...new Set(
      member.actionMemberships.map((membership) => membership.roleLabel),
    ),
  ];
  return (
    <li>
      <button
        aria-current={selected ? "true" : undefined}
        className="member-card"
        data-testid="member-card"
        onClick={onSelect}
        type="button"
      >
        <span aria-hidden="true" className="member-avatar">
          {initials(member.displayName)}
        </span>
        <span className="member-card__body">
          <span className="member-card__title">
            <strong>{member.displayName}</strong>
            <span className="member-status" data-status={member.status}>
              {member.statusLabel}
            </span>
          </span>
          <span className="member-card__email">{member.email}</span>
          <span className="member-card__roles">
            {roleLabels.length > 0
              ? roleLabels.join(" · ")
              : "Noch ohne Rollenzuordnung"}
          </span>
        </span>
        <HugeiconsIcon
          aria-hidden="true"
          icon={ArrowRight01Icon}
          size={19}
          strokeWidth={1.8}
        />
      </button>
    </li>
  );
}

function MemberDirectory({ client }: { readonly client: LeonAidApiClient }) {
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<MemberStatus>("");
  const [actionId, setActionId] = useState("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [cursorHistory, setCursorHistory] = useState<
    ReadonlyArray<string | undefined>
  >([]);
  const [selectedMemberId, setSelectedMemberId] = useState<string>();

  const directory = useQuery({
    placeholderData: (previous) => previous,
    queryFn: () =>
      client.listMembers({
        actionId: actionId || undefined,
        cursor,
        limit: 6,
        search: search || undefined,
        status: status || undefined,
      }),
    queryKey: ["members", search, status, actionId, cursor],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    staleTime: 10_000,
  });

  useEffect(() => {
    if (!directory.data) return;
    const stillVisible = directory.data.items.some(
      (item) => item.userId === selectedMemberId,
    );
    if (!stillVisible) {
      setSelectedMemberId(directory.data.items[0]?.userId);
    }
  }, [directory.data, selectedMemberId]);

  const hasFilters = Boolean(search || status || actionId);
  const resultLabel = useMemo(() => {
    if (!directory.data) return "";
    return directory.data.total === 1
      ? "1 Mitglied"
      : `${directory.data.total} Mitglieder`;
  }, [directory.data]);

  function resetPage() {
    setCursor(undefined);
    setCursorHistory([]);
    setSelectedMemberId(undefined);
  }

  if (directory.isPending) {
    return (
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h2>Mitglieder werden geladen</h2>
        <p>Rollen und Aktionszugriffe werden sicher aufbereitet.</p>
      </div>
    );
  }

  if (directory.isError) {
    const error = actionErrorMessage(directory.error);
    return (
      <StatusMessage tone="error">
        <h2>Mitglieder konnten nicht geladen werden</h2>
        <p>{error.message}</p>
        <Button onClick={() => void directory.refetch()} variant="secondary">
          Erneut versuchen
        </Button>
      </StatusMessage>
    );
  }

  return (
    <div className="member-directory">
      {directory.data.partial ? (
        <div className="member-scope-note" role="note">
          <strong>Ansicht deiner Aktionen</strong>
          <span>
            Sichtbar sind nur Mitglieder und Rollen aus Charity-Aktionen, die du
            selbst verwaltest.
          </span>
        </div>
      ) : (
        <div
          className="member-scope-note member-scope-note--global"
          role="note"
        >
          <strong>Clubweite Ansicht</strong>
          <span>
            Du siehst alle Konten, globalen Rollen und Aktionszuordnungen.
          </span>
        </div>
      )}

      <form
        className="member-filters"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(searchDraft.trim());
          resetPage();
        }}
        role="search"
      >
        <label className="member-search">
          <span>Mitglied suchen</span>
          <span className="member-search__control">
            <HugeiconsIcon
              aria-hidden="true"
              icon={Search01Icon}
              size={18}
              strokeWidth={1.8}
            />
            <input
              autoComplete="off"
              maxLength={160}
              onChange={(event) => setSearchDraft(event.currentTarget.value)}
              placeholder="Name oder Login-E-Mail"
              type="search"
              value={searchDraft}
            />
          </span>
        </label>
        <label>
          <span>Status</span>
          <select
            data-testid="member-status-filter"
            onChange={(event) => {
              setStatus(event.currentTarget.value as MemberStatus);
              resetPage();
            }}
            value={status}
          >
            {statusOptions.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Charity-Aktion</span>
          <select
            data-testid="member-action-filter"
            onChange={(event) => {
              setActionId(event.currentTarget.value);
              resetPage();
            }}
            value={actionId}
          >
            <option value="">Alle sichtbaren Aktionen</option>
            {directory.data.actions.map((action) => (
              <option key={action.actionId} value={action.actionId}>
                {action.actionName}
              </option>
            ))}
          </select>
        </label>
        <Button
          icon={
            <HugeiconsIcon
              aria-hidden="true"
              icon={Search01Icon}
              size={18}
              strokeWidth={1.8}
            />
          }
          type="submit"
        >
          Suchen
        </Button>
      </form>

      <div className="member-result-bar" aria-live="polite">
        <span>
          <strong>{resultLabel}</strong>
          {directory.isFetching ? " · wird aktualisiert …" : ""}
        </span>
        {hasFilters ? (
          <button
            onClick={() => {
              setSearchDraft("");
              setSearch("");
              setStatus("");
              setActionId("");
              resetPage();
            }}
            type="button"
          >
            Filter zurücksetzen
          </button>
        ) : null}
      </div>

      {directory.data.items.length === 0 ? (
        <div className="member-empty">
          <div aria-hidden="true">
            <HugeiconsIcon icon={Search01Icon} size={25} strokeWidth={1.7} />
          </div>
          <h2>
            {hasFilters
              ? "Keine passenden Mitglieder"
              : "Noch keine Mitglieder"}
          </h2>
          <p>
            {hasFilters
              ? "Passe Suche oder Filter an, um andere Einträge zu sehen."
              : "Wechsle zu „Mitglied einladen“, um den ersten Zugang anzulegen."}
          </p>
        </div>
      ) : (
        <div className="member-directory__workspace">
          <div>
            <ul aria-label="Mitglieder" className="member-list">
              {directory.data.items.map((member) => (
                <MemberCard
                  key={member.userId}
                  member={member}
                  onSelect={() => setSelectedMemberId(member.userId)}
                  selected={member.userId === selectedMemberId}
                />
              ))}
            </ul>
            <nav aria-label="Mitgliederseiten" className="member-pagination">
              <Button
                disabled={cursorHistory.length === 0}
                icon={
                  <HugeiconsIcon
                    aria-hidden="true"
                    icon={ArrowLeft01Icon}
                    size={18}
                    strokeWidth={1.8}
                  />
                }
                onClick={() => {
                  const previous = cursorHistory.at(-1);
                  setCursor(previous);
                  setCursorHistory((current) => current.slice(0, -1));
                  setSelectedMemberId(undefined);
                }}
                variant="secondary"
              >
                Zurück
              </Button>
              <span>Seite {cursorHistory.length + 1}</span>
              <Button
                disabled={!directory.data.nextCursor}
                onClick={() => {
                  setCursorHistory((current) => [...current, cursor]);
                  setCursor(directory.data.nextCursor ?? undefined);
                  setSelectedMemberId(undefined);
                }}
                variant="secondary"
              >
                Weiter
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={ArrowRight01Icon}
                  size={18}
                  strokeWidth={1.8}
                />
              </Button>
            </nav>
          </div>
          <MemberDetail
            client={client}
            memberId={selectedMemberId}
            partial={directory.data.partial}
          />
        </div>
      )}
    </div>
  );
}

export function MemberAdministrationPage({
  client,
}: MemberAdministrationPageProps) {
  const [view, setView] = useState<MemberView>(initialView);

  function selectView(next: MemberView) {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "invite") url.searchParams.set("view", "invite");
    else url.searchParams.delete("view");
    window.history.replaceState({}, "", url);
  }

  function handleTabKey(
    event: React.KeyboardEvent<HTMLButtonElement>,
    current: MemberView,
  ) {
    let next: MemberView | undefined;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      next = current === "directory" ? "invite" : "directory";
    } else if (event.key === "Home") {
      next = "directory";
    } else if (event.key === "End") {
      next = "invite";
    }
    if (!next) return;
    event.preventDefault();
    selectView(next);
    document.getElementById(`member-${next}-tab`)?.focus();
  }

  return (
    <div className="action-page action-page--members">
      <header className="action-page__header">
        <div>
          <p className="action-page__eyebrow">Mitglieder</p>
          <h1>Mitglieder verwalten</h1>
          <p>
            Finde Zugänge, prüfe Rollen und ordne neue Mitglieder direkt einer
            Charity-Aktion zu.
          </p>
        </div>
      </header>

      <div
        aria-label="Mitgliederbereiche"
        className="member-view-tabs"
        role="tablist"
      >
        <button
          aria-controls="member-directory-panel"
          aria-selected={view === "directory"}
          id="member-directory-tab"
          onKeyDown={(event) => handleTabKey(event, "directory")}
          onClick={() => selectView("directory")}
          role="tab"
          type="button"
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={UserGroupIcon}
            size={20}
            strokeWidth={1.8}
          />
          <span>
            <strong>Mitgliederübersicht</strong>
            <small>Suchen, filtern und Details prüfen</small>
          </span>
        </button>
        <button
          aria-controls="member-invite-panel"
          aria-selected={view === "invite"}
          id="member-invite-tab"
          onKeyDown={(event) => handleTabKey(event, "invite")}
          onClick={() => selectView("invite")}
          role="tab"
          type="button"
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={UserAdd01Icon}
            size={20}
            strokeWidth={1.8}
          />
          <span>
            <strong>Mitglied einladen</strong>
            <small>Zugang und Aktionsrolle anlegen</small>
          </span>
        </button>
      </div>

      <section
        aria-labelledby={`${view === "directory" ? "member-directory" : "member-invite"}-tab`}
        id={`${view === "directory" ? "member-directory" : "member-invite"}-panel`}
        role="tabpanel"
        tabIndex={0}
      >
        {view === "directory" ? (
          <MemberDirectory client={client} />
        ) : (
          <MemberInvitationPage client={client} embedded />
        )}
      </section>
    </div>
  );
}
