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
  FullWindowConfirm,
  deliveryDraft,
  fullWindowSelected,
  isFullWindowError,
  deliveryPayload,
  hasDeliveryAddress,
  selectableWindows,
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
  const [confirmFull, setConfirmFull] = useState(false);
  const complete = useMutation({
    mutationFn: (allowFullWindow: boolean) =>
      client.completeCommitment(
        order.actionId,
        order.id,
        { ...deliveryPayload(value), allowFullWindow },
        { headers: { "Idempotency-Key": key.current } },
      ),
    onSuccess: (result) => {
      setConfirmFull(false);
      onCompleted(result);
    },
    onError: (error) => {
      if (
        error instanceof ApiError &&
        error.detail.code.startsWith("delivery_")
      )
        void context.refetch();
      // Switched to "ausgebucht" meanwhile: ask, then book anyway.
      setConfirmFull(isFullWindowError(error));
    },
  });
  const configuration = context.data?.deliveryConfiguration;
  const fullWindow = fullWindowSelected(configuration, value.windowId);
  const canComplete =
    !configuration?.enabled ||
    (hasDeliveryAddress(value) &&
      selectableWindows(configuration).upcoming.some(
        (item) => item.id === value.windowId,
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
            if (!canComplete) return;
            if (fullWindow) setConfirmFull(true);
            else complete.mutate(false);
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
          {complete.isError && !isFullWindowError(complete.error) ? (
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
          <FullWindowConfirm
            onCancel={() => {
              setConfirmFull(false);
              complete.reset();
            }}
            onConfirm={() => complete.mutate(true)}
            pending={complete.isPending}
            window={
              confirmFull
                ? (fullWindow ??
                  configuration?.windows.find(
                    (item) => item.id === value.windowId,
                  ))
                : undefined
            }
          />
        </form>
      )}
    </section>
  );
}
