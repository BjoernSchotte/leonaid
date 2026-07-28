import {
  MailSend01Icon,
  UserAdd01Icon,
  UserCheck01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  ApiError,
  type CreateInvitationRequest,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

export interface MemberInvitationPageProps {
  readonly client: LeonAidApiClient;
  readonly embedded?: boolean;
}

type InvitationRole = CreateInvitationRequest["role"];

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

export function MemberInvitationPage({
  client,
  embedded = false,
}: MemberInvitationPageProps) {
  const [draft, setDraft] = useState<InvitationDraft>(emptyDraft);
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
  const mutation = useMutation({
    mutationFn: (request: CreateInvitationRequest) =>
      client.createInvitation(request),
    onSuccess() {
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
    </div>
  );
}
