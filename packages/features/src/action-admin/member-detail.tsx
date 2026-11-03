import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock,
  KeyRound,
  Lock,
  Mail,
  MailWarning,
  Plus,
  ShieldAlert,
  Trash2,
  UserCheck,
} from "lucide-react";
import { useId, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type MemberDirectoryActionResponse,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  ConfirmDialog,
  DetailProps,
  DetailSection,
  Field,
  Icon,
  Input,
  Modal,
  StatusLabel,
  StatusMessage,
  useOptionalToast,
} from "@leonaid/ui";

import { formatDateTime, relativeDay } from "../invoices/invoice-format";
import { actionErrorMessage, type ActionErrorMessage } from "./errors";
import {
  GLOBAL_ROLES,
  actionRoleLabels,
  globalRoleDescriptions,
  globalRoleLabels,
  memberStatusLabels,
  memberStatusShapes,
  membersPath,
  type ActionRole,
  type GlobalRole,
  type MemberRow,
} from "./member-model";

type AccessStatus = "active" | "suspended" | "archived";

type RoleCommand =
  | {
      readonly scope: "global";
      readonly role: GlobalRole;
      readonly enabled: boolean;
    }
  | {
      readonly scope: "action";
      readonly actionId: string;
      readonly actionName: string;
      readonly role: ActionRole;
      readonly enabled: boolean;
    };

function roleLabel(command: RoleCommand): string {
  return command.scope === "global"
    ? globalRoleLabels[command.role]
    : actionRoleLabels[command.role];
}

function sessionText(count: number): string {
  if (count === 0) return "Keine aktiven Sitzungen.";
  return count === 1 ? "1 aktive Sitzung" : `${count} aktive Sitzungen`;
}

/** Error block with "Aktuellen Stand laden" for a revision conflict. */
function CommandError({
  error,
  onReload,
  title,
}: {
  readonly error: ActionErrorMessage;
  readonly onReload: () => void;
  readonly title: string;
}) {
  return (
    <StatusMessage tone="error">
      <strong>
        {error.conflict ? "Stand wurde zwischenzeitlich geändert" : title}
      </strong>
      <p>{error.message}</p>
      {error.conflict ? (
        <Button onClick={onReload} size="sm" variant="secondary">
          Aktuellen Stand laden
        </Button>
      ) : null}
    </StatusMessage>
  );
}

/**
 * Pane body of one member (prototype MemberDetail). Every change goes to the
 * server with the revision it was based on. Role and access changes need a
 * freshly confirmed sign-in: the server answers `fresh_login_required`, and
 * actionErrorMessage sends the person to /fresh-login, which returns to this
 * URL (`?open=<id>` reopens the pane). Nothing is applied without the server.
 */
export function MemberDetail({
  actions,
  allRows,
  client,
  identity,
  partial,
  row,
}: {
  /** Actions this account may manage, with the roles it may assign there. */
  readonly actions: readonly MemberDirectoryActionResponse[];
  readonly allRows: readonly MemberRow[];
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly partial: boolean;
  readonly row: MemberRow;
}) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const emailFormId = useId();
  const [pendingRole, setPendingRole] = useState<{
    readonly command: RoleCommand;
    readonly key: string;
  }>();
  const [roleError, setRoleError] = useState<ActionErrorMessage>();
  const [pendingStatus, setPendingStatus] = useState<{
    readonly status: AccessStatus;
    readonly key: string;
  }>();
  const [statusError, setStatusError] = useState<ActionErrorMessage>();
  const [emailOpen, setEmailOpen] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [requestedEmail, setRequestedEmail] = useState("");
  const [addActionId, setAddActionId] = useState(
    () => actions[0]?.actionId ?? "",
  );
  const [addActionRole, setAddActionRole] = useState<ActionRole | "">("");
  const [addGlobalRole, setAddGlobalRole] = useState<GlobalRole | "">("");

  // The pane shows the row at once and refreshes it: commands need the
  // current revision.
  const detail = useQuery({
    placeholderData: row,
    queryFn: () => client.getMember(row.userId),
    queryKey: ["member-detail", row.userId],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    staleTime: 15_000,
  });

  const refresh = async (userId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["members"] }),
      queryClient.invalidateQueries({ queryKey: ["member-detail", userId] }),
    ]);
  };

  const roleChange = useMutation({
    mutationFn: ({
      command,
      key,
      member,
    }: {
      readonly command: RoleCommand;
      readonly key: string;
      readonly member: MemberRow;
    }) => {
      const body = {
        enabled: command.enabled,
        expectedRevision: member.revision,
      };
      const options = { headers: { "Idempotency-Key": key } };
      return command.scope === "global"
        ? client.changeMemberGlobalRole(
            member.userId,
            command.role,
            body,
            options,
          )
        : client.changeMemberActionRole(
            member.userId,
            command.actionId,
            command.role,
            body,
            options,
          );
    },
    onSuccess: async (result) => {
      setPendingRole(undefined);
      toast?.show({
        title: `${result.roleLabel} wurde ${
          result.enabled ? "zugewiesen" : "entzogen"
        }${result.actionName ? ` · ${result.actionName}` : ""}.`,
        description: "Die Änderung wirkt ab der nächsten Anfrage.",
        tone: "success",
      });
      await Promise.all([
        refresh(result.userId),
        queryClient.invalidateQueries({ queryKey: ["identity"] }),
      ]);
    },
    onError: (error) => {
      setPendingRole(undefined);
      // Redirects to /fresh-login when the server asks for it.
      setRoleError(actionErrorMessage(error));
    },
  });

  const statusChange = useMutation({
    mutationFn: ({
      key,
      member,
      status,
    }: {
      readonly key: string;
      readonly member: MemberRow;
      readonly status: AccessStatus;
    }) =>
      client.changeMemberStatus(
        member.userId,
        { expectedRevision: member.revision, status },
        { headers: { "Idempotency-Key": key } },
      ),
    onSuccess: async (result) => {
      setPendingStatus(undefined);
      toast?.show({
        title:
          result.status === "suspended"
            ? `${result.displayName} ist gesperrt.`
            : result.status === "active"
              ? `${result.displayName} ist wieder aktiv.`
              : `${result.displayName} ist archiviert.`,
        description:
          result.status === "suspended"
            ? `${result.revokedSessionCount} ${
                result.revokedSessionCount === 1
                  ? "Sitzung wurde"
                  : "Sitzungen wurden"
              } sofort beendet.`
            : result.status === "active"
              ? "Für den nächsten Zugriff ist eine neue Anmeldung erforderlich."
              : "Historische Zuordnungen und Dokumente bleiben erhalten.",
        tone: "success",
      });
      await refresh(result.userId);
    },
    onError: (error) => {
      setPendingStatus(undefined);
      setStatusError(actionErrorMessage(error));
    },
  });

  const emailChange = useMutation({
    mutationFn: ({
      email,
      userId,
    }: {
      readonly email: string;
      readonly userId: string;
    }) => client.createMemberEmailChange(userId, { newEmail: email }),
    onSuccess: (_result, { email }) => {
      setEmailOpen(false);
      setRequestedEmail(email);
      toast?.show({
        title: "Bestätigung an die neue Adresse gesendet.",
        tone: "success",
      });
    },
  });

  if (detail.isError && !detail.data) {
    return (
      <div className="member-detail" data-testid="member-detail">
        <StatusMessage tone="error">
          <strong>Details nicht erreichbar</strong>
          <p>{actionErrorMessage(detail.error).message}</p>
          <Button
            onClick={() => void detail.refetch()}
            size="sm"
            variant="secondary"
          >
            Erneut versuchen
          </Button>
        </StatusMessage>
      </div>
    );
  }

  const member = detail.data ?? row;
  const reload = () => {
    setRoleError(undefined);
    setStatusError(undefined);
    void refresh(member.userId);
  };
  const systemAdmin = identity.globalRoles.includes("system_admin");
  const self = member.userId === identity.userId;
  const archived = member.status === "archived";
  const manageable = new Map(
    actions.map((action) => [action.actionId, action]),
  );
  const busy = roleChange.isPending || statusChange.isPending;

  const activeHolders = (matches: (other: MemberRow) => boolean) =>
    allRows.filter(
      (other) =>
        other.userId !== member.userId &&
        other.status === "active" &&
        matches(other),
    ).length;
  const lastSystemAdmin =
    !partial &&
    member.status === "active" &&
    member.globalRoles.includes("system_admin") &&
    activeHolders((other) => other.globalRoles.includes("system_admin")) === 0;
  const isLastLead = (actionId: string) =>
    member.status === "active" &&
    activeHolders((other) =>
      other.actionMemberships.some(
        (item) => item.actionId === actionId && item.role === "charity_admin",
      ),
    ) === 0;

  function askRole(command: RoleCommand) {
    setRoleError(undefined);
    roleChange.reset();
    setPendingRole({
      command,
      key: `pilot012:member-role:${crypto.randomUUID()}`,
    });
  }

  function askStatus(status: AccessStatus) {
    setStatusError(undefined);
    statusChange.reset();
    setPendingStatus({
      status,
      key: `pilot011:member-status:${crypto.randomUUID()}`,
    });
  }

  function revokeActionRole(
    actionId: string,
    actionName: string,
    role: ActionRole,
  ) {
    if (role === "charity_admin" && isLastLead(actionId)) {
      toast?.show({
        title: `${member.displayName} ist die letzte Aktionsleitung von ${actionName}.`,
        description: "Bitte zuerst eine Vertretung als Charity-Admin ernennen.",
        tone: "error",
      });
      return;
    }
    askRole({ scope: "action", actionId, actionName, role, enabled: false });
  }

  const addAction = manageable.get(addActionId) ?? actions[0];
  const addActionRoles = (addAction?.availableRoles ?? []).filter(
    (role) =>
      !member.actionMemberships.some(
        (item) => item.actionId === addAction?.actionId && item.role === role,
      ),
  );
  const chosenActionRole =
    addActionRole && addActionRoles.includes(addActionRole)
      ? addActionRole
      : addActionRoles[0];
  const addGlobalRoles = GLOBAL_ROLES.filter(
    (role) => !member.globalRoles.includes(role),
  );
  const chosenGlobalRole =
    addGlobalRole && addGlobalRoles.includes(addGlobalRole)
      ? addGlobalRole
      : addGlobalRoles[0];

  const pendingCommand = pendingRole?.command;
  const pendingLabel = pendingCommand ? roleLabel(pendingCommand) : "";
  const roleDialogDescription = pendingCommand
    ? `${member.displayName} erhält ${
        pendingCommand.enabled ? "die Rolle" : "nicht mehr die Rolle"
      } „${pendingLabel}“${
        pendingCommand.scope === "action"
          ? ` in ${pendingCommand.actionName}`
          : " im gesamten Club"
      }. Die Änderung wirkt ab der nächsten Anfrage. Historische Fachzuordnungen bleiben erhalten.`
    : "";

  const statusDialog =
    pendingStatus?.status === "suspended"
      ? {
          title: "Zugang wirklich sperren?",
          confirm: "Zugang sperren",
          description: `${member.displayName} verliert sofort den Zugriff. ${
            member.activeSessionCount === 1
              ? "Die aktive Sitzung wird"
              : `${member.activeSessionCount} aktive Sitzungen werden`
          } unwiderruflich beendet.`,
        }
      : pendingStatus?.status === "active"
        ? {
            title: "Zugang reaktivieren?",
            confirm: "Zugang reaktivieren",
            description: `${member.displayName} erhält wieder Zugriff. Alte Sitzungen bleiben beendet; die Person muss sich neu anmelden.`,
          }
        : {
            title: "Zugang dauerhaft archivieren?",
            confirm: "Zugang archivieren",
            description: `${member.displayName} wird dauerhaft archiviert. Aktionszuordnungen, Audit-Verlauf, Rechnungen und Dokumente bleiben historisch erhalten.`,
          };

  const emailError = emailChange.error
    ? actionErrorMessage(emailChange.error)
    : null;
  const canManageAccess = systemAdmin && !partial;
  const globalRolesEditable = canManageAccess && !archived;

  return (
    <div
      className="member-detail"
      data-member-id={member.userId}
      data-testid="member-detail"
    >
      {member.status === "invited" ? (
        <div className="callout">
          <Icon icon={MailWarning} size={16} />
          <div className="stack">
            <span>
              Eingeladen. Der Zugang wird mit der Annahme der Einladung aktiv.
            </span>
            <a className="member-link" href={membersPath("invitations")}>
              Einladungen ansehen
            </a>
          </div>
        </div>
      ) : null}

      {requestedEmail ? (
        <div className="callout" data-testid="member-email-change-success">
          <Icon icon={Clock} size={16} />
          <span>
            Neue Anmeldeadresse <strong>{requestedEmail}</strong> wartet auf
            Bestätigung. Bis dahin gilt die bisherige Adresse weiter.
          </span>
        </div>
      ) : null}

      <DetailSection title="Person">
        <DetailProps
          items={[
            { label: "Name", value: member.displayName },
            {
              label: "Anmeldeadresse",
              value: (
                <a className="member-link" href={`mailto:${member.email}`}>
                  {member.email}
                </a>
              ),
            },
            {
              label: "Status",
              value: (
                <span data-testid="member-detail-status">
                  <StatusLabel
                    shape={memberStatusShapes[member.status]}
                    status={memberStatusLabels[member.status]}
                  />
                </span>
              ),
            },
            {
              label: "Zuletzt aktiv",
              value: member.lastLoginAt ? (
                <time
                  dateTime={member.lastLoginAt}
                  title={formatDateTime(member.lastLoginAt)}
                >
                  {relativeDay(member.lastLoginAt)}
                </time>
              ) : (
                "Noch nie angemeldet"
              ),
            },
            // System admins see and change them in "Systemrollen" below.
            ...(partial || globalRolesEditable
              ? []
              : [
                  {
                    label: "Systemrollen",
                    value: member.globalRoles.length ? (
                      <span className="cluster">
                        {member.globalRoles.map((role) => (
                          <Badge key={role} tone="accent">
                            {globalRoleLabels[role]}
                          </Badge>
                        ))}
                      </span>
                    ) : (
                      <span className="subtle">Keine</span>
                    ),
                  },
                ]),
          ]}
        />
      </DetailSection>

      <section
        aria-labelledby={`member-roles-${member.userId}`}
        className="pane-section"
        data-testid="member-role-admin"
      >
        <h3 id={`member-roles-${member.userId}`}>Rollen in Aktionen</h3>
        {!archived ? (
          <p className="small subtle member-hint">
            Änderungen brauchen eine frisch bestätigte Anmeldung und wirken ab
            der nächsten Anfrage.
          </p>
        ) : null}
        {roleError ? (
          <CommandError
            error={roleError}
            onReload={reload}
            title="Rolle konnte nicht geändert werden"
          />
        ) : null}
        {member.actionMemberships.length === 0 ? (
          <p className="small subtle">
            Derzeit keiner Charity-Aktion zugeordnet.
          </p>
        ) : (
          <ul className="role-list">
            {member.actionMemberships.map((item) => {
              const mayRevoke =
                !archived &&
                Boolean(
                  manageable
                    .get(item.actionId)
                    ?.availableRoles.includes(item.role),
                );
              return (
                <li
                  data-testid="member-membership"
                  key={`${item.actionId}:${item.role}`}
                >
                  <span className="role-name">
                    <strong>{item.roleLabel}</strong>
                    <span className="subtle">{item.actionName}</span>
                  </span>
                  {item.role === "charity_admin" &&
                  isLastLead(item.actionId) ? (
                    <Badge tone="warn">Letzte Aktionsleitung</Badge>
                  ) : null}
                  {mayRevoke ? (
                    <Button
                      aria-label={`${item.roleLabel} in ${item.actionName} entziehen`}
                      data-testid={`member-revoke-action-${item.actionId}-${item.role}`}
                      disabled={busy}
                      onClick={() =>
                        revokeActionRole(
                          item.actionId,
                          item.actionName,
                          item.role,
                        )
                      }
                      size="sm"
                      variant="ghost"
                    >
                      Entziehen
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        {!archived && actions.length > 0 ? (
          <form
            className="role-add"
            onSubmit={(event) => {
              event.preventDefault();
              if (!addAction || !chosenActionRole) return;
              askRole({
                scope: "action",
                actionId: addAction.actionId,
                actionName: addAction.actionName,
                role: chosenActionRole,
                enabled: true,
              });
            }}
          >
            <label
              className="sr-only"
              htmlFor={`role-add-action-${member.userId}`}
            >
              Aktion
            </label>
            <select
              className="input select"
              data-testid="member-role-add-action"
              id={`role-add-action-${member.userId}`}
              onChange={(event) => setAddActionId(event.target.value)}
              value={addAction?.actionId ?? ""}
            >
              {actions.map((action) => (
                <option key={action.actionId} value={action.actionId}>
                  {action.actionName}
                </option>
              ))}
            </select>
            <label
              className="sr-only"
              htmlFor={`role-add-role-${member.userId}`}
            >
              Rolle
            </label>
            <select
              className="input select"
              data-testid="member-role-add-role"
              disabled={addActionRoles.length === 0}
              id={`role-add-role-${member.userId}`}
              onChange={(event) =>
                setAddActionRole(event.target.value as ActionRole)
              }
              value={chosenActionRole ?? ""}
            >
              {addActionRoles.length === 0 ? (
                <option value="">Alle Rollen vergeben</option>
              ) : null}
              {addActionRoles.map((role) => (
                <option key={role} value={role}>
                  {actionRoleLabels[role]}
                </option>
              ))}
            </select>
            <Button
              data-testid="member-role-add-submit"
              disabled={addActionRoles.length === 0 || busy}
              icon={Plus}
              size="sm"
              type="submit"
              variant="secondary"
            >
              Rolle vergeben
            </Button>
          </form>
        ) : null}
      </section>

      {globalRolesEditable ? (
        <DetailSection title="Systemrollen">
          {member.globalRoles.length === 0 ? (
            <p className="small subtle">Keine Systemrollen.</p>
          ) : (
            <ul className="role-list">
              {member.globalRoles.map((role) => (
                <li data-testid="member-global-role" key={role}>
                  <span className="role-name">
                    <strong>{globalRoleLabels[role]}</strong>
                    <span className="subtle">
                      {globalRoleDescriptions[role]}
                    </span>
                  </span>
                  <Button
                    aria-label={`${globalRoleLabels[role]} entziehen`}
                    data-testid={`member-revoke-global-${role}`}
                    disabled={
                      busy || (role === "system_admin" && lastSystemAdmin)
                    }
                    onClick={() =>
                      askRole({ scope: "global", role, enabled: false })
                    }
                    size="sm"
                    variant="ghost"
                  >
                    Entziehen
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {lastSystemAdmin ? (
            <p className="member-guard small">
              <Icon icon={ShieldAlert} size={14} />
              Einzige aktive Systemverwaltung. Diese Rolle lässt sich erst
              entziehen, wenn eine zweite Person sie hat.
            </p>
          ) : null}
          {addGlobalRoles.length > 0 ? (
            <form
              className="role-add"
              onSubmit={(event) => {
                event.preventDefault();
                if (!chosenGlobalRole) return;
                askRole({
                  scope: "global",
                  role: chosenGlobalRole,
                  enabled: true,
                });
              }}
            >
              <label
                className="sr-only"
                htmlFor={`global-role-add-${member.userId}`}
              >
                Systemrolle
              </label>
              <select
                className="input select"
                data-testid="member-global-role-add"
                id={`global-role-add-${member.userId}`}
                onChange={(event) =>
                  setAddGlobalRole(event.target.value as GlobalRole)
                }
                value={chosenGlobalRole ?? ""}
              >
                {addGlobalRoles.map((role) => (
                  <option key={role} value={role}>
                    {globalRoleLabels[role]}
                  </option>
                ))}
              </select>
              <Button
                data-testid="member-global-role-add-submit"
                disabled={busy}
                icon={Plus}
                size="sm"
                type="submit"
                variant="secondary"
              >
                Rolle vergeben
              </Button>
            </form>
          ) : null}
        </DetailSection>
      ) : null}

      <DetailSection title="Sitzungen">
        <p className="small subtle" data-testid="member-sessions">
          {sessionText(member.activeSessionCount)}
        </p>
        {canManageAccess && member.status === "active" ? (
          <Button
            data-testid="member-email-change-open"
            icon={KeyRound}
            onClick={() => {
              emailChange.reset();
              setNewEmail(member.email);
              setEmailOpen(true);
            }}
            size="sm"
            variant="secondary"
          >
            Anmeldeadresse ändern
          </Button>
        ) : null}
      </DetailSection>

      {canManageAccess ? (
        <DetailSection title="Zugang">
          {statusError ? (
            <CommandError
              error={statusError}
              onReload={reload}
              title="Status konnte nicht geändert werden"
            />
          ) : null}
          {self ? (
            <p className="small subtle" data-testid="member-status-self">
              Ihren eigenen Zugang können Sie nicht sperren oder archivieren.
            </p>
          ) : member.status === "invited" ? (
            <p className="small subtle">
              Dieser Zugang wird durch die Annahme seiner Einladung aktiviert.
            </p>
          ) : archived ? (
            <p className="small subtle">
              Archivierte Zugänge bleiben als historischer Datensatz erhalten
              und können nicht reaktiviert werden.
            </p>
          ) : (
            <>
              <p className="small subtle member-hint">
                Kritische Änderungen brauchen eine frisch bestätigte Anmeldung
                und werden vollständig protokolliert.
              </p>
              <div className="cluster">
                {member.status === "active" ? (
                  <Button
                    data-testid="member-status-suspend"
                    disabled={busy}
                    icon={Lock}
                    onClick={() => askStatus("suspended")}
                    size="sm"
                    variant="secondary"
                  >
                    Zugang sperren
                  </Button>
                ) : (
                  <Button
                    data-testid="member-status-reactivate"
                    disabled={busy}
                    icon={UserCheck}
                    onClick={() => askStatus("active")}
                    size="sm"
                  >
                    Reaktivieren
                  </Button>
                )}
                <Button
                  data-testid="member-status-archive"
                  disabled={busy}
                  icon={Trash2}
                  onClick={() => askStatus("archived")}
                  size="sm"
                  variant="danger"
                >
                  Archivieren
                </Button>
              </div>
            </>
          )}
        </DetailSection>
      ) : null}

      {partial ? (
        <p className="small subtle" data-testid="member-scope-pane-note">
          Sie sehen ausschließlich Rollen in Ihren verwalteten Aktionen. Globale
          Rollen bleiben ausgeblendet.
        </p>
      ) : null}

      <ConfirmDialog
        confirmLabel={
          pendingCommand?.enabled ? "Rolle zuweisen" : "Rolle entziehen"
        }
        description={roleDialogDescription}
        onConfirm={() => {
          if (!pendingRole) return;
          roleChange.mutate({
            command: pendingRole.command,
            key: pendingRole.key,
            member,
          });
        }}
        onOpenChange={(open) => {
          if (!open && !roleChange.isPending) setPendingRole(undefined);
        }}
        open={Boolean(pendingRole)}
        pending={roleChange.isPending}
        title={
          pendingCommand?.enabled
            ? `${pendingLabel} zuweisen?`
            : `${pendingLabel} entziehen?`
        }
        tone={pendingCommand?.enabled ? "primary" : "danger"}
      />
      <ConfirmDialog
        confirmLabel={statusDialog.confirm}
        description={statusDialog.description}
        onConfirm={() => {
          if (!pendingStatus) return;
          statusChange.mutate({
            key: pendingStatus.key,
            member,
            status: pendingStatus.status,
          });
        }}
        onOpenChange={(open) => {
          if (!open && !statusChange.isPending) setPendingStatus(undefined);
        }}
        open={Boolean(pendingStatus)}
        pending={statusChange.isPending}
        title={statusDialog.title}
        tone={pendingStatus?.status === "active" ? "primary" : "danger"}
      />
      <Modal
        description="Die neue Adresse wird erst nach eigener Bestätigung aktiv. Danach enden alle bisherigen Sitzungen."
        footer={
          <>
            <Button
              disabled={emailChange.isPending}
              onClick={() => setEmailOpen(false)}
              variant="ghost"
            >
              Abbrechen
            </Button>
            <Button
              data-testid="member-email-change-submit"
              form={emailFormId}
              icon={Mail}
              loading={emailChange.isPending}
              type="submit"
            >
              Bestätigung senden
            </Button>
          </>
        }
        onClose={() => {
          if (!emailChange.isPending) setEmailOpen(false);
        }}
        open={emailOpen}
        size="sm"
        title="Anmeldeadresse ändern"
      >
        <form
          id={emailFormId}
          onSubmit={(event) => {
            event.preventDefault();
            if (!newEmail.trim()) return;
            emailChange.mutate({
              email: newEmail.trim(),
              userId: member.userId,
            });
          }}
        >
          <Field
            error={
              emailError
                ? `${
                    emailError.conflict
                      ? "E-Mail-Korrektur nicht möglich."
                      : "E-Mail-Korrektur fehlgeschlagen."
                  } ${emailError.message}`
                : undefined
            }
            hint="Magic Link und Code gehen an diese Adresse. Die bisherige Adresse erhält einen Sicherheitshinweis."
            label="Neue Login-E-Mail"
            required
          >
            <Input
              autoComplete="email"
              autoFocus
              data-testid="member-email-change-input"
              onChange={(event) => setNewEmail(event.target.value)}
              type="email"
              value={newEmail}
            />
          </Field>
        </form>
      </Modal>
    </div>
  );
}
