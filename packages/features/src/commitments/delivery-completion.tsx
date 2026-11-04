import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import {
  ApiError,
  type CommitmentResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import {
  DeliveryFields,
  DeliverySummary,
  deliveryDraft,
  deliveryPayload,
  hasDeliveryAddress,
  hasPartialDeliveryAddress,
  selectableWindows,
} from "./delivery-fields";

interface InvoiceDraft {
  readonly recipientName: string;
  readonly streetLine1: string;
  readonly postalCode: string;
  readonly city: string;
  readonly countryCode: string;
  readonly email: string;
}

function invoiceDraft(order: CommitmentResponse): InvoiceDraft {
  const recipient = order.invoiceRecipient;
  return {
    recipientName: recipient?.recipientName ?? order.buyer.displayName,
    streetLine1: recipient?.streetLine1 ?? "",
    postalCode: recipient?.postalCode ?? "",
    city: recipient?.city ?? "",
    countryCode: recipient?.countryCode ?? "DE",
    email: recipient?.email ?? "",
  };
}

function hasInvoiceAddress(value: InvoiceDraft) {
  return [
    value.recipientName,
    value.streetLine1,
    value.postalCode,
    value.city,
  ].every((item) => item.trim());
}

/** Delivery details an invoice requires while delivery planning is enabled. */
export function deliveryDetailsMissing(
  order: CommitmentResponse,
  deliveryEnabled: boolean,
) {
  return (
    deliveryEnabled && (!order.deliveryRecipient || !order.deliveryWindowId)
  );
}

export function DeliveryCompletion({
  client,
  order,
  onSaved,
}: {
  readonly client: LeonAidApiClient;
  readonly order: CommitmentResponse;
  readonly onSaved: (order: CommitmentResponse) => void;
}) {
  const prefix = useId();
  const [baseline, setBaseline] = useState(order);
  const [delivery, setDelivery] = useState(() => deliveryDraft(order));
  const [invoice, setInvoice] = useState(() => invoiceDraft(order));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [comparison, setComparison] = useState<CommitmentResponse>();
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [saved, setSaved] = useState(false);
  const message = useRef<HTMLDivElement>(null);
  // One key per distinct payload: an unchanged retry after a lost response
  // replays exactly; any change is a new command.
  const attempt = useRef<{ payload: string; key: string }>(undefined);
  const configuration = useQuery({
    queryKey: ["delivery-configuration", order.actionId],
    queryFn: () => client.getDeliveryConfiguration(order.actionId),
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (error || saved) message.current?.focus();
  }, [error, saved]);

  const enabled = Boolean(configuration.data?.enabled);
  const lockedWindow = Boolean(baseline.deliveryWindowId);
  const choices = configuration.data
    ? selectableWindows(configuration.data, { historical: true })
    : { upcoming: [], past: [] };
  const historicalChoice =
    !lockedWindow && choices.past.some((item) => item.id === delivery.windowId);
  const deliveryReady =
    !enabled ||
    (hasDeliveryAddress(delivery) &&
      (lockedWindow ||
        historicalChoice ||
        choices.upcoming.some((item) => item.id === delivery.windowId)));
  const canSubmit =
    !pending &&
    !configuration.isPending &&
    hasInvoiceAddress(invoice) &&
    deliveryReady &&
    !hasPartialDeliveryAddress(delivery);

  async function submit() {
    const payload = deliveryPayload(delivery);
    const body = {
      expectedVersion: baseline.deliveryCompletionVersion,
      invoiceRecipient: {
        recipientName: invoice.recipientName.trim(),
        streetLine1: invoice.streetLine1.trim(),
        postalCode: invoice.postalCode.trim(),
        city: invoice.city.trim(),
        countryCode: invoice.countryCode.trim().toUpperCase(),
        email: invoice.email.trim().toLowerCase() || null,
      },
      deliveryRecipient: payload.deliveryRecipient,
      deliveryWindowId: enabled ? payload.deliveryWindowId : null,
      deliveryContact: enabled ? payload.deliveryContact : null,
    };
    const serialized = JSON.stringify(body);
    if (attempt.current?.payload !== serialized)
      attempt.current = {
        payload: serialized,
        key: `delivery-completion:${crypto.randomUUID()}`,
      };
    setPending(true);
    setError("");
    setConflict(false);
    setSaved(false);
    try {
      const result = await client.completeCommitmentDelivery(
        order.actionId,
        order.id,
        body,
        { headers: { "Idempotency-Key": attempt.current.key } },
      );
      attempt.current = undefined;
      setBaseline(result);
      setComparison(undefined);
      setSaved(true);
      onSaved(result);
    } catch (cause) {
      const known = cause instanceof ApiError;
      setConflict(
        known && cause.detail.code === "delivery_completion_conflict",
      );
      if (known && cause.detail.code.startsWith("delivery_window"))
        void configuration.refetch();
      setError(
        known
          ? `${cause.detail.message} Ihre Eingaben bleiben erhalten.`
          : "Die Angaben konnten nicht gespeichert werden. Ihre Eingaben bleiben erhalten. Bitte senden Sie sie unverändert erneut.",
      );
    } finally {
      setPending(false);
    }
  }

  async function loadCurrent() {
    setLoadingComparison(true);
    try {
      setComparison(await client.getCommitment(order.actionId, order.id));
    } catch {
      setError(
        "Der aktuelle Stand konnte nicht geladen werden. Ihre Eingaben bleiben erhalten.",
      );
    } finally {
      setLoadingComparison(false);
    }
  }

  return (
    <form
      aria-labelledby={`${prefix}-title`}
      className="commitment-delivery-completion"
      data-testid="delivery-completion"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) void submit();
      }}
    >
      <h3 id={`${prefix}-title`}>Liefer- und Rechnungsangaben ergänzen</h3>
      <p className="commitment-step__intro">
        Besteller, Positionen und Preise bleiben unverändert. Nach dem Speichern
        ist die Bestellung prüfbereit.
      </p>
      {saved || error ? (
        <div ref={message} tabIndex={-1}>
          {saved ? (
            <StatusMessage tone="success">
              Angaben gespeichert. Die Bestellung ist prüfbereit.
            </StatusMessage>
          ) : (
            <StatusMessage tone="error">{error}</StatusMessage>
          )}
        </div>
      ) : null}
      {conflict ? (
        <Button
          disabled={loadingComparison}
          onClick={() => void loadCurrent()}
          variant="secondary"
        >
          {loadingComparison
            ? "Aktueller Stand wird geladen …"
            : "Aktuellen Stand laden und vergleichen"}
        </Button>
      ) : null}
      {comparison ? (
        <section
          aria-label="Inzwischen gespeicherte Angaben"
          className="commitment-delivery-comparison"
          data-testid="delivery-completion-comparison"
        >
          <h4>Inzwischen gespeichert</h4>
          <DeliverySummary order={comparison} />
          <p>
            <strong>Rechnung:</strong>{" "}
            {comparison.invoiceRecipient
              ? [
                  comparison.invoiceRecipient.recipientName,
                  comparison.invoiceRecipient.streetLine1,
                  `${comparison.invoiceRecipient.postalCode} ${comparison.invoiceRecipient.city}`,
                  comparison.invoiceRecipient.email,
                ]
                  .filter(Boolean)
                  .join(", ")
              : "Keine Rechnungsadresse erfasst."}
          </p>
          <Button
            onClick={() => {
              setBaseline(comparison);
              if (comparison.deliveryWindowId)
                setDelivery({
                  ...delivery,
                  windowId: comparison.deliveryWindowId,
                });
              setComparison(undefined);
              setConflict(false);
              setError("");
            }}
          >
            Meine Eingaben auf diesen Stand anwenden
          </Button>
        </section>
      ) : null}
      {configuration.isPending ? (
        <p role="status">Lieferplanung wird geladen …</p>
      ) : configuration.isError ? (
        <StatusMessage tone="error">
          <p>
            Die Lieferplanung konnte nicht geladen werden. Ihre Eingaben bleiben
            erhalten.
          </p>
          <Button
            disabled={configuration.isFetching}
            onClick={() => void configuration.refetch()}
            variant="secondary"
          >
            Lieferplanung erneut laden
          </Button>
        </StatusMessage>
      ) : enabled && configuration.data ? (
        <DeliveryFields
          configuration={configuration.data}
          disabled={pending}
          invoiceAddress={baseline.invoiceRecipient}
          historical
          lockedWindow={lockedWindow}
          onChange={setDelivery}
          refresh={() => void configuration.refetch()}
          refreshing={configuration.isFetching}
          value={delivery}
        />
      ) : null}
      <fieldset className="commitment-step" disabled={pending}>
        <legend>Rechnung</legend>
        {enabled && hasDeliveryAddress(delivery) ? (
          <Button
            onClick={() =>
              setInvoice({
                ...invoice,
                recipientName: delivery.recipientName,
                streetLine1: delivery.streetLine1,
                postalCode: delivery.postalCode,
                city: delivery.city,
                countryCode: delivery.countryCode,
              })
            }
            variant="secondary"
          >
            Rechnungsadresse wie Lieferadresse übernehmen
          </Button>
        ) : null}
        <div className="commitment-recipient-grid">
          {(
            [
              ["recipientName", "Rechnungsempfänger", 200, "organization"],
              ["streetLine1", "Straße und Hausnummer", 200, "address-line1"],
              ["postalCode", "PLZ", 20, "postal-code"],
              ["city", "Ort", 120, "address-level2"],
            ] as const
          ).map(([key, label, maximum, autoComplete]) => (
            <div
              className={`commitment-field ${key === "recipientName" || key === "streetLine1" ? "commitment-field--wide" : ""}`}
              key={key}
            >
              <label htmlFor={`${prefix}-invoice-${key}`}>{label}</label>
              <input
                aria-required="true"
                autoComplete={`section-billing ${autoComplete}`}
                id={`${prefix}-invoice-${key}`}
                maxLength={maximum}
                onChange={(event) =>
                  setInvoice({ ...invoice, [key]: event.target.value })
                }
                value={invoice[key]}
              />
            </div>
          ))}
          <div className="commitment-field">
            <label htmlFor={`${prefix}-invoice-country`}>Länderkürzel</label>
            <input
              autoComplete="section-billing country"
              id={`${prefix}-invoice-country`}
              maxLength={2}
              minLength={2}
              onChange={(event) =>
                setInvoice({
                  ...invoice,
                  countryCode: event.target.value.toUpperCase(),
                })
              }
              pattern="[A-Za-z]{2}"
              value={invoice.countryCode}
            />
          </div>
          <div className="commitment-field commitment-field--wide">
            <label htmlFor={`${prefix}-invoice-email`}>
              Rechnungs-E-Mail (optional)
            </label>
            <input
              autoComplete="section-billing email"
              id={`${prefix}-invoice-email`}
              maxLength={320}
              onChange={(event) =>
                setInvoice({ ...invoice, email: event.target.value })
              }
              type="email"
              value={invoice.email}
            />
          </div>
        </div>
      </fieldset>
      {enabled && historicalChoice ? (
        <p
          className="commitment-step__intro"
          data-testid="delivery-completion-historical"
        >
          Die Lieferung wird nachträglich für ein vergangenes Zeitfenster
          erfasst.
        </p>
      ) : null}
      <Button
        data-testid="delivery-completion-submit"
        disabled={!canSubmit || Boolean(comparison)}
        type="submit"
      >
        {pending ? "Angaben werden gespeichert …" : "Angaben speichern"}
      </Button>
    </form>
  );
}
