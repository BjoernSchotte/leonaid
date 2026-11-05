import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, MailPlus, PenLine, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import {
  ApiError,
  type CreateInvitationRequest,
  type InvitationSummaryResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  Select,
  SkeletonRows,
  StatusLabel,
  StatusMessage,
  useOptionalToast,
  type StatusShape,
} from "@leonaid/ui";

import { createHref } from "../command-palette/create-request";
import { formatDateTime } from "../shared/dates";
import { actionErrorMessage, type ActionErrorMessage } from "./errors";
import {
  needsFreshLogin,
  saveFreshLoginDraft,
  takeFreshLoginDraft,
} from "./fresh-login-draft";
import { saveInviteDraft, takeInviteDraft } from "./invite-draft";
import {
  EMAIL,
  INVALID_EMAIL,
  INVITE_KIND,
  actionRoleLabels,
} from "./member-model";
import { useActionErrorMessage } from "./use-action-error";

type InvitationRole = CreateInvitationRequest["role"];
type InvitationStatus = InvitationSummaryResponse["status"];

const retryUnlessApiError = (failureCount: number, error: unknown) =>
  !(error instanceof ApiError) && failureCount < 2;

interface DraftErrors {
  readonly email?: string;
  readonly displayName?: string;
}

/**
 * "Mitglied einladen" (prototype InviteModal). The server lists the actions
 * and roles this account may invite into and authorizes the request again.
 */
export function InviteMemberDialog({
  client,
  onClose,
  open,
  userId,
}: {
  readonly client: LeonAidApiClient;
  readonly onClose: () => void;
  readonly open: boolean;
  /** The signed-in account; a stored draft belongs to it. */
  readonly userId: string;
}) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const formId = useId();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [actionId, setActionId] = useState("");
  const [role, setRole] = useState<InvitationRole | "">("");
  const [errors, setErrors] = useState<DraftErrors>({});
  const options = useQuery({
    enabled: open,
    queryFn: () => client.getInvitationOptions(),
    queryKey: ["invitation-options"],
    retry: retryUnlessApiError,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 30_000,
  });
  const [submitError, setSubmitError] = useState<ActionErrorMessage | null>(
    null,
  );
  const optionsError = useActionErrorMessage(options.error);
  const invite = useMutation({
    mutationFn: (request: CreateInvitationRequest) =>
      client.createInvitation(request),
    onError: (error, request) => {
      const fresh =
        error instanceof ApiError &&
        error.detail.code === "fresh_login_required";
      if (fresh) saveInviteDraft(userId, request);
      // After the fresh sign-in the dialog opens again with the draft.
      setSubmitError(
        actionErrorMessage(
          error,
          fresh
            ? {
                returnTo: createHref(
                  `${window.location.pathname}${window.location.search}`,
                  INVITE_KIND,
                ),
              }
            : {},
        ),
      );
    },
    onSuccess: (_result, request) => {
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
      // The invited person is listed as "Eingeladen" right away.
      void queryClient.invalidateQueries({ queryKey: ["members"] });
      toast?.show({
        title: `Einladung an ${request.email} gesendet.`,
        description:
          "Das Mitglied erhält einen Magic Link und einen sechsstelligen Code.",
        tone: "success",
      });
      close();
    },
  });

  useEffect(() => {
    if (!open) return;
    const draft = takeInviteDraft(userId);
    if (!draft) return;
    setEmail(draft.email);
    setDisplayName(draft.displayName);
    if (draft.actionId) setActionId(draft.actionId);
    if (draft.role) setRole(draft.role);
  }, [open, userId]);

  useEffect(() => {
    if (!options.data) return;
    setActionId((current) =>
      options.data.actions.some((action) => action.id === current)
        ? current
        : (options.data.actions[0]?.id ?? ""),
    );
    setRole((current) =>
      options.data.roles.some((item) => item.value === current)
        ? current
        : (options.data.roles[0]?.value ?? ""),
    );
  }, [options.data]);

  function close() {
    setEmail("");
    setDisplayName("");
    setErrors({});
    setSubmitError(null);
    invite.reset();
    onClose();
  }

  const canInvite =
    Boolean(options.data?.actions.length) &&
    Boolean(options.data?.roles.length);

  return (
    <Modal
      description="Die Person bekommt einen Link und einen Code per E-Mail."
      footer={
        <>
          <Button disabled={invite.isPending} onClick={close} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="invite-submit"
            disabled={!canInvite}
            form={formId}
            icon={Mail}
            loading={invite.isPending}
            type="submit"
          >
            Einladung senden
          </Button>
        </>
      }
      onClose={() => {
        if (!invite.isPending) close();
      }}
      open={open}
      title="Mitglied einladen"
    >
      {options.isPending ? (
        <SkeletonRows rows={3} />
      ) : options.isError ? (
        <StatusMessage tone="error">
          <strong>Einladung konnte nicht vorbereitet werden</strong>
          <p>{optionsError?.message}</p>
          <Button onClick={() => void options.refetch()} variant="secondary">
            Erneut versuchen
          </Button>
        </StatusMessage>
      ) : (
        <form
          className="stack"
          id={formId}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            const next: DraftErrors = {
              email: EMAIL.test(email.trim()) ? undefined : INVALID_EMAIL,
              displayName: displayName.trim()
                ? undefined
                : "Bitte den Namen des Mitglieds eingeben.",
            };
            setErrors(next);
            if (next.email || next.displayName || !actionId || !role) return;
            setSubmitError(null);
            invite.mutate({
              actionId,
              displayName: displayName.trim(),
              email: email.trim(),
              role,
            });
          }}
        >
          <fieldset className="stack" disabled={!canInvite || invite.isPending}>
            <legend className="sr-only">Einladung</legend>
            <Field error={errors.email} label="E-Mail-Adresse">
              <Input
                autoComplete="off"
                autoFocus
                onChange={(event) => {
                  setEmail(event.target.value);
                  setErrors((current) => ({ ...current, email: undefined }));
                }}
                type="email"
                value={email}
              />
            </Field>
            <Field error={errors.displayName} label="Name">
              <Input
                autoComplete="off"
                maxLength={160}
                onChange={(event) => {
                  setDisplayName(event.target.value);
                  setErrors((current) => ({
                    ...current,
                    displayName: undefined,
                  }));
                }}
                value={displayName}
              />
            </Field>
            <Field label="Aktion">
              <Select
                data-testid="invite-action"
                onChange={(event) => setActionId(event.target.value)}
                value={actionId}
              >
                {options.data.actions.map((action) => (
                  <option key={action.id} value={action.id}>
                    {action.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              hint="Sie sehen nur Aktionen und Rollen, die Sie vergeben dürfen."
              label="Rolle in dieser Aktion"
            >
              <Select
                data-testid="invite-role"
                onChange={(event) =>
                  setRole(event.target.value as InvitationRole)
                }
                value={role}
              >
                {options.data.roles.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </Field>
          </fieldset>
          {!canInvite ? (
            <StatusMessage tone="error">
              Sie verwalten derzeit keine Aktion, in die Sie ein Mitglied
              einladen dürfen.
            </StatusMessage>
          ) : null}
          {submitError ? (
            <StatusMessage id="invitation-status" tone="error">
              {submitError.message}
            </StatusMessage>
          ) : null}
        </form>
      )}
    </Modal>
  );
}

const statusLabels: Readonly<Record<InvitationStatus, string>> = {
  pending: "Offen",
  accepted: "Angenommen",
  expired: "Abgelaufen",
  revoked: "Widerrufen",
};

const statusShapes: Readonly<Record<InvitationStatus, StatusShape>> = {
  pending: "open",
  accepted: "done",
  expired: "alert",
  revoked: "cancelled",
};

const statusFilters: ReadonlyArray<{
  readonly label: string;
  readonly value: InvitationStatus | "";
}> = [
  { label: "Alle", value: "" },
  { label: "Offen", value: "pending" },
  { label: "Angenommen", value: "accepted" },
  { label: "Abgelaufen", value: "expired" },
  { label: "Widerrufen", value: "revoked" },
];

/** "Einladungen": every invitation of the actions this account manages. */
export function InvitationLedger({
  client,
  onInvite,
  userId,
}: {
  readonly client: LeonAidApiClient;
  readonly onInvite: () => void;
  /** The signed-in account; a stored address draft belongs to it. */
  readonly userId: string;
}) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const [statusFilter, setStatusFilter] = useState<InvitationStatus | "">("");
  const [correction, setCorrection] = useState<{
    readonly invitation: InvitationSummaryResponse;
    readonly email: string;
  }>();
  const [revokeCandidate, setRevokeCandidate] =
    useState<InvitationSummaryResponse>();
  const invitations = useQuery({
    queryFn: () =>
      client.listInvitations(statusFilter ? { status: statusFilter } : {}),
    queryKey: ["invitations", statusFilter],
    retry: retryUnlessApiError,
    staleTime: 10_000,
  });
  const done = (title: string) => {
    void queryClient.invalidateQueries({ queryKey: ["invitations"] });
    toast?.show({ title, tone: "success" });
  };
  const failed = (error: unknown) =>
    toast?.show({
      title: "Die Einladung wurde nicht geändert.",
      description: actionErrorMessage(error).message,
      tone: "error",
    });
  const resend = useMutation({
    mutationFn: (invitationId: string) => client.resendInvitation(invitationId),
    onSuccess: () =>
      done(
        "Eine neue Einladung wurde versendet. Der bisherige Link ist jetzt ungültig.",
      ),
    onError: failed,
  });
  const revoke = useMutation({
    mutationFn: (invitationId: string) => client.revokeInvitation(invitationId),
    onSuccess: () => {
      setRevokeCandidate(undefined);
      done("Die offene Einladung wurde widerrufen.");
    },
    onError: (error) => {
      setRevokeCandidate(undefined);
      failed(error);
    },
  });
  const correctAddress = useMutation({
    mutationFn: ({
      email,
      invitationId,
    }: {
      readonly email: string;
      readonly invitationId: string;
    }) => client.correctInvitationAddress(invitationId, { email }),
    onError: (error, { email, invitationId }) => {
      // The fresh sign-in reloads the page: keep the typed address.
      if (needsFreshLogin(error)) {
        saveFreshLoginDraft(
          `invitation-address:${invitationId}`,
          userId,
          email,
        );
      }
    },
    onSuccess: () => {
      setCorrection(undefined);
      done(
        "Die alte Einladung wurde widerrufen und eine neue an die korrigierte Adresse versendet.",
      );
    },
  });
  // Back from the fresh sign-in: reopen the correction with the typed
  // address once the invitation is listed again.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !invitations.data) return;
    restored.current = true;
    for (const invitation of invitations.data.items) {
      const draft = takeFreshLoginDraft(
        `invitation-address:${invitation.id}`,
        userId,
      );
      if (draft !== null) {
        setCorrection({ invitation, email: draft });
        return;
      }
    }
  }, [invitations.data, userId]);
  const correctionFormId = useId();
  const [correctionInvalid, setCorrectionInvalid] = useState(false);
  const correctionError = useActionErrorMessage(correctAddress.error);
  const invitationsError = useActionErrorMessage(invitations.error);
  const items = invitations.data?.items ?? [];

  return (
    <div className="members-ledger">
      <header className="page-header">
        <div className="page-heading">
          <h1>Einladungen</h1>
          {invitations.isSuccess ? (
            <span className="page-count num" data-testid="invitations-count">
              {items.length} {items.length === 1 ? "Einladung" : "Einladungen"}
            </span>
          ) : null}
        </div>
        <div className="page-actions">
          <label className="members-filter">
            <span className="small">Status</span>
            <Select
              data-testid="invitation-status-filter"
              onChange={(event) =>
                setStatusFilter(event.target.value as InvitationStatus | "")
              }
              value={statusFilter}
            >
              {statusFilters.map((item) => (
                <option key={item.value || "all"} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </label>
          <Button icon={MailPlus} onClick={onInvite}>
            Mitglied einladen
          </Button>
        </div>
      </header>
      <p className="small muted members-ledger-note">
        Offene Einladungen können Sie erneut senden, korrigieren oder
        widerrufen. Abgeschlossene Einträge bleiben als Verlauf erhalten.
      </p>
      {invitations.isPending ? (
        <SkeletonRows rows={5} />
      ) : invitations.isError ? (
        <ErrorState
          onRetry={() => void invitations.refetch()}
          title="Die Einladungen konnten nicht geladen werden"
        >
          {invitationsError?.message}
        </ErrorState>
      ) : items.length === 0 ? (
        <EmptyState
          description="Wechseln Sie den Statusfilter oder laden Sie das erste Mitglied ein."
          headingLevel={2}
          icon={MailPlus}
          title="Keine Einladungen in dieser Ansicht"
        />
      ) : (
        <div
          aria-label="Einladungen"
          className="table-wrap"
          role="region"
          tabIndex={0}
        >
          <table className="table" data-testid="invitations-table">
            <caption className="sr-only">Einladungen</caption>
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Aktion</th>
                <th scope="col">Rolle</th>
                <th scope="col">Status</th>
                <th scope="col">Gültig bis / Versendet</th>
                <th scope="col">
                  <span className="sr-only">Befehle</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((invitation) => {
                const pending = invitation.status === "pending";
                return (
                  <tr
                    className="invitation-row"
                    data-status={invitation.status}
                    data-testid={`invitation-${invitation.id}`}
                    key={invitation.id}
                  >
                    <td>
                      <span className="invitation-person">
                        <strong>{invitation.displayName}</strong>
                        <span className="subtle">{invitation.email}</span>
                      </span>
                    </td>
                    <td>{invitation.actionName}</td>
                    <td>{actionRoleLabels[invitation.role]}</td>
                    <td>
                      <StatusLabel
                        shape={statusShapes[invitation.status]}
                        status={statusLabels[invitation.status]}
                      />
                    </td>
                    <td className="num invitation-date">
                      {formatDateTime(
                        pending ? invitation.expiresAt : invitation.createdAt,
                      )}
                    </td>
                    <td>
                      {pending ? (
                        <span className="invitation-commands">
                          <Button
                            data-testid="invitation-resend"
                            icon={RefreshCw}
                            loading={
                              resend.isPending &&
                              resend.variables === invitation.id
                            }
                            onClick={() => resend.mutate(invitation.id)}
                            size="sm"
                            variant="secondary"
                          >
                            Erneut senden
                          </Button>
                          <Button
                            data-testid="invitation-correct-address"
                            icon={PenLine}
                            onClick={() => {
                              correctAddress.reset();
                              setCorrection({
                                invitation,
                                email: invitation.email,
                              });
                            }}
                            size="sm"
                            variant="ghost"
                          >
                            Adresse korrigieren
                          </Button>
                          <Button
                            data-testid="invitation-revoke"
                            icon={Trash2}
                            onClick={() => setRevokeCandidate(invitation)}
                            size="sm"
                            variant="ghost"
                          >
                            Widerrufen
                          </Button>
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        description="Die bisherige Einladung wird widerrufen; ihr Verlauf bleibt erhalten. Magic Link und Code gehen an die neue Adresse."
        footer={
          <>
            <Button
              disabled={correctAddress.isPending}
              onClick={() => setCorrection(undefined)}
              variant="ghost"
            >
              Abbrechen
            </Button>
            <Button
              form={correctionFormId}
              icon={Mail}
              loading={correctAddress.isPending}
              type="submit"
            >
              Korrigieren & senden
            </Button>
          </>
        }
        onClose={() => {
          if (!correctAddress.isPending) setCorrection(undefined);
        }}
        open={Boolean(correction)}
        size="sm"
        title="Adresse korrigieren"
      >
        {correction ? (
          <form
            className="stack"
            id={correctionFormId}
            // The Field shows the error; no native validation bubble.
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              if (!EMAIL.test(correction.email.trim())) {
                setCorrectionInvalid(true);
                return;
              }
              setCorrectionInvalid(false);
              correctAddress.mutate({
                email: correction.email.trim(),
                invitationId: correction.invitation.id,
              });
            }}
          >
            <Field
              error={
                correctionInvalid ? INVALID_EMAIL : correctionError?.message
              }
              label="Neue Login-E-Mail"
              required
            >
              <Input
                autoComplete="email"
                autoFocus
                onChange={(event) =>
                  setCorrection({ ...correction, email: event.target.value })
                }
                type="email"
                value={correction.email}
              />
            </Field>
          </form>
        ) : null}
      </Modal>
      <ConfirmDialog
        confirmLabel="Jetzt widerrufen"
        description={
          revokeCandidate
            ? `Die Einladung an ${revokeCandidate.email} wird widerrufen. Magic Link und Code funktionieren danach sofort nicht mehr.`
            : ""
        }
        onConfirm={() => {
          if (revokeCandidate) revoke.mutate(revokeCandidate.id);
        }}
        onOpenChange={(open) => {
          if (!open && !revoke.isPending) setRevokeCandidate(undefined);
        }}
        open={Boolean(revokeCandidate)}
        pending={revoke.isPending}
        title="Einladung wirklich widerrufen?"
        tone="danger"
      />
    </div>
  );
}
