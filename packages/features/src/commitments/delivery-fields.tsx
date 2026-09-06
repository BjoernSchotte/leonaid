import type {
  DeliveryOrderFormResponse,
  CommitmentResponse,
} from "@leonaid/api-client";

export interface DeliveryDraft {
  recipientName: string;
  streetLine1: string;
  postalCode: string;
  city: string;
  countryCode: string;
  contactName: string;
  contactPhone: string;
  instructions: string;
}
export function emptyDelivery(): DeliveryDraft {
  return {
    recipientName: "",
    streetLine1: "",
    postalCode: "",
    city: "",
    countryCode: "DE",
    contactName: "",
    contactPhone: "",
    instructions: "",
  };
}
export function deliveryDate(date: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "full",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}
export function DeliveryFields({
  definition,
  value,
  onChange,
  date,
  onDate,
  windowId,
  onWindow,
  deferred,
  onDeferred,
  allowDefer = true,
  showSchedule = true,
}: {
  allowDefer?: boolean;
  showSchedule?: boolean;
  definition: DeliveryOrderFormResponse;
  value: DeliveryDraft;
  onChange: (value: DeliveryDraft) => void;
  date: string;
  onDate: (date: string) => void;
  windowId: string;
  onWindow: (id: string) => void;
  deferred: boolean;
  onDeferred: (deferred: boolean) => void;
}) {
  const fields = [
    ["recipientName", "Firma / Empfänger", "organization", 200],
    ["streetLine1", "Straße und Hausnummer", "address-line1", 200],
    ["postalCode", "PLZ", "postal-code", 20],
    ["city", "Ort", "address-level2", 120],
    ["countryCode", "Ländercode (z. B. DE)", "country", 2],
  ] as const;
  const dates = [
    ...new Set(definition.windows.map((w) => w.deliveryOn)),
  ].sort();
  return (
    <fieldset className="commitment-step">
      <legend>
        <span>3</span>Lieferung
      </legend>
      {allowDefer && (
        <label className="commitment-delivery-toggle">
          <input
            type="checkbox"
            checked={deferred}
            onChange={(e) => onDeferred(e.target.checked)}
          />
          Lieferdaten später ergänzen (nur Entwurf)
        </label>
      )}
      {!deferred && (
        <>
          <div className="commitment-recipient-grid">
            {fields.map(([key, label, autocomplete, limit]) => (
              <div className="commitment-field" key={key}>
                <label htmlFor={`delivery-${key}`}>{label}</label>
                <input
                  id={`delivery-${key}`}
                  autoComplete={`shipping ${autocomplete}`}
                  maxLength={limit}
                  minLength={key === "countryCode" ? 2 : undefined}
                  required={definition.requireAddress}
                  value={value[key]}
                  onChange={(e) =>
                    onChange({
                      ...value,
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
          {showSchedule &&
            (!dates.length ? (
              <p role="status">
                Keine Lieferfenster verfügbar. Du kannst einen Entwurf speichern
                und die Lieferung später ergänzen.
              </p>
            ) : (
              <div className="commitment-recipient-grid">
                <div className="commitment-field">
                  <label htmlFor="delivery-date">Liefertag</label>
                  <select
                    id="delivery-date"
                    required={definition.requireWindow}
                    value={date}
                    onChange={(e) => onDate(e.target.value)}
                  >
                    <option value="">Tag auswählen</option>
                    {dates.map((d) => (
                      <option key={d} value={d}>
                        {deliveryDate(d)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="commitment-field">
                  <label htmlFor="delivery-window">Lieferzeitfenster</label>
                  <select
                    id="delivery-window"
                    required={definition.requireWindow}
                    value={windowId}
                    onChange={(e) => onWindow(e.target.value)}
                  >
                    <option value="">Zeitfenster auswählen</option>
                    {definition.windows
                      .filter((w) => w.deliveryOn === date)
                      .map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.startsAt.slice(0, 5)}–{w.endsAt.slice(0, 5)} Uhr
                        </option>
                      ))}
                  </select>
                  <small>Zeitzone: {definition.timezone}</small>
                </div>
              </div>
            ))}
          {definition.allowContact && (
            <div className="commitment-recipient-grid">
              <div className="commitment-field">
                <label htmlFor="delivery-contact">
                  Ansprechpartner bei der Lieferung (optional)
                </label>
                <input
                  id="delivery-contact"
                  autoComplete="shipping name"
                  maxLength={definition.contactNameMaxLength}
                  value={value.contactName}
                  onChange={(e) =>
                    onChange({ ...value, contactName: e.target.value })
                  }
                />
              </div>
              <div className="commitment-field">
                <label htmlFor="delivery-phone">
                  Telefonnummer am Liefertag (optional)
                </label>
                <input
                  id="delivery-phone"
                  type="tel"
                  autoComplete="shipping tel"
                  maxLength={definition.contactPhoneMaxLength}
                  value={value.contactPhone}
                  onChange={(e) =>
                    onChange({ ...value, contactPhone: e.target.value })
                  }
                />
              </div>
            </div>
          )}
          {definition.allowInstructions && (
            <div className="commitment-field">
              <label htmlFor="delivery-instructions">
                Abteilung / Lieferhinweise (optional)
              </label>
              <textarea
                id="delivery-instructions"
                rows={3}
                maxLength={definition.instructionsMaxLength}
                value={value.instructions}
                onChange={(e) =>
                  onChange({ ...value, instructions: e.target.value })
                }
              />
              <small>
                Zum Beispiel Abteilung, Eingang, Stockwerk oder Wegbeschreibung.
              </small>
            </div>
          )}
        </>
      )}
    </fieldset>
  );
}

export function DeliveryDetails({
  commitment,
}: {
  commitment: CommitmentResponse;
}) {
  const address = commitment.deliveryRecipient;
  const slot = commitment.deliveryWindowSnapshot;
  if (!address && !slot) return null;
  return (
    <section
      className="commitment-delivery-details"
      aria-label="Gespeicherte Lieferdaten"
    >
      <h3>Lieferung</h3>
      {address && (
        <>
          <p>
            {address.recipientName}
            <br />
            {address.streetLine1}
            <br />
            {address.postalCode} {address.city} · {address.countryCode}
          </p>
          {address.contactName && <p>Ansprechpartner: {address.contactName}</p>}
          {address.contactPhone && (
            <p>Telefon am Liefertag: {address.contactPhone}</p>
          )}
          {address.instructions && (
            <p className="commitment-delivery-instructions">
              {address.instructions}
            </p>
          )}
        </>
      )}
      {slot && (
        <p>
          {deliveryDate(slot.deliveryOn)} · {slot.startsAt.slice(0, 5)}–
          {slot.endsAt.slice(0, 5)} Uhr ({slot.timezone})
        </p>
      )}
    </section>
  );
}
