import { useEffect, useId } from "react";
import type {
  CommitmentResponse,
  DeliveryConfigurationResponse,
  PublicOrderDeliveryRecipientRequest,
} from "@leonaid/api-client";
import { ApiError } from "@leonaid/api-client";
import { Button, ConfirmDialog, StatusMessage } from "@leonaid/ui";

export interface DeliveryDraft {
  readonly recipientName: string;
  readonly streetLine1: string;
  readonly postalCode: string;
  readonly city: string;
  readonly countryCode: string;
  readonly windowId: string;
  readonly contactName: string;
  readonly contactPhone: string;
  readonly driverNote: string;
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
    driverNote: order?.deliveryContact?.driverNote ?? "",
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
      value.contactName.trim() ||
      value.contactPhone.trim() ||
      value.driverNote.trim()
        ? {
            name: value.contactName.trim() || null,
            phone: value.contactPhone.trim() || null,
            driverNote: value.driverNote.trim() || null,
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

type DeliveryWindowOption = DeliveryConfigurationResponse["windows"][number];

function zoneOffset(instant: number, zone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(instant));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value);
  return (
    Date.UTC(
      part("year"),
      part("month") - 1,
      part("day"),
      part("hour"),
      part("minute"),
      part("second"),
    ) - instant
  );
}

/** Start instant (ms) of a window whose wall time is local to `zone`. */
export function windowStart(window: DeliveryWindowOption, zone: string) {
  const [year, month, day] = window.deliveryOn.split("-").map(Number);
  const [hour, minute] = window.startsAt.split(":").map(Number);
  const wall = Date.UTC(year!, month! - 1, day!, hour!, minute!);
  // Two passes settle the offset across a DST change; Core rejects
  // ambiguous or nonexistent wall times when windows are created.
  const first = wall - zoneOffset(wall, zone);
  return wall - zoneOffset(first, zone);
}

/**
 * Windows an order may select. Capture only offers active windows that have
 * not started. A manager completing an existing order may also record a
 * window that has already started (retired or not) as historical delivery.
 */
export function selectableWindows(
  configuration: DeliveryConfigurationResponse,
  { historical = false, now = Date.now() } = {},
) {
  const upcoming: DeliveryWindowOption[] = [];
  const past: DeliveryWindowOption[] = [];
  for (const item of configuration.windows) {
    if (windowStart(item, configuration.timezone) > now) {
      if (!item.retired) upcoming.push(item);
    } else if (historical) past.push(item);
  }
  return { upcoming, past };
}

/**
 * The selected window when a manager marked it "ausgebucht" and the order
 * would newly book it; such a booking needs a confirmation first.
 */
export function fullWindowSelected(
  configuration: DeliveryConfigurationResponse | null | undefined,
  windowId: string,
) {
  if (!configuration?.enabled || !windowId) return undefined;
  return selectableWindows(configuration).upcoming.find(
    (item) => item.id === windowId && item.fullyBooked,
  );
}

/** The server refused a window that was switched to "ausgebucht" meanwhile. */
export function isFullWindowError(error: unknown) {
  return (
    error instanceof ApiError && error.detail.code === "delivery_window_full"
  );
}

/** Asks before booking a window marked "ausgebucht" (admin and PWA). */
export function FullWindowConfirm({
  window,
  onCancel,
  onConfirm,
  pending = false,
}: {
  readonly window: DeliveryWindowOption | undefined;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
  readonly pending?: boolean;
}) {
  return (
    <ConfirmDialog
      confirmLabel="Trotzdem eintragen"
      description={
        window
          ? `${dayLabel(window.deliveryOn)}, ${window.startsAt.slice(0, 5)}–${window.endsAt.slice(0, 5)} Uhr ist als ausgebucht markiert. Das öffentliche Bestellformular bietet es nicht mehr an. Die Bestellung wird trotzdem in diesem Fenster eingetragen; das wird im Verlauf vermerkt.`
          : ""
      }
      onConfirm={onConfirm}
      onOpenChange={(next) => {
        if (!next && !pending) onCancel();
      }}
      open={Boolean(window)}
      pending={pending}
      title="Lieferfenster ist ausgebucht"
      tone="primary"
    />
  );
}

export function DeliveryFields({
  configuration,
  value,
  onChange,
  invoiceAddress,
  disabled = false,
  refresh,
  refreshing = false,
  lockedWindow = false,
  historical = false,
}: {
  readonly configuration: DeliveryConfigurationResponse;
  readonly value: DeliveryDraft;
  readonly onChange: (next: DeliveryDraft) => void;
  readonly invoiceAddress?: PublicOrderDeliveryRecipientRequest | null;
  readonly disabled?: boolean;
  readonly refresh: () => void;
  readonly refreshing?: boolean;
  /** A booked window is immutable: hide the choice and keep the stored ID. */
  readonly lockedWindow?: boolean;
  /** Manager completion only: also offer windows that have already started. */
  readonly historical?: boolean;
}) {
  const prefix = useId();
  const { upcoming, past } = selectableWindows(configuration, { historical });
  const selectedAvailable = [...upcoming, ...past].some(
    (item) => item.id === value.windowId,
  );
  const renderDays = (windows: DeliveryWindowOption[], headingLevel: 3 | 4) =>
    [...new Set(windows.map((item) => item.deliveryOn))].sort().map((day) => {
      const Heading = headingLevel === 3 ? "h3" : "h4";
      return (
        <div className="commitment-delivery-day" key={day}>
          <Heading>{dayLabel(day)}</Heading>
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
                    onChange={() => onChange({ ...value, windowId: item.id })}
                  />
                  <span>
                    {item.startsAt.slice(0, 5)}–{item.endsAt.slice(0, 5)} Uhr
                    {item.retired
                      ? " (stillgelegt)"
                      : item.fullyBooked
                        ? " (ausgebucht)"
                        : ""}
                    <span className="sr-only"> am {dayLabel(day)}</span>
                  </span>
                </label>
              ))}
          </div>
        </div>
      );
    });
  useEffect(() => {
    if (!lockedWindow && value.windowId && !selectedAvailable)
      onChange({ ...value, windowId: "" });
  }, [lockedWindow, selectedAvailable, value.windowId]);
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
      {lockedWindow ? (
        <p className="commitment-step__intro">
          Der gebuchte Liefertermin bleibt unverändert.
        </p>
      ) : (
        <fieldset
          className="commitment-window-choice"
          aria-describedby={`${prefix}-timezone`}
        >
          <legend>Lieferzeitfenster</legend>
          <p id={`${prefix}-timezone`}>
            Alle Uhrzeiten gelten in {configuration.timezone}. Bitte ein Fenster
            auswählen.
          </p>
          {upcoming.length ? (
            renderDays(upcoming, 3)
          ) : past.length ? (
            <StatusMessage tone="info">
              Zurzeit ist kein künftiges Lieferfenster verfügbar. Eine bereits
              erfolgte Lieferung können Sie unten nachträglich erfassen.
            </StatusMessage>
          ) : (
            <StatusMessage tone="info">
              Zurzeit ist kein Lieferfenster verfügbar. Ein Entwurf ist möglich.
              Bitte den Charity-Admin, neue Termine freizugeben.
            </StatusMessage>
          )}
          {past.length ? (
            <div
              aria-describedby={`${prefix}-past-hint`}
              aria-labelledby={`${prefix}-past-title`}
              className="commitment-delivery-past"
              data-testid="delivery-window-past"
              role="group"
            >
              <h3 id={`${prefix}-past-title`}>
                Vergangene Lieferzeiten (nachträglich erfassen)
              </h3>
              <p id={`${prefix}-past-hint`}>
                Nur wählen, wenn die Bestellung in diesem Zeitfenster bereits
                geliefert wurde. Die Angabe wird als nachträglich erfasst
                protokolliert.
              </p>
              {renderDays(past, 4)}
            </div>
          ) : null}
          <Button variant="ghost" disabled={refreshing} onClick={refresh}>
            {refreshing
              ? "Lieferfenster werden geladen …"
              : "Lieferfenster aktualisieren"}
          </Button>
        </fieldset>
      )}
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
        <div className="commitment-field commitment-field--wide">
          <label htmlFor={`${prefix}-driver-note`}>
            Hinweis für den Fahrer (optional)
          </label>
          <input
            id={`${prefix}-driver-note`}
            maxLength={200}
            value={value.driverNote}
            onChange={(event) =>
              onChange({ ...value, driverNote: event.target.value })
            }
          />
          <small>Zum Beispiel: Klingel defekt, Hintereingang im Hof.</small>
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
      {order.deliveryContact?.name || order.deliveryContact?.phone ? (
        <p>
          <strong>Lieferkontakt:</strong>{" "}
          {order.deliveryContact?.name ?? "Kein Name angegeben"}
          {order.deliveryContact?.phone ? (
            <> · {order.deliveryContact.phone}</>
          ) : null}
        </p>
      ) : (
        <p>
          <strong>Bestellkontakt:</strong> {order.buyer.displayName}
          {order.buyer.email ? ` · ${order.buyer.email}` : ""}
        </p>
      )}
      {order.deliveryContact?.driverNote ? (
        <p>
          <strong>Hinweis für den Fahrer:</strong>{" "}
          {order.deliveryContact.driverNote}
        </p>
      ) : null}
    </section>
  );
}
