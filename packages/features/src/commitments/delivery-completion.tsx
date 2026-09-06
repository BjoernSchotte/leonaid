import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ApiError,
  type CommitmentResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import {
  DeliveryFields,
  DeliveryDetails,
  emptyDelivery,
  type DeliveryDraft,
} from "./delivery-fields";

export function DeliveryCompletion({
  client,
  order,
  onSaved,
  onCancel,
}: {
  client: LeonAidApiClient;
  order: CommitmentResponse;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [baseline, setBaseline] = useState(order);
  const [comparison, setComparison] = useState<CommitmentResponse>();
  const [conflict, setConflict] = useState(false);
  const [delivery, setDelivery] = useState<DeliveryDraft>({
    ...emptyDelivery(),
    ...order.deliveryRecipient,
    contactName: order.deliveryRecipient?.contactName ?? "",
    contactPhone: order.deliveryRecipient?.contactPhone ?? "",
    instructions: order.deliveryRecipient?.instructions ?? "",
  });
  const [invoice, setInvoice] = useState({
    recipientName: "",
    streetLine1: "",
    postalCode: "",
    city: "",
    countryCode: "DE",
    ...order.invoiceRecipient,
  });
  const [email, setEmail] = useState(
    order.invoiceRecipient?.email ?? order.buyer.email ?? "",
  );
  const [same, setSame] = useState(!order.invoiceRecipient);
  const [date, setDate] = useState("");
  const [windowId, setWindowId] = useState(order.deliveryWindowId ?? "");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const message = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const attempt = useRef<
    { payload: string; key: string; unknown: boolean } | undefined
  >(undefined);
  const context = useQuery({
    queryKey: ["completion-context", order.actionId],
    queryFn: () => client.getDeliveryOrderForm(order.actionId),
  });
  const definition = context.data;
  useEffect(() => {
    if (error) message.current?.focus();
  }, [error]);
  return (
    <form
      className="commitment-delivery-completion"
      data-testid="delivery-completion"
      onSubmit={async (event) => {
        event.preventDefault();
        if (pending || !definition) return;
        const recipient = same
          ? {
              recipientName: delivery.recipientName,
              streetLine1: delivery.streetLine1,
              postalCode: delivery.postalCode,
              city: delivery.city,
              countryCode: delivery.countryCode,
            }
          : invoice;
        const body = {
          expectedVersion: baseline.deliveryCompletionVersion,
          deliveryRecipient: delivery,
          invoiceRecipient: { ...recipient, email: email.trim() || null },
          windowId: windowId || null,
        };
        const payload = JSON.stringify(body);
        if (attempt.current?.unknown && attempt.current.payload !== payload) {
          setError(
            "Der Ausgang der letzten Übermittlung ist unklar. Sende zunächst die ursprünglichen Angaben unverändert erneut.",
          );
          return;
        }
        if (!attempt.current || attempt.current.payload !== payload)
          attempt.current = {
            payload,
            key: crypto.randomUUID(),
            unknown: false,
          };
        attempt.current.unknown = true;
        setError("");
        setConflict(false);
        setPending(true);
        try {
          await client.completeCommitmentDelivery(
            order.actionId,
            order.id,
            body,
            { headers: { "Idempotency-Key": attempt.current.key } },
          );
          onSaved();
        } catch (cause) {
          setConflict(
            cause instanceof ApiError &&
              cause.detail.code === "delivery_completion_conflict",
          );
          if (cause instanceof ApiError && cause.status < 500)
            attempt.current.unknown = false;
          setError(
            cause instanceof ApiError
              ? `${cause.detail.message} Deine Eingaben bleiben erhalten.`
              : "Die Verbindung ist unterbrochen. Deine Eingaben bleiben erhalten; bitte unverändert erneut versuchen.",
          );
        } finally {
          setPending(false);
        }
      }}
    >
      <h3 ref={heading} tabIndex={-1}>
        Liefer- und Rechnungsdaten ergänzen
      </h3>
      <p>
        Nach dem Speichern ist die Bestellung prüfbereit. Mengen und Preise
        bleiben unverändert.
      </p>
      {error && (
        <div ref={message} tabIndex={-1}>
          <StatusMessage tone="error">{error}</StatusMessage>
        </div>
      )}
      {conflict && (
        <Button
          type="button"
          variant="secondary"
          onClick={async () => {
            try {
              const latest = await client.listCommitments(order.actionId);
              const current = latest.items.find(
                (item) => item.commitment.id === order.id,
              )?.commitment;
              if (current) setComparison(current);
            } catch {
              setError(
                "Der aktuelle Stand konnte nicht geladen werden. Deine Eingaben bleiben erhalten.",
              );
            }
          }}
        >
          Aktuelle Angaben vergleichen
        </Button>
      )}
      {comparison && (
        <section aria-label="Gespeicherte Angaben">
          <h4>Aktuell gespeichert</h4>
          <DeliveryDetails commitment={comparison} />
          <p>
            Rechnung: {comparison.invoiceRecipient?.recipientName},{" "}
            {comparison.invoiceRecipient?.streetLine1},{" "}
            {comparison.invoiceRecipient?.postalCode}{" "}
            {comparison.invoiceRecipient?.city},{" "}
            {comparison.invoiceRecipient?.countryCode} ·{" "}
            {comparison.invoiceRecipient?.email}
          </p>
          <Button
            type="button"
            onClick={() => {
              setBaseline(comparison);
              if (comparison.deliveryWindowId)
                setWindowId(comparison.deliveryWindowId);
              setComparison(undefined);
              setConflict(false);
              setError("");
            }}
          >
            Eigene Eingaben auf diesen Stand übernehmen
          </Button>
        </section>
      )}
      {context.isError && (
        <StatusMessage tone="error">
          Lieferplanung konnte nicht geladen werden.
        </StatusMessage>
      )}
      {!definition ? (
        <p>Lieferplanung wird geladen …</p>
      ) : (
        <fieldset disabled={pending}>
          {baseline.deliveryWindowId && (
            <>
              <p>Der bereits gebuchte Liefertermin bleibt unverändert.</p>
              <DeliveryDetails commitment={baseline} />
            </>
          )}
          <DeliveryFields
            definition={{ ...definition, requireAddress: true }}
            value={delivery}
            onChange={setDelivery}
            date={date}
            onDate={(value) => {
              setDate(value);
              setWindowId("");
            }}
            windowId={windowId}
            onWindow={setWindowId}
            deferred={false}
            onDeferred={() => {}}
            allowDefer={false}
            showSchedule={!baseline.deliveryWindowId && definition.enabled}
          />
          {!baseline.deliveryWindowId && (
            <Button
              type="button"
              variant="ghost"
              onClick={async () => {
                const result = await context.refetch();
                if (
                  result.data &&
                  !result.data.windows.some((item) => item.id === windowId)
                ) {
                  setWindowId("");
                  setDate("");
                }
              }}
            >
              Lieferfenster aktualisieren
            </Button>
          )}
          <fieldset className="commitment-step">
            <legend>Rechnung</legend>
            <label className="commitment-delivery-toggle">
              <input
                type="checkbox"
                checked={same}
                onChange={(e) => setSame(e.target.checked)}
              />
              Rechnungsadresse entspricht der Lieferadresse
            </label>
            {!same && (
              <div className="commitment-recipient-grid">
                {(
                  [
                    ["recipientName", "Rechnungsempfänger", 200],
                    ["streetLine1", "Straße und Hausnummer (Rechnung)", 200],
                    ["postalCode", "PLZ (Rechnung)", 20],
                    ["city", "Ort (Rechnung)", 120],
                    ["countryCode", "Ländercode (Rechnung)", 2],
                  ] as const
                ).map(([key, label, limit]) => (
                  <div className="commitment-field" key={key}>
                    <label htmlFor={`completion-${key}`}>{label}</label>
                    <input
                      id={`completion-${key}`}
                      required
                      maxLength={limit}
                      value={invoice[key]}
                      onChange={(e) =>
                        setInvoice({
                          ...invoice,
                          [key]:
                            key === "countryCode"
                              ? e.target.value.toUpperCase()
                              : e.target.value,
                        })
                      }
                    />
                  </div>
                ))}
              </div>
            )}
            <div className="commitment-field">
              <label htmlFor="completion-email">Rechnungs-E-Mail</label>
              <input
                id="completion-email"
                type="email"
                maxLength={320}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </fieldset>
          <div className="commitment-invoice-review__actions">
            <Button type="button" variant="ghost" onClick={onCancel}>
              Ergänzung schließen
            </Button>
            <Button type="submit" disabled={definition.enabled && !windowId}>
              Ergänzen und prüfbereit speichern
            </Button>
          </div>
        </fieldset>
      )}
    </form>
  );
}
