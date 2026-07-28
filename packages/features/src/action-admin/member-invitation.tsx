import {
  Delete02Icon,
  MailSend01Icon,
  NoteEditIcon,
  RefreshIcon,
  UserAdd01Icon,
  UserCheck01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  ApiError,
  type CreateInvitationRequest,
  type InvitationSummaryResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

export interface MemberInvitationPageProps {
  readonly client: LeonAidApiClient;
  readonly embedded?: boolean;
}

type InvitationRole = CreateInvitationRequest["role"];
type InvitationStatus = InvitationSummaryResponse["status"] | "";

interface InvitationDraft {
  readonly actionId: string;
  readonly displayName: string;
  readonly email: string;
  readonly role: InvitationRole | "";
}

const emptyDraft: InvitationDraft = {
  actionId: "",
  displayName: "",
  email: "",
  role: "",
};

const invitationStatuses: ReadonlyArray<{
  readonly label: string;
  readonly value: InvitationStatus;
}> = [
  { label: "Alle", value: "" },
  { label: "Offen", value: "pending" },
  { label: "Angenommen", value: "accepted" },
  { label: "Abgelaufen", value: "expired" },
  { label: "Widerrufen", value: "revoked" },
];

const statusLabels: Record<InvitationSummaryResponse["status"], string> = {
  accepted: "Angenommen",
  expired: "Abgelaufen",
  pending: "Offen",
  revoked: "Widerrufen",
};

const roleLabels: Record<InvitationSummaryResponse["role"], string> = {
  acquirer: "Akquisiteur",
  charity_admin: "Charity-Admin",
  driver: "Fahrer",
  finance_reader: "Finanz-Lesezugriff",
};

function localDate(value: string): string {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function MemberInvitationPage({
  client,
  embedded = false,
}: MemberInvitationPageProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<InvitationDraft>(emptyDraft);
  const [statusFilter, setStatusFilter] = useState<InvitationStatus>("");
  const [correction, setCorrection] = useState<{
    readonly id: string;
    readonly email: string;
  }>();
  const [revokeCandidate, setRevokeCandidate] =
    useState<InvitationSummaryResponse>();
  const [feedback, setFeedback] = useState<
    { readonly message: string; readonly tone: "error" | "success" } | undefined
  >();
  const options = useQuery({
    queryFn: () => client.getInvitationOptions(),
    queryKey: ["invitation-options"],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 30_000,
  });
  const invitations = useQuery({
    queryFn: () =>
      client.listInvitations(statusFilter ? { status: statusFilter } : {}),
    queryKey: ["invitations", statusFilter],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    staleTime: 10_000,
  });
  const mutation = useMutation({
    mutationFn: (request: CreateInvitationRequest) =>
      client.createInvitation(request),
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
      setDraft((current) => ({
        ...current,
        displayName: "",
        email: "",
      }));
      setFeedback({
        message:
          "Die Einladung ist unterwegs. Das Mitglied erhält einen Magic Link und einen sechsstelligen Code.",
        tone: "success",
      });
    },
    onError(error) {
      setFeedback({
        message: actionErrorMessage(error).message,
        tone: "error",
      });
    },
  });
  const resend = useMutation({
    mutationFn: (invitationId: string) => client.resendInvitation(invitationId),
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
      setFeedback({
        message:
          "Eine neue Einladung wurde versendet. Der bisherige Link ist jetzt ungültig.",
        tone: "success",
      });
    },
    onError(error) {
      setFeedback({
        message: actionErrorMessage(error).message,
        tone: "error",
      });
    },
  });
  const revoke = useMutation({
    mutationFn: (invitationId: string) => client.revokeInvitation(invitationId),
    onSuccess() {
      setRevokeCandidate(undefined);
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
      setFeedback({
        message: "Die offene Einladung wurde widerrufen.",
        tone: "success",
      });
    },
    onError(error) {
      setFeedback({
        message: actionErrorMessage(error).message,
        tone: "error",
      });
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
    onSuccess() {
      setCorrection(undefined);
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
      setFeedback({
        message:
          "Die alte Einladung wurde widerrufen und eine neue an die korrigierte Adresse versendet.",
        tone: "success",
      });
    },
    onError(error) {
      setFeedback({
        message: actionErrorMessage(error).message,
        tone: "error",
      });
    },
  });

  useEffect(() => {
    if (!options.data) return;
    setDraft((current) => ({
      ...current,
      actionId: current.actionId || options.data.actions[0]?.id || "",
      role: current.role || options.data.roles[0]?.value || "",
    }));
  }, [options.data]);

  if (options.isPending) {
    return (
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Einladung wird vorbereitet</h1>
        <p>Deine Aktionen und verfügbaren Rollen werden geladen.</p>
      </div>
    );
  }

  if (options.isError) {
    const details = actionErrorMessage(options.error);
    return (
      <div className="action-page action-page--state">
        <StatusMessage tone="error">
          <h1>Einladung konnte nicht vorbereitet werden</h1>
          <p>{details.message}</p>
          <Button onClick={() => void options.refetch()} variant="secondary">
            Erneut versuchen
          </Button>
        </StatusMessage>
      </div>
    );
  }

  const canInvite =
    options.data.actions.length > 0 && options.data.roles.length > 0;

  return (
    <div
      className={
        embedded
          ? "member-invitation-panel"
          : "action-page action-page--invitation"
      }
    >
      {!embedded ? (
        <header className="action-page__header">
          <div>
            <p className="action-page__eyebrow">Mitglieder</p>
            <h1>Mitglied einladen</h1>
            <p>
              Ordne ein Mitglied beim Annehmen der Einladung direkt einer von
              dir verwalteten Charity-Aktion zu.
            </p>
          </div>
        </header>
      ) : null}

      <div className="action-invitation-layout">
        <form
          className="action-invitation-form"
          id="invitation-form"
          onSubmit={(event) => {
            event.preventDefault();
            setFeedback(undefined);
            if (!draft.actionId || !draft.role) return;
            mutation.mutate({
              actionId: draft.actionId,
              displayName: draft.displayName,
              email: draft.email,
              role: draft.role,
            });
          }}
        >
          <fieldset disabled={!canInvite || mutation.isPending}>
            <legend>Einladung</legend>
            <div className="action-form-grid">
              <label className="action-field action-field--wide">
                <span>Charity-Aktion</span>
                <select
                  data-testid="invite-action"
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      actionId: event.currentTarget.value,
                    })
                  }
                  required
                  value={draft.actionId}
                >
                  {options.data.actions.map((action) => (
                    <option key={action.id} value={action.id}>
                      {action.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="action-field">
                <span>Name des Mitglieds</span>
                <input
                  autoComplete="name"
                  maxLength={160}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      displayName: event.currentTarget.value,
                    })
                  }
                  required
                  value={draft.displayName}
                />
              </label>
              <label className="action-field">
                <span>Login-E-Mail</span>
                <input
                  autoComplete="email"
                  onChange={(event) =>
                    setDraft({ ...draft, email: event.currentTarget.value })
                  }
                  required
                  type="email"
                  value={draft.email}
                />
              </label>
              <label className="action-field action-field--wide">
                <span>Rolle in dieser Aktion</span>
                <select
                  data-testid="invite-role"
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      role: event.currentTarget.value as InvitationRole,
                    })
                  }
                  required
                  value={draft.role}
                >
                  {options.data.roles.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {!canInvite ? (
              <StatusMessage tone="error">
                Du verwaltest derzeit keine Aktion, in die du ein Mitglied
                einladen darfst.
              </StatusMessage>
            ) : null}

            {feedback ? (
              <StatusMessage id="invitation-status" tone={feedback.tone}>
                {feedback.message}
              </StatusMessage>
            ) : null}

            <Button
              data-testid="invite-submit"
              disabled={!canInvite || mutation.isPending}
              icon={
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={MailSend01Icon}
                  size={18}
                  strokeWidth={1.8}
                />
              }
              type="submit"
            >
              {mutation.isPending ? "Wird versendet …" : "Einladung senden"}
            </Button>
          </fieldset>
        </form>

        <aside
          aria-labelledby="invite-next-heading"
          className="action-guidance"
        >
          <div aria-hidden="true" className="action-guidance__icon">
            <HugeiconsIcon icon={UserAdd01Icon} size={24} strokeWidth={1.7} />
          </div>
          <h2 id="invite-next-heading">Was passiert danach?</h2>
          <ol>
            <li>
              <HugeiconsIcon
                aria-hidden="true"
                icon={MailSend01Icon}
                size={18}
                strokeWidth={1.8}
              />
              Magic Link und Code kommen per E-Mail.
            </li>
            <li>
              <HugeiconsIcon
                aria-hidden="true"
                icon={UserCheck01Icon}
                size={18}
                strokeWidth={1.8}
              />
              Nach der Bestätigung ist das Mitglied angemeldet und der Aktion
              zugeordnet.
            </li>
          </ol>
          <p>
            Die Login-E-Mail kann das Mitglied im PoC anschließend nicht selbst
            ändern.
          </p>
        </aside>
      </div>

      <section
        aria-labelledby="invitation-lifecycle-heading"
        className="invitation-lifecycle"
      >
        <header className="invitation-lifecycle__header">
          <div>
            <p className="action-page__eyebrow">Einladungsverlauf</p>
            <h2 id="invitation-lifecycle-heading">Einladungen im Blick</h2>
            <p>
              Offene Einladungen kannst du erneut senden, korrigieren oder
              widerrufen. Abgeschlossene Einträge bleiben als Historie erhalten.
            </p>
          </div>
          <label className="action-field invitation-lifecycle__filter">
            <span>Status</span>
            <select
              data-testid="invitation-status-filter"
              onChange={(event) =>
                setStatusFilter(event.currentTarget.value as InvitationStatus)
              }
              value={statusFilter}
            >
              {invitationStatuses.map((item) => (
                <option key={item.value || "all"} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </header>

        {feedback ? (
          <StatusMessage id="invitation-lifecycle-status" tone={feedback.tone}>
            {feedback.message}
          </StatusMessage>
        ) : null}

        {invitations.isPending ? (
          <div
            aria-label="Einladungen werden geladen"
            className="invitation-lifecycle__skeleton"
            role="status"
          >
            <span />
            <span />
          </div>
        ) : invitations.isError ? (
          <StatusMessage tone="error">
            <p>{actionErrorMessage(invitations.error).message}</p>
            <Button
              onClick={() => void invitations.refetch()}
              variant="secondary"
            >
              Erneut versuchen
            </Button>
          </StatusMessage>
        ) : invitations.data.items.length === 0 ? (
          <div className="invitation-lifecycle__empty">
            <HugeiconsIcon
              aria-hidden="true"
              icon={UserAdd01Icon}
              size={24}
              strokeWidth={1.7}
            />
            <strong>Keine Einladungen in dieser Ansicht</strong>
            <span>
              Wechsle den Statusfilter oder versende oben die erste Einladung.
            </span>
          </div>
        ) : (
          <div className="invitation-list">
            {invitations.data.items.map((invitation) => {
              const pending = invitation.status === "pending";
              const correcting = correction?.id === invitation.id;
              const confirmingRevoke = revokeCandidate?.id === invitation.id;
              return (
                <article
                  className="invitation-card"
                  data-status={invitation.status}
                  data-testid={`invitation-${invitation.id}`}
                  key={invitation.id}
                >
                  <div className="invitation-card__identity">
                    <div>
                      <strong>{invitation.displayName}</strong>
                      <span>{invitation.email}</span>
                    </div>
                    <span
                      className="invitation-card__status"
                      data-status={invitation.status}
                    >
                      {statusLabels[invitation.status]}
                    </span>
                  </div>
                  <dl className="invitation-card__meta">
                    <div>
                      <dt>Aktion</dt>
                      <dd>{invitation.actionName}</dd>
                    </div>
                    <div>
                      <dt>Rolle</dt>
                      <dd>{roleLabels[invitation.role]}</dd>
                    </div>
                    <div>
                      <dt>{pending ? "Gültig bis" : "Versendet"}</dt>
                      <dd>
                        {localDate(
                          pending ? invitation.expiresAt : invitation.createdAt,
                        )}
                      </dd>
                    </div>
                  </dl>

                  {correcting ? (
                    <form
                      className="invitation-card__inline-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!correction.email.trim()) return;
                        correctAddress.mutate({
                          email: correction.email,
                          invitationId: invitation.id,
                        });
                      }}
                    >
                      <label className="action-field">
                        <span>Neue Login-E-Mail</span>
                        <small>
                          Die bisherige Einladung wird widerrufen; ihre Historie
                          bleibt erhalten.
                        </small>
                        <input
                          autoComplete="email"
                          autoFocus
                          onChange={(event) =>
                            setCorrection({
                              id: invitation.id,
                              email: event.currentTarget.value,
                            })
                          }
                          required
                          type="email"
                          value={correction.email}
                        />
                      </label>
                      <div className="invitation-card__actions">
                        <Button
                          disabled={correctAddress.isPending}
                          type="submit"
                        >
                          Korrigieren & senden
                        </Button>
                        <Button
                          disabled={correctAddress.isPending}
                          onClick={() => setCorrection(undefined)}
                          variant="ghost"
                        >
                          Abbrechen
                        </Button>
                      </div>
                    </form>
                  ) : confirmingRevoke ? (
                    <div className="invitation-card__confirmation" role="alert">
                      <p>
                        Wirklich widerrufen? Magic Link und Code funktionieren
                        danach sofort nicht mehr.
                      </p>
                      <div className="invitation-card__actions">
                        <Button
                          disabled={revoke.isPending}
                          onClick={() => revoke.mutate(invitation.id)}
                          variant="danger"
                        >
                          Jetzt widerrufen
                        </Button>
                        <Button
                          disabled={revoke.isPending}
                          onClick={() => setRevokeCandidate(undefined)}
                          variant="ghost"
                        >
                          Abbrechen
                        </Button>
                      </div>
                    </div>
                  ) : pending ? (
                    <div className="invitation-card__actions">
                      <Button
                        data-testid="invitation-resend"
                        disabled={resend.isPending}
                        icon={
                          <HugeiconsIcon
                            aria-hidden="true"
                            icon={RefreshIcon}
                            size={17}
                            strokeWidth={1.8}
                          />
                        }
                        onClick={() => resend.mutate(invitation.id)}
                        variant="secondary"
                      >
                        Erneut senden
                      </Button>
                      <Button
                        data-testid="invitation-correct-address"
                        icon={
                          <HugeiconsIcon
                            aria-hidden="true"
                            icon={NoteEditIcon}
                            size={17}
                            strokeWidth={1.8}
                          />
                        }
                        onClick={() =>
                          setCorrection({
                            id: invitation.id,
                            email: invitation.email,
                          })
                        }
                        variant="ghost"
                      >
                        Adresse korrigieren
                      </Button>
                      <Button
                        data-testid="invitation-revoke"
                        icon={
                          <HugeiconsIcon
                            aria-hidden="true"
                            icon={Delete02Icon}
                            size={17}
                            strokeWidth={1.8}
                          />
                        }
                        onClick={() => setRevokeCandidate(invitation)}
                        variant="ghost"
                      >
                        Widerrufen
                      </Button>
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
