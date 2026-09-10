import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  ApiError,
  type CommitmentResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import {
  DeliveryFields,
  deliveryDraft,
  deliveryPayload,
  hasDeliveryAddress,
  hasPartialDeliveryAddress,
} from "./delivery-fields";

export function orderError(error: unknown): string {
  return error instanceof ApiError
    ? error.detail.message
    : "Die Bestellung konnte nicht gespeichert werden. Deine Eingaben bleiben erhalten. Bitte versuche es erneut.";
}

export function CompleteDraft({
  client,
  order,
  onCompleted,
}: {
  readonly client: LeonAidApiClient;
  readonly order: CommitmentResponse;
  readonly onCompleted: (order: CommitmentResponse) => void;
}) {
  const [value, setValue] = useState(() => deliveryDraft(order));
  const key = useRef(`delivery-complete:${crypto.randomUUID()}`);
  const context = useQuery({
    queryKey: ["commitment-capture-context", order.actionId],
    queryFn: () => client.getCommitmentCaptureContext(order.actionId),
    refetchOnWindowFocus: false,
  });
  const complete = useMutation({
    mutationFn: () =>
      client.completeCommitment(
        order.actionId,
        order.id,
        deliveryPayload(value),
        { headers: { "Idempotency-Key": key.current } },
      ),
    onSuccess: onCompleted,
    onError: (error) => {
      if (
        error instanceof ApiError &&
        error.detail.code.startsWith("delivery_")
      )
        void context.refetch();
    },
  });
  const configuration = context.data?.deliveryConfiguration;
  const canComplete =
    !configuration?.enabled ||
    (hasDeliveryAddress(value) &&
      configuration.windows.some(
        (item) => item.id === value.windowId && !item.retired,
      ));
  return (
    <section
      className="commitment-draft-completion"
      aria-labelledby={`complete-${order.id}`}
    >
      <h2 id={`complete-${order.id}`}>Entwurf abschließen</h2>
      <p>
        Besteller, Rechnung und Positionen bleiben erhalten. Ergänze die
        Lieferangaben und gib die Bestellung zur Prüfung frei.
      </p>
      {context.isPending ? (
        <p role="status">Bestellvorgaben werden geladen …</p>
      ) : context.isError ? (
        <StatusMessage tone="error">
          <p>Die Bestellvorgaben konnten nicht geladen werden.</p>
          <Button onClick={() => void context.refetch()} variant="secondary">
            Erneut versuchen
          </Button>
        </StatusMessage>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (canComplete) complete.mutate();
          }}
        >
          {configuration?.enabled ? (
            <DeliveryFields
              configuration={configuration}
              value={value}
              onChange={(next) => {
                setValue(next);
                if (
                  next.windowId &&
                  next.windowId !== value.windowId &&
                  complete.isError
                )
                  complete.reset();
              }}
              invoiceAddress={order.invoiceRecipient}
              disabled={complete.isPending}
              refresh={() => void context.refetch()}
              refreshing={context.isFetching}
            />
          ) : null}
          {complete.isError ? (
            <StatusMessage tone="error">
              {orderError(complete.error)}
            </StatusMessage>
          ) : null}
          <Button
            type="submit"
            disabled={
              complete.isPending ||
              context.isFetching ||
              !canComplete ||
              hasPartialDeliveryAddress(value)
            }
          >
            {complete.isPending
              ? "Bestellung wird abgeschlossen …"
              : "Entwurf prüfbereit abschließen"}
          </Button>
        </form>
      )}
    </section>
  );
}
