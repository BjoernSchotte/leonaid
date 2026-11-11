import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  type CharityActionConfigurationResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Badge, StatusMessage, Switch, useOptionalToast } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

interface OrderFormDonationSectionProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  /** Archived action: the switch is shown, not changed. */
  readonly disabled: boolean;
  /** The action has the function "Spenden". */
  readonly hasDonations: boolean;
  /** The action's order form; the section exists only with one. */
  readonly orderForm: NonNullable<
    CharityActionConfigurationResponse["orderForm"]
  >;
}

/** The capability picker refuses to drop "Spenden" while the switch is on. */
export const DONATION_SWITCH_BLOCKS_CAPABILITY =
  "Schalten Sie zuerst die Zusatzspende im Bestellformular aus.";

/**
 * "Zusatzspende im Bestellformular" in the action's settings
 * (specs/mails-documents-donations-push §8.6). The switch saves at once
 * and, unlike the action's functions, can change while the action runs.
 */
export function OrderFormDonationSection({
  actionId,
  client,
  disabled,
  hasDonations,
  orderForm,
}: OrderFormDonationSectionProps) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const queryKey = ["action-configuration", actionId] as const;
  const [error, setError] = useState<string>();
  const save = useMutation({
    mutationFn: (allowDonation: boolean) =>
      client.setOrderFormDonation(actionId, { allowDonation }),
    onMutate: () => setError(undefined),
    onSuccess(result) {
      cache.setQueryData(queryKey, result);
      // The capture form reads whether a donation is offered.
      void cache.invalidateQueries({
        queryKey: ["commitment-capture-context", actionId],
      });
      toast?.show({
        title: result.orderForm?.allowDonation
          ? "Das Bestellformular bietet ab jetzt eine Zusatzspende an."
          : "Das Bestellformular bietet keine Zusatzspende mehr an.",
        tone: "success",
      });
    },
    async onError(cause) {
      // The form or the functions changed meanwhile: show their state.
      if (cause instanceof ApiError && cause.status === 409) {
        await Promise.all([
          cache.invalidateQueries({ queryKey }),
          cache.invalidateQueries({
            queryKey: ["action-management", actionId],
          }),
        ]);
      }
      setError(
        cause instanceof ApiError &&
          cause.detail.code === "order_form_donation_capability_missing"
          ? "Die Zusatzspende braucht die Funktion „Spenden“. Schalten Sie zuerst die Funktion ein."
          : actionErrorMessage(cause).message,
      );
    },
  });
  const on = orderForm.allowDonation;

  return (
    <section
      aria-labelledby="order-form-donation-heading"
      className="edit-section"
      data-testid="order-form-donation-section"
      id="order-form-donation"
    >
      <h2 className="tab-h2" id="order-form-donation-heading">
        Bestellformular
      </h2>
      <p className="small muted edit-section-intro">
        Der Schalter gilt sofort, auch während die Aktion läuft.
      </p>
      <ul className="choice-list">
        <li className="buyer-mail-switch">
          <div className="buyer-mail-switch-text">
            <label htmlFor="order-form-donation-switch">
              <strong>Zusatzspende im Bestellformular anbieten</strong>
            </label>
            <p className="small muted" id="order-form-donation-description">
              Besteller können zusätzlich zur Bestellung freiwillig spenden. Die
              Spende erhält eine eigene Spendenzusage, getrennt von der
              Rechnung. Benötigt die Funktion „Spenden“ und den Teil „Spenden“
              in „Rechtliches“.
              {hasDonations
                ? null
                : " Diese Aktion hat die Funktion „Spenden“ nicht; der Schalter bleibt deshalb aus."}
            </p>
          </div>
          <Badge tone={on ? "ok" : "neutral"}>{on ? "An" : "Aus"}</Badge>
          <Switch
            aria-describedby="order-form-donation-description"
            checked={on}
            data-testid="order-form-donation-switch"
            disabled={
              disabled ||
              save.isPending ||
              // Switching off stays possible when the function is gone.
              (!hasDonations && !on)
            }
            id="order-form-donation-switch"
            onChange={(event) => save.mutate(event.target.checked)}
          />
        </li>
      </ul>
      {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
    </section>
  );
}
