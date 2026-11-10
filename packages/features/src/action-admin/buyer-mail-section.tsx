import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  type BuyerMailConfigurationResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  ErrorState,
  SkeletonRows,
  StatusMessage,
  Switch,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

export const buyerMailConfigurationKey = (actionId: string) =>
  ["buyer-mail-configuration", actionId] as const;

interface BuyerMailSectionProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  /** Archived action: the switches are shown, not changed. */
  readonly disabled: boolean;
}

type Change = Partial<
  Pick<BuyerMailConfigurationResponse, "internalOrderMails">
>;

/**
 * "E-Mails an Käufer" in the action's settings: the switches of
 * `action_buyer_mail_configuration`. A switch saves at once with the row's
 * revision; unlike the action's functions it can change while the action
 * runs. Mails for orders of the public form are not behind a switch.
 */
export function BuyerMailSection({
  actionId,
  client,
  disabled,
}: BuyerMailSectionProps) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const queryKey = buyerMailConfigurationKey(actionId);
  const [error, setError] = useState<string>();
  const query = useQuery({
    queryKey,
    queryFn: () => client.getBuyerMailConfiguration(actionId),
    refetchOnWindowFocus: false,
    retry: false,
  });
  const save = useMutation({
    mutationFn: (change: Change) => {
      const current = query.data!;
      return client.saveBuyerMailConfiguration(actionId, {
        expectedRevision: current.revision,
        internalOrderMails:
          change.internalOrderMails ?? current.internalOrderMails,
        deliveryDayMail: current.deliveryDayMail,
        deliveryDaySendTime: current.deliveryDaySendTime,
      });
    },
    onMutate: () => setError(undefined),
    async onSuccess(result, change) {
      cache.setQueryData(queryKey, result);
      // The order list says per order whether a cancellation notifies.
      await cache.invalidateQueries({ queryKey: ["commitments", actionId] });
      if (change.internalOrderMails !== undefined) {
        toast?.show({
          title: result.internalOrderMails
            ? "Käufer erhalten ab jetzt E-Mails zu Bestellungen, die Mitglieder erfassen."
            : "Für Bestellungen, die Mitglieder erfassen, gehen keine E-Mails mehr an Käufer.",
          tone: "success",
        });
      }
    },
    async onError(cause) {
      // Someone else changed the switches: show their state.
      if (cause instanceof ApiError && cause.status === 409)
        await cache.invalidateQueries({ queryKey });
      setError(actionErrorMessage(cause).message);
    },
  });

  const heading = (
    <>
      <h2 className="tab-h2" id="buyer-mails-heading">
        E-Mails an Käufer
      </h2>
      <p className="small muted edit-section-intro">
        Wer über das öffentliche Bestellformular bestellt, erhält seine E-Mails
        immer. Hier legen Sie fest, welche E-Mails Käufer zusätzlich bekommen.
        Ein Schalter gilt sofort, auch während die Aktion läuft.
      </p>
    </>
  );

  if (query.isPending) {
    return (
      <section
        aria-busy="true"
        aria-labelledby="buyer-mails-heading"
        className="edit-section"
        id="buyer-mails"
      >
        {heading}
        <SkeletonRows rows={1} />
      </section>
    );
  }
  if (query.isError) {
    return (
      <section
        aria-labelledby="buyer-mails-heading"
        className="edit-section"
        id="buyer-mails"
      >
        {heading}
        <ErrorState
          onRetry={() => void query.refetch()}
          title="Die E-Mail-Einstellungen konnten nicht geladen werden"
        >
          Der Server hat nicht geantwortet. Prüfen Sie die Verbindung und
          versuchen Sie es erneut.
        </ErrorState>
      </section>
    );
  }
  const configuration = query.data;
  return (
    <section
      aria-labelledby="buyer-mails-heading"
      className="edit-section"
      data-testid="buyer-mail-section"
      id="buyer-mails"
    >
      {heading}
      <ul className="choice-list">
        <li className="buyer-mail-switch">
          <div className="buyer-mail-switch-text">
            <label htmlFor="buyer-mail-internal">
              <strong>E-Mails für Bestellungen, die Mitglieder erfassen</strong>
            </label>
            <p className="small muted" id="buyer-mail-internal-description">
              Der Käufer erhält eine Bestellbestätigung, sobald die Bestellung
              prüfbereit ist, und eine Nachricht, wenn sie storniert wird. Das
              gilt für Bestellungen aus der Akquise und aus der Verwaltung, wenn
              in der Bestellung eine E-Mail-Adresse des Käufers steht. Entwürfe
              senden nichts.
            </p>
          </div>
          <Badge tone={configuration.internalOrderMails ? "ok" : "neutral"}>
            {configuration.internalOrderMails ? "An" : "Aus"}
          </Badge>
          <Switch
            aria-describedby="buyer-mail-internal-description"
            checked={configuration.internalOrderMails}
            data-testid="buyer-mail-internal"
            disabled={disabled || save.isPending}
            id="buyer-mail-internal"
            onChange={(event) =>
              save.mutate({ internalOrderMails: event.target.checked })
            }
          />
        </li>
      </ul>
      {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
    </section>
  );
}
