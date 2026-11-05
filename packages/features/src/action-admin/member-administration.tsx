import { useQuery } from "@tanstack/react-query";
import { CircleDot, Flag, Info, MailPlus, Users } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  ErrorState,
  fullBleedPage,
  Icon,
  ListView,
  StatusIcon,
  StatusLabel,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { consumeCreateRequest } from "../command-palette/create-request";
import { useContextCommands } from "../command-palette/store";
import { relativeDay } from "../shared/dates";
import { MemberDetail } from "./member-detail";
import { useActionErrorMessage } from "./use-action-error";
import { InvitationLedger, InviteMemberDialog } from "./member-invitation";
import {
  INVITE_KIND,
  MEMBER_STATUSES,
  NO_ACTION,
  actionFilterValues,
  actionRoleLabels,
  familyNameKey,
  globalRoleLabels,
  knownActions,
  loadMemberDirectory,
  memberStatusLabels,
  memberStatusShapes,
  membersPath,
  migrateLegacyInviteParam,
  roleFilterOptions,
  roleFilterValues,
  type MemberRow,
} from "./member-model";

export interface MemberAdministrationPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

export type MemberSection = "list" | "invitations";

/** `/admin/members` or `/admin/members/invitations`. */
export function memberSection(pathname: string): MemberSection {
  return pathname.replace(/\/+$/, "").endsWith("/members/invitations")
    ? "invitations"
    : "list";
}

function SubNav({ current }: { readonly current: MemberSection }) {
  const links: readonly [MemberSection, string][] = [
    ["list", "Mitglieder"],
    ["invitations", "Einladungen"],
  ];
  return (
    <nav aria-label="Mitgliederbereiche" className="section-links">
      {links.map(([section, label]) => (
        <a
          aria-current={current === section ? "page" : undefined}
          data-testid={`member-section-${section}`}
          href={membersPath(section)}
          key={section}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

export function MemberAdministrationPage({
  client,
  identity,
}: MemberAdministrationPageProps) {
  const [section] = useState(() => memberSection(window.location.pathname));
  // Old `?view=invite` links open the dialog, before the list reads ?view=.
  const [inviting, setInviting] = useState(() => {
    migrateLegacyInviteParam();
    return consumeCreateRequest(INVITE_KIND);
  });
  const openInvite = useCallback(() => setInviting(true), []);

  useContextCommands(
    useMemo(
      () =>
        section === "list"
          ? [
              {
                id: "members:section:invitations",
                label: "Einladungen ansehen",
                group: "Mitglieder",
                icon: MailPlus,
                run: () => window.location.assign(membersPath("invitations")),
              },
            ]
          : [
              {
                id: "members:section:list",
                label: "Mitglieder ansehen",
                group: "Mitglieder",
                icon: Users,
                run: () => window.location.assign(membersPath("list")),
              },
              {
                id: "create:member-invitation",
                label: "Mitglied einladen",
                group: "Mitglieder",
                icon: MailPlus,
                run: openInvite,
              },
            ],
      [openInvite, section],
    ),
  );

  return (
    <div
      className={
        section === "list" ? "members-page" : "members-page members-ledger-page"
      }
      data-zone="members"
      // The list is full-bleed as in the prototype; Einladungen keeps the
      // shell's page frame.
      {...(section === "list" ? fullBleedPage : {})}
    >
      <div className="members-top">
        <SubNav current={section} />
      </div>
      {section === "list" ? (
        <MemberList client={client} identity={identity} onInvite={openInvite} />
      ) : (
        <InvitationLedger
          client={client}
          onInvite={openInvite}
          userId={identity.userId}
        />
      )}
      <InviteMemberDialog
        client={client}
        onClose={() => setInviting(false)}
        open={inviting}
        userId={identity.userId}
      />
    </div>
  );
}

function MemberStatusChip({ row }: { readonly row: MemberRow }) {
  return (
    <StatusLabel
      shape={memberStatusShapes[row.status]}
      status={memberStatusLabels[row.status]}
    />
  );
}

function RoleChips({ row }: { readonly row: MemberRow }) {
  const roles = [
    ...row.globalRoles.map((role) => ({
      key: `global:${role}`,
      label: globalRoleLabels[role],
      tone: "accent" as const,
    })),
    ...[...new Set(row.actionMemberships.map((item) => item.role))].map(
      (role) => ({
        key: `action:${role}`,
        label: actionRoleLabels[role],
        tone: "zone" as const,
      }),
    ),
  ].slice(0, 2);
  if (!roles.length) return null;
  return (
    <span className="role-chips">
      {roles.map((role) => (
        <Badge key={role.key} tone={role.tone}>
          {role.label}
        </Badge>
      ))}
    </span>
  );
}

function MemberList({
  client,
  identity,
  onInvite,
}: {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly onInvite: () => void;
}) {
  const directory = useQuery({
    queryFn: ({ signal }) => loadMemberDirectory(client, signal),
    queryKey: ["members", "directory"],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    staleTime: 10_000,
  });
  const directoryError = useActionErrorMessage(directory.error);
  const rows = directory.data?.items ?? [];
  const actions = useMemo(
    () => directory.data?.actions ?? [],
    [directory.data?.actions],
  );
  const actionOptions = useMemo(
    () => knownActions(actions, directory.data?.items ?? []),
    [actions, directory.data?.items],
  );

  const properties = useMemo<ListProperty<MemberRow>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: MEMBER_STATUSES.map((value) => ({
          value,
          label: memberStatusLabels[value],
          icon: (
            <StatusIcon
              label={memberStatusLabels[value]}
              status={memberStatusShapes[value]}
            />
          ),
        })),
        chip: (row) => <MemberStatusChip row={row} />,
      },
      {
        id: "campaign",
        label: "Aktion",
        icon: Flag,
        get: actionFilterValues,
        options: [
          ...actionOptions.map((action) => ({
            value: action.actionId,
            label: action.actionName,
          })),
          { value: NO_ACTION, label: "Ohne Aktion" },
        ],
      },
      {
        id: "role",
        label: "Rolle",
        icon: Users,
        get: roleFilterValues,
        options: roleFilterOptions,
        chip: (row) => <RoleChips row={row} />,
        groupable: false,
      },
    ],
    [actionOptions],
  );

  const sorts = useMemo<ListSort<MemberRow>[]>(
    () => [
      {
        id: "name",
        label: "Name A–Z",
        compare: (a, b) =>
          familyNameKey(a.displayName).localeCompare(
            familyNameKey(b.displayName),
            "de",
          ),
      },
      {
        id: "seen",
        label: "Zuletzt aktiv",
        compare: (a, b) =>
          (b.lastLoginAt ?? "").localeCompare(a.lastLoginAt ?? ""),
      },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      { id: "all", label: "Alle", filters: [], groupBy: null, sort: "name" },
      {
        id: "invited",
        label: "Eingeladen",
        filters: [{ prop: "status", values: ["invited"] }],
        groupBy: null,
        sort: "name",
      },
      {
        id: "blocked",
        label: "Gesperrt",
        filters: [{ prop: "status", values: ["suspended"] }],
        groupBy: null,
        sort: "name",
      },
      {
        id: "archived",
        label: "Archiviert",
        filters: [{ prop: "status", values: ["archived"] }],
        groupBy: null,
        sort: "name",
      },
    ],
    [],
  );

  const columns = useMemo<ListColumns<MemberRow>>(
    () => ({
      leading: (row) => <Avatar name={row.displayName} />,
      primary: (row) => (
        <span data-member-row={row.userId}>{row.displayName}</span>
      ),
      secondary: (row) => row.email,
      trailing: (row) => (row.lastLoginAt ? relativeDay(row.lastLoginAt) : "–"),
    }),
    [],
  );

  const getId = useCallback((row: MemberRow) => row.userId, []);
  const searchText = useCallback(
    (row: MemberRow) => `${row.displayName} ${row.email}`,
    [],
  );
  const detailTitle = useCallback((row: MemberRow) => row.displayName, []);

  if (directory.isError && directory.error instanceof ApiError) {
    // No access (403) or another server answer: not a connection problem.
    return (
      <div className="members-state">
        <header className="page-header">
          <div className="page-heading">
            <h1>Mitglieder</h1>
          </div>
        </header>
        <ErrorState
          onRetry={() => void directory.refetch()}
          title="Mitglieder konnten nicht geladen werden"
        >
          {directoryError?.message}
        </ErrorState>
      </div>
    );
  }

  const partial = Boolean(directory.data?.partial);
  const truncated = Boolean(directory.data?.truncated);

  return (
    <ListView<MemberRow>
      beforeList={
        partial || truncated ? (
          <div className="members-notes">
            {partial ? (
              <div
                className="callout"
                data-testid="member-scope-note"
                role="note"
              >
                <Icon icon={Info} size={16} />
                <span>
                  <strong>Ansicht Ihrer Aktionen.</strong> Sichtbar sind nur
                  Mitglieder und Rollen aus Charity-Aktionen, die Sie selbst
                  verwalten.
                </span>
              </div>
            ) : null}
            {truncated ? (
              <div className="callout tone-warn" role="status">
                <Icon icon={Info} size={16} />
                <span>
                  Die Liste zeigt die ersten {rows.length} Mitglieder. Weitere
                  Mitglieder lädt sie nicht.
                </span>
              </div>
            ) : null}
          </div>
        ) : undefined
      }
      className="members-list"
      columns={columns}
      createCommandId={`create:${INVITE_KIND}`}
      createLabel="Mitglied einladen"
      detailTitle={detailTitle}
      emptyIcon={Users}
      entityLabel={{ one: "Mitglied", many: "Mitglieder" }}
      getId={getId}
      id="members"
      onCreate={onInvite}
      onRetry={() => void directory.refetch()}
      properties={properties}
      renderDetail={(row) => (
        <MemberDetail
          actions={actions}
          allRows={rows}
          client={client}
          identity={identity}
          key={row.userId}
          partial={partial}
          row={row}
        />
      )}
      rows={rows}
      searchText={searchText}
      sorts={sorts}
      status={
        directory.isPending ? "loading" : directory.isError ? "error" : "ready"
      }
      title="Mitglieder"
      useCommands={useContextCommands}
      views={views}
    />
  );
}
