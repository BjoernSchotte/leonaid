import { useEffect, useId } from "react";
import type {
  CommitmentResponse,
  DeliveryConfigurationResponse,
  PublicOrderDeliveryRecipientRequest,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export interface DeliveryDraft {
  readonly recipientName: string;
  readonly streetLine1: string;
  readonly postalCode: string;
  readonly city: string;
  readonly countryCode: string;
  readonly windowId: string;
  readonly contactName: string;
  readonly contactPhone: string;
}

export function deliveryDraft(order?: CommitmentResponse): DeliveryDraft {
  return {
    recipientName: order?.deliveryRecipient?.recipientName ?? "",
    streetLine1: order?.deliveryRecipient?.streetLine1 ?? "",
    postalCode: order?.deliveryRecipient?.postalCode ?? "",
    city: order?.deliveryRecipient?.city ?? "",
    countryCode: order?.deliveryRecipient?.countryCode ?? "DE",
    windowId: order?.deliveryWindowId ?? "",
    contactName: order?.deliveryContact?.name ?? "",
    contactPhone: order?.deliveryContact?.phone ?? "",
  };
}

export function hasDeliveryAddress(value: DeliveryDraft) {
  return [
    value.recipientName,
    value.streetLine1,
    value.postalCode,
    value.city,
    value.countryCode,
  ].every((item) => item.trim());
}

export function hasPartialDeliveryAddress(value: DeliveryDraft) {
  return (
    !hasDeliveryAddress(value) &&
    [value.recipientName, value.streetLine1, value.postalCode, value.city].some(
      (item) => item.trim(),
    )
  );
}

export function deliveryPayload(value: DeliveryDraft) {
  return {
    deliveryRecipient: hasDeliveryAddress(value)
      ? {
          recipientName: value.recipientName.trim(),
          streetLine1: value.streetLine1.trim(),
          postalCode: value.postalCode.trim(),
          city: value.city.trim(),
          countryCode: value.countryCode.trim().toUpperCase(),
        }
      : null,
    deliveryWindowId: value.windowId || null,
    deliveryContact:
      value.contactName.trim() || value.contactPhone.trim()
        ? {
            name: value.contactName.trim() || null,
            phone: value.contactPhone.trim() || null,
          }
        : null,
  };
}

function dayLabel(day: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "full",
    timeZone: "UTC",
  }).format(new Date(`${day}T12:00:00Z`));
}

export function DeliveryFields({
  configuration,
  value,
  onChange,
  invoiceAddress,
  disabled = false,
  refresh,
  refreshing = false,
}: {
  readonly configuration: DeliveryConfigurationResponse;
  readonly value: DeliveryDraft;
  readonly onChange: (next: DeliveryDraft) => void;
  readonly invoiceAddress?: PublicOrderDeliveryRecipientRequest | null;
  readonly disabled?: boolean;
  readonly refresh: () => void;
  readonly refreshing?: boolean;
}) {
  const prefix = useId();
  const windows = configuration.windows.filter((item) => !item.retired);
  const days = [...new Set(windows.map((item) => item.deliveryOn))].sort();
  const selectedAvailable = windows.some((item) => item.id === value.windowId);
  useEffect(() => {
    if (value.windowId && !selectedAvailable)
      onChange({ ...value, windowId: "" });
  }, [selectedAvailable, value.windowId]);
  return (
    <fieldset
      className="commitment-step commitment-delivery"
      disabled={disabled}
    >
      <legend>Lieferung</legend>
      <p className="commitment-step__intro">
        Für eine prüfbereite Bestellung sind eine vollständige Lieferadresse und
        ein Zeitfenster erforderlich.
      </p>
      {invoiceAddress ? (
        <Button
          variant="secondary"
          onClick={() =>
            onChange({
              ...value,
              recipientName: invoiceAddress.recipientName,
              streetLine1: invoiceAddress.streetLine1,
              postalCode: invoiceAddress.postalCode,
              city: invoiceAddress.city,
              countryCode: invoiceAddress.countryCode ?? "DE",
            })
          }
        >
          Lieferadresse wie Rechnungsadresse übernehmen
        </Button>
      ) : null}
      <div className="commitment-recipient-grid">
        {(
          [
            [
              "recipientName",
              "Lieferempfänger",
              200,
              "section-delivery organization",
            ],
            [
              "streetLine1",
              "Straße und Hausnummer für die Lieferung",
              200,
              "section-delivery address-line1",
            ],
            [
              "postalCode",
              "PLZ für die Lieferung",
              20,
              "section-delivery postal-code",
            ],
            [
              "city",
              "Ort für die Lieferung",
              120,
              "section-delivery address-level2",
            ],
          ] as const
        ).map(([key, label, maximum, autoComplete]) => (
          <div
            className={`commitment-field ${key === "recipientName" || key === "streetLine1" ? "commitment-field--wide" : ""}`}
            key={key}
          >
            <label htmlFor={`${prefix}-${key}`}>{label}</label>
            <input
              id={`${prefix}-${key}`}
              autoComplete={autoComplete}
              aria-required="true"
              maxLength={maximum}
              value={value[key]}
              onChange={(event) =>
                onChange({ ...value, [key]: event.target.value })
              }
            />
          </div>
        ))}
        <div className="commitment-field">
          <label htmlFor={`${prefix}-country`}>
            Länderkürzel für die Lieferung
          </label>
          <input
            id={`${prefix}-country`}
            autoComplete="section-delivery country"
            maxLength={2}
            minLength={2}
            pattern="[A-Za-z]{2}"
            value={value.countryCode}
            onChange={(event) =>
              onChange({
                ...value,
                countryCode: event.target.value.toUpperCase(),
              })
            }
          />
          <small>Zwei Buchstaben, zum Beispiel DE.</small>
        </div>
      </div>
      <fieldset
        className="commitment-window-choice"
        aria-describedby={`${prefix}-timezone`}
      >
        <legend>Lieferzeitfenster</legend>
        <p id={`${prefix}-timezone`}>
          Alle Uhrzeiten gelten in {configuration.timezone}. Bitte ein Fenster
          auswählen.
        </p>
        {days.length ? (
          days.map((day) => (
            <div className="commitment-delivery-day" key={day}>
              <h3>{dayLabel(day)}</h3>
              <div className="commitment-delivery-options">
                {windows
                  .filter((item) => item.deliveryOn === day)
                  .sort((a, b) => a.startsAt.localeCompare(b.startsAt))
                  .map((item) => (
                    <label key={item.id}>
                      <input
                        type="radio"
                        name="delivery-window"
                        value={item.id}
                        checked={value.windowId === item.id}
                        onChange={() =>
                          onChange({ ...value, windowId: item.id })
                        }
                      />
                      <span>
                        {item.startsAt.slice(0, 5)}–{item.endsAt.slice(0, 5)}{" "}
                        Uhr<span className="sr-only"> am {dayLabel(day)}</span>
                      </span>
                    </label>
                  ))}
              </div>
            </div>
          ))
        ) : (
          <StatusMessage tone="info">
            Zurzeit ist kein Lieferfenster verfügbar. Ein Entwurf ist möglich.
            Bitte den Charity-Admin, neue Termine freizugeben.
          </StatusMessage>
        )}
        <Button variant="ghost" disabled={refreshing} onClick={refresh}>
          {refreshing
            ? "Lieferfenster werden geladen …"
            : "Lieferfenster aktualisieren"}
        </Button>
      </fieldset>
      <div className="commitment-recipient-grid">
        <div className="commitment-field commitment-field--wide">
          <label htmlFor={`${prefix}-contact-name`}>
            Ansprechpartner bei der Lieferung (optional)
          </label>
          <input
            id={`${prefix}-contact-name`}
            maxLength={200}
            autoComplete="section-delivery-contact name"
            value={value.contactName}
            onChange={(event) =>
              onChange({ ...value, contactName: event.target.value })
            }
          />
        </div>
        <div className="commitment-field commitment-field--wide">
          <label htmlFor={`${prefix}-contact-phone`}>
            Telefonnummer für die Lieferung (optional)
          </label>
          <input
            id={`${prefix}-contact-phone`}
            type="tel"
            maxLength={40}
            autoComplete="section-delivery-contact tel"
            value={value.contactPhone}
            onChange={(event) =>
              onChange({ ...value, contactPhone: event.target.value })
            }
          />
          <small>
            Beide Angaben sind unabhängig optional. Ohne Lieferkontakt bleibt
            der Bestellkontakt für Rückfragen erhalten.
          </small>
        </div>
      </div>
      {hasPartialDeliveryAddress(value) ? (
        <p className="commitment-step__intro">
          Vervollständige die angefangene Lieferadresse oder leere sie für einen
          Entwurf. Teiladressen können nicht gespeichert werden.
        </p>
      ) : null}
    </fieldset>
  );
}

export function DeliverySummary({
  order,
}: {
  readonly order: CommitmentResponse;
}) {
  const address = order.deliveryRecipient;
  const snapshot = order.deliveryWindowSnapshot;
  const time = snapshot
    ? new Intl.DateTimeFormat("de-DE", {
        timeStyle: "short",
        timeZone: snapshot.timezone,
      })
    : null;
  const start = snapshot ? new Date(snapshot.startsAt!) : null;
  return (
    <section
      className="commitment-delivery-summary"
      aria-label="Gespeicherte Lieferdaten"
    >
      <h3>Lieferung</h3>
      {address ? (
        <address>
          {address.recipientName}
          <br />
          {address.streetLine1}
          <br />
          {address.postalCode} {address.city}
          <br />
          {address.countryCode}
        </address>
      ) : (
        <p>Keine Lieferadresse erfasst.</p>
      )}
      <p>
        {snapshot && start && time ? (
          <>
            {new Intl.DateTimeFormat("de-DE", {
              dateStyle: "full",
              timeZone: snapshot.timezone,
            }).format(start)}{" "}
            · {time.format(start)}–{time.format(new Date(snapshot.endsAt!))} Uhr
            ({snapshot.timezone})
          </>
        ) : (
          "Kein Lieferfenster erfasst."
        )}
      </p>
      {order.deliveryContact ? (
        <p>
          <strong>Lieferkontakt:</strong>{" "}
          {order.deliveryContact.name ?? "Kein Name angegeben"}
          {order.deliveryContact.phone ? (
            <> · {order.deliveryContact.phone}</>
          ) : null}
        </p>
      ) : (
        <p>
          <strong>Bestellkontakt:</strong> {order.buyer.displayName}
          {order.buyer.email ? ` · ${order.buyer.email}` : ""}
        </p>
      )}
    </section>
  );
}
