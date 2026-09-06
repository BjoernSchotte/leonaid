import {
  ArrowLeft01Icon,
  CheckmarkCircle02Icon,
  Invoice03Icon,
  Package01Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  type AcquisitionActivityWorkItemResponse,
  type CommitmentResponse,
  type CreateCommitmentRequest,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import {
  DeliveryFields,
  DeliveryDetails,
  emptyDelivery,
  type DeliveryDraft,
} from "./delivery-fields";

interface CommitmentCapturePageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

interface RecipientDraft {
  readonly countryCode: string;
  readonly city: string;
  readonly email: string;
  readonly postalCode: string;
  readonly recipientName: string;
  readonly streetLine1: string;
}

const unitLabels = {
  box: ["Box", "Boxen"],
  package: ["Paket", "Pakete"],
  piece: ["Stück", "Stück"],
  sponsoring: ["Sponsoring", "Sponsorings"],
} as const;

function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

function quantityLabel(quantity: number, unit: keyof typeof unitLabels) {
  return unitLabels[unit][quantity === 1 ? 0 : 1];
}

function captureError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.detail.code === "idempotency_incomplete") {
      return "Die erste Übermittlung wird noch verarbeitet. Warte kurz und versuche dieselbe Bestellung erneut.";
    }
    if (error.detail.code === "idempotency_conflict") {
      return "Die Bestellung wurde bereits mit anderen Angaben gespeichert. Öffne den Sponsor neu und prüfe die Eingabe.";
    }
    if (error.detail.code === "offering_not_available") {
      return "Das gewählte Angebot ist nicht mehr verfügbar. Lade die Angebote neu und wähle erneut.";
    }
    if (error.detail.code.startsWith("delivery_")) {
      return `${error.detail.message} Deine weiteren Eingaben bleiben erhalten.`;
    }
    if (error.status === 403) {
      return "Du darfst für diesen Sponsor keine Bestellung erfassen. Wähle einen dir zugeordneten Sponsor.";
    }
  }
  return "Die Bestellung konnte nicht gespeichert werden. Prüfe deine Verbindung; deine Eingaben bleiben erhalten.";
}

function recipientFor(
  sponsor: AcquisitionActivityWorkItemResponse | undefined,
): RecipientDraft {
  return {
    countryCode: "DE",
    city: sponsor?.city ?? "",
    email: sponsor?.email ?? "",
    postalCode: sponsor?.postalCode ?? "",
    recipientName: sponsor?.partyDisplayName ?? "",
    streetLine1: "",
  };
}

function CaptureSuccess({
  commitment,
  onContinue,
}: {
  readonly commitment: CommitmentResponse;
  readonly onContinue: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);
  const ready = commitment.status === "review_ready";
  return (
    <section
      aria-labelledby="commitment-success-heading"
      className="commitment-success"
      data-commitment-id={commitment.id}
      data-testid="commitment-success"
    >
      <span aria-hidden="true" className="commitment-success__icon">
        <HugeiconsIcon
          icon={CheckmarkCircle02Icon}
          size={26}
          strokeWidth={1.8}
        />
      </span>
      <p className="commitment-eyebrow">Bestellung gespeichert</p>
      <h1 id="commitment-success-heading" ref={heading} tabIndex={-1}>
        {ready ? "Bereit für die Prüfung" : "Als Entwurf gesichert"}
      </h1>
      <p>
        {ready
          ? "Der Charity-Admin sieht die Bestellung jetzt im Prüfbereich."
          : "Die Bestellung ist gespeichert, aber noch nicht zur Prüfung freigegeben."}
      </p>
      <dl className="commitment-success__facts">
        <div>
          <dt>Status</dt>
          <dd>
            <span className="commitment-status" data-status={commitment.status}>
              {ready ? "Prüfbereit" : "Entwurf"}
            </span>
          </dd>
        </div>
        <div>
          <dt>Besteller</dt>
          <dd>{commitment.buyer.displayName}</dd>
        </div>
        <div>
          <dt>Gesamt</dt>
          <dd>{formatMoney(commitment.totalMinor, commitment.currency)}</dd>
        </div>
      </dl>
      <DeliveryDetails commitment={commitment} />
      {commitment.invoiceRecipient && (
        <p>
          Rechnung: {commitment.invoiceRecipient.recipientName},{" "}
          {commitment.invoiceRecipient.streetLine1},{" "}
          {commitment.invoiceRecipient.postalCode}{" "}
          {commitment.invoiceRecipient.city}
        </p>
      )}
      <div className="commitment-success__actions">
        <a className="ui-button ui-button--secondary" href="/app/sponsors">
          Zurück zu meinen Sponsoren
        </a>
        <Button onClick={onContinue} variant="ghost">
          Weitere Bestellung erfassen
        </Button>
      </div>
    </section>
  );
}

export function CommitmentCapturePage({
  client,
  identity,
}: CommitmentCapturePageProps) {
  const memberships = useMemo(
    () =>
      identity.actionMemberships.filter(
        (membership) => membership.role === "acquirer",
      ),
    [identity.actionMemberships],
  );
  const initialParameters = useMemo(
    () => new URLSearchParams(window.location.search),
    [],
  );
  const requestedActionId = initialParameters.get("action") ?? "";
  const initialActionId = memberships.some(
    (membership) => membership.actionId === requestedActionId,
  )
    ? requestedActionId
    : (memberships[0]?.actionId ?? "");
  const [actionId, setActionId] = useState(initialActionId);
  const [assignmentId, setAssignmentId] = useState(
    initialParameters.get("assignment") ?? "",
  );
  const [offeringId, setOfferingId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [recipient, setRecipient] = useState<RecipientDraft>(() =>
    recipientFor(undefined),
  );
  const commandId = useRef(crypto.randomUUID());
  const lastPayload = useRef("");
  const [delivery, setDelivery] = useState<DeliveryDraft>(emptyDelivery);
  const [deliveryDate, setDeliveryDate] = useState("");
  const [deliveryWindowId, setDeliveryWindowId] = useState("");
  const [sameAddress, setSameAddress] = useState(true);
  const [deferredDelivery, setDeferredDelivery] = useState(false);
  const [localError, setLocalError] = useState("");
  const errorFocus = useRef<HTMLDivElement>(null);

  const context = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getCommitmentCaptureContext(actionId),
    queryKey: ["commitment-capture-context", actionId],
  });
  const sponsors = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getAcquisitionActivityBoard(actionId, { limit: 100 }),
    queryKey: ["acquisition-activity-board", actionId],
  });
  const selectedSponsor = sponsors.data?.workItems.find(
    (item) => item.assignmentId === assignmentId,
  );
  const selectedOffering = context.data?.offerings.find(
    (offering) => offering.id === offeringId,
  );

  useEffect(() => {
    if (
      sponsors.data &&
      !sponsors.data.workItems.some(
        (item) => item.assignmentId === assignmentId,
      )
    ) {
      setAssignmentId(sponsors.data.workItems[0]?.assignmentId ?? "");
    }
  }, [assignmentId, sponsors.data]);

  useEffect(() => {
    if (
      context.data &&
      !context.data.offerings.some((offering) => offering.id === offeringId)
    ) {
      setOfferingId(context.data.offerings[0]?.id ?? "");
    }
  }, [context.data, offeringId]);

  useEffect(() => {
    setRecipient(recipientFor(selectedSponsor));
    setDelivery({
      ...emptyDelivery(),
      recipientName: selectedSponsor?.partyDisplayName ?? "",
      postalCode: selectedSponsor?.postalCode ?? "",
      city: selectedSponsor?.city ?? "",
    });
    setDeliveryWindowId("");
    setDeliveryDate("");
    setSameAddress(true);
    setDeferredDelivery(false);
    setLocalError("");
    commandId.current = crypto.randomUUID();
    lastPayload.current = "";
  }, [selectedSponsor?.assignmentId]);

  const deliveryDefinition = context.data?.delivery;
  const deliveryEnabled = Boolean(deliveryDefinition?.enabled);
  const create = useMutation({
    mutationFn: (payload: CreateCommitmentRequest) =>
      client.createCommitment(actionId, payload, {
        headers: { "Idempotency-Key": `delivery:${commandId.current}` },
      }),
    onError: (error) => {
      if (
        error instanceof ApiError &&
        error.detail.code.startsWith("delivery_")
      )
        void context.refetch();
    },
  });

  useEffect(() => {
    if (create.isError || localError) errorFocus.current?.focus();
  }, [create.isError, localError]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent)
      .submitter as HTMLButtonElement | null;
    if (!selectedSponsor || !selectedOffering || !submitter || create.isPending)
      return;
    const readyForReview = submitter.value === "review_ready";
    const address = deliveryEnabled && sameAddress ? delivery : recipient;
    const omitInvoice = deliveryEnabled && sameAddress && deferredDelivery;
    const payload: CreateCommitmentRequest = {
      buyer: {
        displayName: selectedSponsor.partyDisplayName,
        email: selectedSponsor.email,
        partyKind: selectedSponsor.partyKind,
        twentyId: selectedSponsor.partyId,
      },
      invoiceRecipient: omitInvoice
        ? null
        : {
            recipientName: address.recipientName.trim(),
            streetLine1: address.streetLine1.trim(),
            postalCode: address.postalCode.trim(),
            city: address.city.trim(),
            countryCode: address.countryCode,
            email: recipient.email.trim() || null,
          },
      deliveryRecipient:
        deliveryEnabled && !deferredDelivery
          ? {
              ...delivery,
              contactName: deliveryDefinition?.allowContact
                ? delivery.contactName.trim() || null
                : null,
              contactPhone: deliveryDefinition?.allowContact
                ? delivery.contactPhone.trim() || null
                : null,
              instructions: deliveryDefinition?.allowInstructions
                ? delivery.instructions.trim() || null
                : null,
            }
          : null,
      deliveryWindowId:
        deliveryEnabled && !deferredDelivery ? deliveryWindowId || null : null,
      lines: [
        {
          offeringId: selectedOffering.id,
          quantity,
          quotedUnitPriceMinor: selectedOffering.unitPriceMinor,
          unit: selectedOffering.unit,
        },
      ],
      readyForReview,
      source: "acquisition",
    };
    const serialized = JSON.stringify(payload);
    if (lastPayload.current && lastPayload.current !== serialized) {
      if (
        create.isError &&
        (!(create.error instanceof ApiError) ||
          create.error.detail.code === "idempotency_incomplete")
      ) {
        setLocalError(
          "Der Ausgang der letzten Übermittlung ist noch unklar. Bitte die ursprünglichen Angaben unverändert erneut senden oder zuerst die gespeicherten Bestellungen prüfen.",
        );
        return;
      }
      commandId.current = crypto.randomUUID();
    }
    lastPayload.current = serialized;
    setLocalError("");
    create.mutate(payload);
  }

  function reset() {
    commandId.current = crypto.randomUUID();
    lastPayload.current = "";
    setDeliveryWindowId("");
    setDeliveryDate("");
    setLocalError("");
    setQuantity(1);
    create.reset();
  }

  if (create.data) {
    return <CaptureSuccess commitment={create.data} onContinue={reset} />;
  }

  const pending = context.isPending || sponsors.isPending;
  const failed = context.isError || sponsors.isError;
  const totalMinor = (selectedOffering?.unitPriceMinor ?? 0) * quantity;

  return (
    <div className="commitment-page commitment-page--capture">
      <header className="commitment-page__header">
        <a className="commitment-back-link" href="/app/sponsors">
          <HugeiconsIcon
            aria-hidden="true"
            icon={ArrowLeft01Icon}
            size={18}
            strokeWidth={1.8}
          />
          Meine Sponsoren
        </a>
        <p className="commitment-eyebrow">Bestellung oder Zusage</p>
        <h1>Vom Gespräch zur klaren Bestellung.</h1>
        <p>
          Besteller, Angebot und Anschriften bleiben auf einer Seite. LeonAid
          berechnet den verbindlichen Preis beim Speichern erneut.
        </p>
      </header>

      {failed ? (
        <StatusMessage tone="error">
          <div>
            <strong>Bestellerfassung nicht erreichbar</strong>
            <p>
              Angebote oder Sponsoren konnten nicht geladen werden. Prüfe deine
              Verbindung und lade die Seite erneut.
            </p>
          </div>
        </StatusMessage>
      ) : pending ? (
        <div
          aria-label="Bestellformular wird geladen"
          className="commitment-loading"
          role="status"
        >
          <span />
          <span />
          <span />
        </div>
      ) : (
        <form className="commitment-capture" onSubmit={submit}>
          <fieldset
            className="commitment-capture-lock"
            disabled={create.isPending}
          >
            <div className="commitment-capture__form">
              {memberships.length > 1 ? (
                <div className="commitment-field">
                  <label htmlFor="commitment-action">Charity-Aktion</label>
                  <small id="commitment-action-help">
                    Die Aktion bestimmt verfügbare Angebote und Zuständigkeiten.
                  </small>
                  <select
                    aria-describedby="commitment-action-help"
                    id="commitment-action"
                    onChange={(event) => {
                      setActionId(event.target.value);
                      setAssignmentId("");
                      create.reset();
                    }}
                    value={actionId}
                  >
                    {memberships.map((membership) => (
                      <option
                        key={membership.actionId}
                        value={membership.actionId}
                      >
                        {membership.actionName}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              <fieldset className="commitment-step">
                <legend>
                  <span>1</span>
                  Besteller
                </legend>
                <div className="commitment-field">
                  <label htmlFor="commitment-sponsor">
                    Zugeordneter Sponsor
                  </label>
                  <small id="commitment-sponsor-help">
                    Die Bestellung wird diesem CRM-Kontakt und deiner
                    Zuständigkeit zugeordnet.
                  </small>
                  <select
                    aria-describedby="commitment-sponsor-help"
                    data-testid="commitment-sponsor"
                    id="commitment-sponsor"
                    onChange={(event) => {
                      setAssignmentId(event.target.value);
                      create.reset();
                    }}
                    required
                    value={assignmentId}
                  >
                    <option disabled value="">
                      Sponsor auswählen
                    </option>
                    {(sponsors.data?.workItems ?? []).map((item) => (
                      <option key={item.assignmentId} value={item.assignmentId}>
                        {item.partyDisplayName}
                      </option>
                    ))}
                  </select>
                </div>
                {selectedSponsor ? (
                  <div
                    className="commitment-party"
                    data-testid="commitment-party"
                  >
                    <span aria-hidden="true">
                      <HugeiconsIcon
                        icon={UserMultiple02Icon}
                        size={20}
                        strokeWidth={1.8}
                      />
                    </span>
                    <div>
                      <strong>{selectedSponsor.partyDisplayName}</strong>
                      <small>
                        {[selectedSponsor.postalCode, selectedSponsor.city]
                          .filter(Boolean)
                          .join(" ") || "Keine Ortsangabe"}
                      </small>
                    </div>
                  </div>
                ) : null}
              </fieldset>

              <fieldset className="commitment-step">
                <legend>
                  <span>2</span>
                  Angebot und Menge
                </legend>
                {context.data?.offerings.length ? (
                  <div className="commitment-offering-grid">
                    <div className="commitment-field">
                      <label htmlFor="commitment-offering">Angebot</label>
                      <small id="commitment-offering-help">
                        Es werden nur aktuell bestellbare Angebote angezeigt.
                      </small>
                      <select
                        aria-describedby="commitment-offering-help"
                        data-testid="commitment-offering"
                        id="commitment-offering"
                        onChange={(event) => setOfferingId(event.target.value)}
                        required
                        value={offeringId}
                      >
                        {context.data.offerings.map((offering) => (
                          <option key={offering.id} value={offering.id}>
                            {offering.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="commitment-field">
                      <label htmlFor="commitment-quantity">Menge</label>
                      <small id="commitment-quantity-help">
                        Einheit:{" "}
                        {selectedOffering
                          ? quantityLabel(2, selectedOffering.unit)
                          : "–"}
                      </small>
                      <input
                        aria-describedby="commitment-quantity-help"
                        data-testid="commitment-quantity"
                        id="commitment-quantity"
                        inputMode="numeric"
                        max={1_000_000}
                        min={1}
                        onChange={(event) =>
                          setQuantity(
                            Math.max(
                              1,
                              Number.parseInt(event.target.value, 10) || 1,
                            ),
                          )
                        }
                        required
                        type="number"
                        value={quantity}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="commitment-empty">
                    <HugeiconsIcon
                      aria-hidden="true"
                      icon={Package01Icon}
                      size={24}
                      strokeWidth={1.8}
                    />
                    <strong>Kein Angebot bestellbar</strong>
                    <span>
                      Bitte den Charity-Admin, Angebot und Zeitraum zu prüfen.
                    </span>
                  </div>
                )}
              </fieldset>

              {deliveryEnabled && deliveryDefinition && (
                <DeliveryFields
                  definition={deliveryDefinition}
                  value={delivery}
                  onChange={setDelivery}
                  date={deliveryDate}
                  onDate={(date) => {
                    setDeliveryDate(date);
                    setDeliveryWindowId("");
                  }}
                  windowId={deliveryWindowId}
                  onWindow={setDeliveryWindowId}
                  deferred={deferredDelivery}
                  onDeferred={setDeferredDelivery}
                />
              )}
              <fieldset className="commitment-step">
                <legend>
                  <span>{deliveryEnabled ? 4 : 3}</span>
                  Rechnungsempfänger
                </legend>
                <p className="commitment-step__intro">
                  Diese Anschrift wird mit der Bestellung gespeichert und kann
                  vom Besteller abweichen.
                </p>
                {deliveryEnabled && (
                  <label className="commitment-delivery-toggle">
                    <input
                      type="checkbox"
                      checked={sameAddress}
                      onChange={(e) => setSameAddress(e.target.checked)}
                    />
                    Rechnungsadresse entspricht der Lieferadresse
                  </label>
                )}
                <div className="commitment-recipient-grid">
                  {(!deliveryEnabled || !sameAddress) && (
                    <>
                      <div className="commitment-field commitment-field--wide">
                        <label htmlFor="commitment-recipient-name">Name</label>
                        <input
                          autoComplete="organization"
                          id="commitment-recipient-name"
                          maxLength={200}
                          onChange={(event) =>
                            setRecipient({
                              ...recipient,
                              recipientName: event.target.value,
                            })
                          }
                          required
                          value={recipient.recipientName}
                        />
                      </div>
                      <div className="commitment-field commitment-field--wide">
                        <label htmlFor="commitment-street">
                          Straße und Hausnummer
                        </label>
                        <input
                          autoComplete="address-line1"
                          data-testid="commitment-street"
                          id="commitment-street"
                          maxLength={200}
                          onChange={(event) =>
                            setRecipient({
                              ...recipient,
                              streetLine1: event.target.value,
                            })
                          }
                          placeholder="Musterstraße 12"
                          required
                          value={recipient.streetLine1}
                        />
                      </div>
                      <div className="commitment-field">
                        <label htmlFor="commitment-postal-code">PLZ</label>
                        <input
                          autoComplete="postal-code"
                          id="commitment-postal-code"
                          maxLength={20}
                          onChange={(event) =>
                            setRecipient({
                              ...recipient,
                              postalCode: event.target.value,
                            })
                          }
                          required
                          value={recipient.postalCode}
                        />
                      </div>
                      <div className="commitment-field">
                        <label htmlFor="commitment-city">Ort</label>
                        <input
                          autoComplete="address-level2"
                          id="commitment-city"
                          maxLength={120}
                          onChange={(event) =>
                            setRecipient({
                              ...recipient,
                              city: event.target.value,
                            })
                          }
                          required
                          value={recipient.city}
                        />
                      </div>
                      <div className="commitment-field">
                        <label htmlFor="commitment-country">
                          Ländercode (z. B. DE)
                        </label>
                        <input
                          id="commitment-country"
                          autoComplete="billing country"
                          minLength={2}
                          maxLength={2}
                          required
                          value={recipient.countryCode}
                          onChange={(e) =>
                            setRecipient({
                              ...recipient,
                              countryCode: e.target.value.toUpperCase(),
                            })
                          }
                        />
                      </div>
                    </>
                  )}
                  <div className="commitment-field commitment-field--wide">
                    <label htmlFor="commitment-email">Rechnungs-E-Mail</label>
                    <small id="commitment-email-help">
                      Optional; kann von der Kontaktadresse abweichen.
                    </small>
                    <input
                      aria-describedby="commitment-email-help"
                      autoComplete="email"
                      id="commitment-email"
                      maxLength={320}
                      onChange={(event) =>
                        setRecipient({
                          ...recipient,
                          email: event.target.value,
                        })
                      }
                      type="email"
                      value={recipient.email}
                    />
                  </div>
                </div>
              </fieldset>
            </div>

            <aside
              aria-labelledby="commitment-summary-heading"
              className="commitment-summary"
            >
              <div className="commitment-summary__heading">
                <span aria-hidden="true">
                  <HugeiconsIcon
                    icon={Invoice03Icon}
                    size={21}
                    strokeWidth={1.8}
                  />
                </span>
                <div>
                  <h2 id="commitment-summary-heading">Bestellübersicht</h2>
                  <p>Vor dem Speichern noch einmal klar zusammengefasst.</p>
                </div>
              </div>
              <dl className="commitment-summary__facts">
                <div>
                  <dt>Besteller</dt>
                  <dd>
                    {selectedSponsor?.partyDisplayName ?? "Noch auswählen"}
                  </dd>
                </div>
                <div>
                  <dt>Angebot</dt>
                  <dd>{selectedOffering?.name ?? "Nicht verfügbar"}</dd>
                </div>
                <div>
                  <dt>Menge</dt>
                  <dd>
                    {selectedOffering
                      ? `${quantity} ${quantityLabel(quantity, selectedOffering.unit)}`
                      : "–"}
                  </dd>
                </div>
                {selectedOffering?.piecesPerUnit ? (
                  <div>
                    <dt>Enthaltene Stückzahl</dt>
                    <dd>{quantity * selectedOffering.piecesPerUnit} Stück</dd>
                  </div>
                ) : null}
              </dl>
              <div className="commitment-summary__total">
                <span>Voraussichtlicher Gesamtbetrag</span>
                <strong data-testid="commitment-preview-total">
                  {selectedOffering
                    ? formatMoney(totalMinor, selectedOffering.currency)
                    : "–"}
                </strong>
                <small>
                  Der Core übernimmt beim Speichern den aktuellen Angebotspreis.
                </small>
              </div>
              <div ref={errorFocus} tabIndex={-1}>
                {localError && (
                  <StatusMessage tone="error">{localError}</StatusMessage>
                )}
                {deliveryEnabled && deferredDelivery && (
                  <p>
                    Lieferadresse und Zeitfenster fehlen im Entwurf. Vor der
                    Prüfung müssen sie ergänzt werden.
                  </p>
                )}
                {create.isError ? (
                  <StatusMessage tone="error">
                    {captureError(create.error)}
                  </StatusMessage>
                ) : null}
                {create.isError && deliveryEnabled && (
                  <Button
                    variant="secondary"
                    onClick={() => void context.refetch()}
                  >
                    Lieferfenster neu laden
                  </Button>
                )}
              </div>
              <div className="commitment-submit-choices">
                <div>
                  <Button
                    data-testid="commitment-save-draft"
                    formNoValidate
                    disabled={
                      create.isPending || !selectedSponsor || !selectedOffering
                    }
                    name="readiness"
                    type="submit"
                    value="draft"
                    variant="secondary"
                  >
                    {create.isPending
                      ? "Wird gespeichert …"
                      : "Als Entwurf speichern"}
                  </Button>
                  <small>Bleibt intern und kann später geprüft werden.</small>
                </div>
                <div>
                  <Button
                    data-testid="commitment-save-ready"
                    disabled={
                      create.isPending ||
                      !selectedSponsor ||
                      !selectedOffering ||
                      (deliveryEnabled &&
                        (deferredDelivery ||
                          !deliveryDefinition?.windows.length))
                    }
                    name="readiness"
                    type="submit"
                    value="review_ready"
                  >
                    {create.isPending
                      ? "Wird gespeichert …"
                      : "Prüfbereit erfassen"}
                  </Button>
                  <small>Erscheint sofort beim Charity-Admin.</small>
                </div>
              </div>
            </aside>
          </fieldset>
        </form>
      )}
    </div>
  );
}
