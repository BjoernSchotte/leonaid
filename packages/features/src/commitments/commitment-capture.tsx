/*
 * Order capture of the acquisition app (prototype pwa/Acquire.tsx
 * OrderFlow): Angebot → Lieferung → Prüfen, for one of the acquirer's
 * sponsors, then the confirmation.
 */
import { ArrowLeft, Check, Minus, Plus } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  type AcquisitionActivityWorkItemResponse,
  type CommitmentBuyerResponse,
  type CommitmentResponse,
  type ConfiguredOfferingResponse,
  type CreateCommitmentRequest,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  EmptyState,
  Field,
  Icon,
  Input,
  SkeletonRows,
  StatusMessage,
} from "@leonaid/ui";

import { useActionInUrl } from "../action-admin/action-location";
import {
  ActionChoice,
  SponsorRow,
  followInPage,
  sponsorHref,
  useScreenHeading,
  useSponsorBoard,
} from "../acquisition/pwa-common";
import type { SubmitOutcome } from "../offline/controller";
import { acceptPrice, bookAnyway } from "../offline/resolutions";
import { minimizeCaptureContext } from "../offline/read-cache";
import {
  STALE_READ_CACHE_TEXT,
  StaleReadCacheError,
  deviceCopyFetchedAt,
  readThrough,
  useOfflineRuntime,
} from "../offline/runtime";
import { formatDateTime } from "../shared/dates";
import { useLocationHref } from "../shared/location";
import { CompleteDraft } from "./complete-draft";
import {
  DeliveryFields,
  DeliverySummary,
  FullWindowConfirm,
  deliveryDraft,
  deliveryPayload,
  fullWindowSelected,
  hasDeliveryAddress,
  hasPartialDeliveryAddress,
  isFullWindowError,
  selectableWindows,
} from "./delivery-fields";
import { configuredWindowLabel } from "./order-format";
import { quantityLabel, unitLabels } from "./quantities";
import { PWA_BASE } from "@leonaid/ui/base-paths";

interface CommitmentCapturePageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

interface RecipientDraft {
  readonly city: string;
  readonly email: string;
  readonly postalCode: string;
  readonly recipientName: string;
  readonly streetLine1: string;
}

const STEPS = ["Angebot", "Lieferung", "Prüfen"] as const;
const MAX_QUANTITY = 1_000_000;

function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

function isPriceChange(error: unknown) {
  return (
    error instanceof ApiError &&
    error.detail.code === "commitment_price_changed"
  );
}

/** §10.2: "Der Preis für … ist jetzt … statt …". */
function priceChangeText(error: unknown) {
  const details = (error instanceof ApiError ? error.detail.details : null) as {
    readonly lines?: ReadonlyArray<{
      readonly quotedUnitPriceMinor?: number;
      readonly unitPriceMinor?: number;
    }>;
    readonly totalMinor?: number;
    readonly currency?: string;
  } | null;
  const line = details?.lines?.[0];
  const currency = details?.currency ?? "EUR";
  if (
    line?.unitPriceMinor === undefined ||
    line.quotedUnitPriceMinor === undefined ||
    details?.totalMinor === undefined
  ) {
    return "Der Preis hat sich inzwischen geändert.";
  }
  return `Der Preis ist jetzt ${formatMoney(line.unitPriceMinor, currency)} statt ${formatMoney(line.quotedUnitPriceMinor, currency)}. Die Bestellung kostet ${formatMoney(details.totalMinor, currency)}.`;
}

function captureError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.detail.code.startsWith("delivery_")) return error.detail.message;
    if (error.detail.code === "idempotency_incomplete") {
      return "Die erste Übermittlung wird noch verarbeitet. Warte kurz und versuche dieselbe Bestellung erneut.";
    }
    if (error.detail.code === "idempotency_conflict") {
      return "Die Bestellung wurde bereits mit anderen Angaben gespeichert. Öffne den Sponsor neu und prüfe die Eingabe.";
    }
    if (error.detail.code === "offering_not_available") {
      return "Das gewählte Angebot ist nicht mehr verfügbar. Lade die Angebote neu und wähle erneut.";
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
    city: sponsor?.city ?? "",
    email: sponsor?.email ?? "",
    postalCode: sponsor?.postalCode ?? "",
    recipientName: sponsor?.partyDisplayName ?? "",
    streetLine1: "",
  };
}

function hasRecipient(value: RecipientDraft) {
  return [
    value.recipientName,
    value.streetLine1,
    value.postalCode,
    value.city,
  ].every((item) => item.trim());
}

function Stepper({
  label,
  onChange,
  value,
}: {
  readonly label: string;
  readonly onChange: (value: number) => void;
  readonly value: number;
}) {
  // The field may be empty while typing; the last valid number stays the
  // value until the next one, and leaving the field shows it again.
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <div
      aria-labelledby="commitment-quantity-label"
      className="stepper"
      role="group"
    >
      <span className="field-label" id="commitment-quantity-label">
        {label}
      </span>
      <div className="stepper-controls">
        <button
          aria-label="Eine weniger"
          disabled={value <= 1}
          onClick={() => onChange(Math.max(1, value - 1))}
          type="button"
        >
          <Icon icon={Minus} size={20} />
        </button>
        <input
          aria-labelledby="commitment-quantity-label"
          className="stepper-value num"
          data-testid="commitment-quantity"
          id="commitment-quantity"
          inputMode="numeric"
          max={MAX_QUANTITY}
          min={1}
          onBlur={() => setText(String(value))}
          onChange={(event) => {
            setText(event.target.value);
            const next = Number.parseInt(event.target.value, 10);
            if (Number.isFinite(next) && next >= 1) {
              onChange(Math.min(MAX_QUANTITY, next));
            }
          }}
          type="number"
          value={text}
        />
        <button
          aria-label="Eine mehr"
          disabled={value >= MAX_QUANTITY}
          onClick={() => onChange(Math.min(MAX_QUANTITY, value + 1))}
          type="button"
        >
          <Icon icon={Plus} size={20} />
        </button>
      </div>
    </div>
  );
}

function StepList({ step }: { readonly step: number }) {
  return (
    <ol aria-label="Schritte" className="pwa-steps">
      {STEPS.map((label, index) => (
        <li
          aria-current={step === index + 1 ? "step" : undefined}
          className={
            step === index + 1
              ? "is-current"
              : step > index + 1
                ? "is-done"
                : undefined
          }
          key={label}
        >
          <span className="pwa-step-no">
            {step > index + 1 ? <Icon icon={Check} size={12} /> : index + 1}
          </span>
          {label}
        </li>
      ))}
    </ol>
  );
}

/** An order kept on the device: not yet (or not cleanly) at Core. */
interface QueuedOrder {
  readonly queued: Exclude<SubmitOutcome["state"], "accepted">;
  /** Why a queued order still waits (offline, sign-in, retry). */
  readonly reason?: "offline" | "paused" | "retry";
  readonly readyForReview: boolean;
  readonly totalMinor: number;
  readonly currency: string;
}

/** §12.3: "Bestellung gespeichert. Wird gesendet, …" (prototype copy). */
function QueuedConfirmation({
  actionId,
  buyer,
  order,
  sponsor,
}: {
  readonly actionId: string;
  readonly buyer: CommitmentBuyerResponse;
  readonly order: QueuedOrder;
  readonly sponsor: AcquisitionActivityWorkItemResponse | undefined;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    heading.current?.focus({ preventScroll: true });
  }, []);
  const decision = order.queued !== "queued" && order.queued !== "sent";
  const later =
    order.reason === "paused"
      ? "Wird gesendet, sobald du dich wieder angemeldet hast."
      : order.reason === "retry"
        ? "LeonAid ist gerade nicht erreichbar; die App versucht es gleich noch einmal."
        : "Wird gesendet, sobald du wieder online bist.";
  return (
    <section
      aria-labelledby="commitment-queued-heading"
      className="pwa-done"
      data-testid="commitment-queued"
    >
      <span aria-hidden="true" className="pwa-done-icon">
        <Icon icon={Check} size={20} />
      </span>
      <h1
        className="pwa-h1"
        id="commitment-queued-heading"
        ref={heading}
        tabIndex={-1}
      >
        Bestellung gespeichert
      </h1>
      <p className="muted">
        Für {buyer.displayName}, {formatMoney(order.totalMinor, order.currency)}
        .
      </p>
      <p className="small muted" data-testid="commitment-queued-text">
        {order.queued === "sent"
          ? "Die Bestellung ist bei LeonAid angekommen."
          : decision
            ? "Sie liegt auf diesem Gerät und braucht deine Entscheidung. Öffne die Warteschlange über das Netz-Symbol oben."
            : order.readyForReview
              ? `${later} Die Aktionsleitung prüft die Bestellung und stellt danach die Rechnung aus.`
              : `${later} Sie geht als Entwurf an LeonAid.`}
      </p>
      {sponsor ? (
        <a
          className={`${buttonClassName({ size: "lg", variant: "primary" })} pwa-wide`}
          href={sponsorHref(actionId, sponsor.assignmentId)}
          onClick={followInPage}
        >
          Zurück zu {sponsor.partyDisplayName}
        </a>
      ) : null}
    </section>
  );
}

function CaptureSuccess({
  actionId,
  client,
  commitment,
  onCompleted,
  sponsor,
  showDelivery,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly commitment: CommitmentResponse;
  readonly onCompleted: (order: CommitmentResponse) => void;
  readonly sponsor: AcquisitionActivityWorkItemResponse | undefined;
  readonly showDelivery: boolean;
}) {
  const ready = commitment.status === "review_ready";
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    heading.current?.focus({ preventScroll: true });
  }, [commitment.id, commitment.status]);
  const quantity = commitment.quantities
    .map(
      (item) =>
        `${new Intl.NumberFormat("de-DE").format(item.quantity)} ${quantityLabel(item.quantity, item.unit)}`,
    )
    .join(", ");
  return (
    <section
      aria-labelledby="commitment-success-heading"
      className="pwa-done"
      data-commitment-id={commitment.id}
      data-testid="commitment-success"
    >
      <span aria-hidden="true" className="pwa-done-icon">
        <Icon icon={Check} size={20} />
      </span>
      <h1
        className="pwa-h1"
        id="commitment-success-heading"
        ref={heading}
        tabIndex={-1}
      >
        {ready ? "Bestellung erfasst" : "Als Entwurf gesichert"}
      </h1>
      <p className="muted">
        {quantity ? `${quantity} für ` : "Für "}
        {commitment.buyer.displayName},{" "}
        {formatMoney(commitment.totalMinor, commitment.currency)}.
      </p>
      <p className="small muted">
        {ready
          ? "Die Aktionsleitung prüft die Bestellung und stellt danach die Rechnung aus."
          : "Die Bestellung ist gespeichert, aber noch nicht zur Prüfung freigegeben."}
      </p>
      {showDelivery ? <DeliverySummary order={commitment} /> : null}
      {!ready && commitment.status === "draft" ? (
        <CompleteDraft
          client={client}
          key={commitment.id}
          onCompleted={onCompleted}
          order={commitment}
        />
      ) : null}
      {sponsor ? (
        <a
          className={`${buttonClassName({ size: "lg", variant: "primary" })} pwa-wide`}
          href={sponsorHref(actionId, sponsor.assignmentId)}
          onClick={followInPage}
        >
          Zurück zu {sponsor.partyDisplayName}
        </a>
      ) : null}
      <a
        className={`${buttonClassName({ size: "lg", variant: "secondary" })} pwa-wide`}
        href={`${PWA_BASE}?action=${encodeURIComponent(actionId)}`}
        onClick={followInPage}
      >
        Zur Startseite
      </a>
    </section>
  );
}

export function CommitmentCapturePage({
  client,
  identity,
}: CommitmentCapturePageProps) {
  const memberships = useMemo(
    () => [
      ...new Map(
        identity.actionMemberships
          .filter((membership) => membership.role === "acquirer")
          .map((membership) => [membership.actionId, membership]),
      ).values(),
    ],
    [identity.actionMemberships],
  );
  const initialParameters = useMemo(
    () => new URLSearchParams(window.location.search),
    [],
  );
  const requestedActionId = initialParameters.get("action") ?? "";
  const [actionId, setActionId] = useState(
    memberships.some((membership) => membership.actionId === requestedActionId)
      ? requestedActionId
      : (memberships[0]?.actionId ?? ""),
  );
  useActionInUrl(actionId);
  // From the URL on every render: the sponsor picker links in-page.
  const href = useLocationHref();
  const assignmentId =
    new URLSearchParams(href.split("?")[1] ?? "").get("assignment") ?? "";
  const existingId = initialParameters.get("commitment") ?? "";
  const [step, setStep] = useState(1);
  const [offeringId, setOfferingId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [delivery, setDelivery] = useState(() => deliveryDraft());
  const [recipient, setRecipient] = useState<RecipientDraft>(() =>
    recipientFor(undefined),
  );
  const [stepError, setStepError] = useState("");
  const [showMissing, setShowMissing] = useState(false);
  const heading = useScreenHeading();
  // Each step change moves the focus to the step's heading (I3).
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const stepChanged = useRef(false);
  function goToStep(next: number) {
    stepChanged.current = true;
    setStep(next);
  }
  useEffect(() => {
    if (!stepChanged.current) return;
    stepChanged.current = false;
    stepHeading.current?.focus({ preventScroll: false });
  }, [step]);
  const [savedOrder, setSavedOrder] = useState<CommitmentResponse | null>(null);
  const [queuedOrder, setQueuedOrder] = useState<QueuedOrder | null>(null);
  const [confirmFull, setConfirmFull] = useState(false);
  // A queued order waiting for this screen's answer (full window, price).
  const pendingEntry = useRef<{
    readonly entryId: string;
    readonly choice: "window" | "price";
  } | null>(null);
  const appliedBuyer = useRef("");
  const commandId = useRef(crypto.randomUUID());
  const queries = useQueryClient();

  const runtime = useOfflineRuntime();
  const context = useQuery({
    enabled: Boolean(actionId),
    // Offers and windows come from the device copy without network
    // (specs/pwa-offline-queue §8.2).
    queryFn: () =>
      readThrough(
        runtime,
        "capture",
        actionId,
        () => client.getCommitmentCaptureContext(actionId),
        minimizeCaptureContext,
      ),
    queryKey: ["commitment-capture-context", actionId],
    refetchOnWindowFocus: false,
    // deviceCopyFetchedAt needs the object readThrough returned.
    structuralSharing: false,
  });
  const priceFrom = deviceCopyFetchedAt(context.data);
  const existing = useQuery({
    enabled: Boolean(actionId && existingId),
    queryKey: ["commitment", actionId, existingId],
    queryFn: () => client.getCommitment(actionId, existingId),
  });
  const sponsors = useSponsorBoard(client, actionId);
  const sponsor = sponsors.data?.workItems.find(
    (item) => item.assignmentId === assignmentId,
  );
  const offerings = context.data?.offerings ?? [];
  const offering = offerings.find((item) => item.id === offeringId);
  const buyer: CommitmentBuyerResponse | undefined = sponsor
    ? {
        displayName: sponsor.partyDisplayName,
        email: sponsor.email,
        partyKind: sponsor.partyKind,
        twentyId: sponsor.partyId,
      }
    : undefined;
  const configuration = context.data?.deliveryConfiguration;
  const deliveryEnabled = Boolean(configuration?.enabled);
  const completeDelivery =
    !configuration?.enabled ||
    (hasDeliveryAddress(delivery) &&
      selectableWindows(configuration).upcoming.some(
        (item) => item.id === delivery.windowId,
      ));

  useEffect(() => {
    if (offerings.length && !offering) setOfferingId(offerings[0]!.id);
  }, [offerings, offering]);

  // A new sponsor brings its own billing defaults and a new command.
  const buyerKey = buyer ? `${actionId}:${buyer.twentyId}` : "";
  useEffect(() => {
    if (!buyerKey || appliedBuyer.current === buyerKey) return;
    appliedBuyer.current = buyerKey;
    setRecipient(recipientFor(sponsor));
    setDelivery(deliveryDraft());
    setStep(1);
    commandId.current = crypto.randomUUID();
  }, [buyerKey]);

  const create = useMutation({
    mutationFn: async ({
      allowFullWindow = false,
      readyForReview,
      selected,
      selectedOffering,
    }: {
      readonly allowFullWindow?: boolean;
      readonly readyForReview: boolean;
      readonly selected: CommitmentBuyerResponse;
      readonly selectedOffering: ConfiguredOfferingResponse;
    }): Promise<CommitmentResponse | QueuedOrder> => {
      const body: CreateCommitmentRequest = {
        allowFullWindow,
        buyer: selected,
        ...(deliveryEnabled ? deliveryPayload(delivery) : {}),
        invoiceRecipient: {
          city: recipient.city.trim(),
          countryCode: "DE",
          email: recipient.email.trim() || null,
          postalCode: recipient.postalCode.trim(),
          recipientName: recipient.recipientName.trim(),
          streetLine1: recipient.streetLine1.trim(),
        },
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
      if (!runtime.enabled || !runtime.queue || !sponsor) {
        return client.createCommitment(actionId, body, {
          headers: { "Idempotency-Key": `poc081:${commandId.current}` },
        });
      }
      // Offline capture on: saved on the device first, sent at once when
      // online (specs/pwa-offline-queue §9.1); the price and window it was
      // made against are the entry's base (§9.3, §11.3).
      const chosenWindow = configuration?.windows.find(
        (item) => item.id === delivery.windowId,
      );
      const pending = pendingEntry.current;
      // An answer on this screen (FullWindowConfirm, the new price) changes
      // the entry already queued instead of capturing a second order.
      const outcome = pending
        ? await runtime.queue.resubmit(
            pending.entryId,
            (entry) =>
              entry.kind !== "commitment"
                ? entry
                : pending.choice === "price"
                  ? (acceptPrice(entry) ?? entry)
                  : bookAnyway(entry),
            // allowFullWindow is not in Core's hash; a new price is.
            { newKey: pending.choice === "price" },
          )
        : await runtime.queue.submit({
            actionId,
            assignmentId: sponsor.assignmentId,
            base: {
              unitPriceMinor: selectedOffering.unitPriceMinor,
              windowFullyBooked: chosenWindow?.fullyBooked ?? false,
              windowId: deliveryEnabled ? delivery.windowId || null : null,
            },
            kind: "commitment",
            party: {
              displayName: sponsor.partyDisplayName,
              id: sponsor.partyId,
              kind: sponsor.partyKind,
            },
            request: body,
          });
      pendingEntry.current = null;
      if (
        outcome.state === "accepted" &&
        outcome.result.kind === "commitment"
      ) {
        return outcome.result.response;
      }
      // Online, the window filled up or the price changed meanwhile: ask
      // here, as without the queue (§10.2), with the entry kept.
      const code = outcome.state === "conflict" ? outcome.error?.code : null;
      if (
        code === "delivery_window_full" ||
        code === "commitment_price_changed"
      ) {
        pendingEntry.current = {
          choice: code === "commitment_price_changed" ? "price" : "window",
          entryId: outcome.entryId,
        };
        throw new ApiError(409, {
          code,
          details: outcome.state === "conflict" ? outcome.error?.details : null,
          message:
            outcome.state === "conflict" ? (outcome.error?.message ?? "") : "",
          requestId: "",
        });
      }
      return {
        currency: selectedOffering.currency,
        queued: outcome.state === "accepted" ? "sent" : outcome.state,
        reason: outcome.state === "queued" ? outcome.reason : undefined,
        readyForReview,
        totalMinor: quantity * selectedOffering.unitPriceMinor,
      };
    },
    onSuccess: (saved) => {
      setConfirmFull(false);
      if ("queued" in saved) {
        setQueuedOrder(saved);
        return;
      }
      const order = saved;
      setSavedOrder(order);
      // The sponsor's status and the pipeline move with the order.
      void queries.invalidateQueries({
        queryKey: ["acquisition-activity-board", order.actionId],
      });
      void queries.invalidateQueries({ queryKey: ["dashboard"] });
      const url = new URL(window.location.href);
      url.searchParams.set("action", order.actionId);
      url.searchParams.set("commitment", order.id);
      window.history.replaceState({}, "", `${url.pathname}${url.search}`);
    },
    onError: (error) => {
      if (
        error instanceof ApiError &&
        error.detail.code.startsWith("delivery_")
      ) {
        void context.refetch();
      }
      // Switched to "ausgebucht" meanwhile: ask, then book anyway.
      setConfirmFull(isFullWindowError(error));
    },
  });
  const fullWindow = fullWindowSelected(configuration, delivery.windowId);

  function save(readyForReview: boolean, allowFullWindow = false) {
    if (!buyer || !offering) return;
    if (readyForReview && !allowFullWindow && fullWindow) {
      // A draft books nothing yet; its completion asks.
      setConfirmFull(true);
      return;
    }
    create.mutate({
      allowFullWindow,
      readyForReview,
      selected: buyer,
      selectedOffering: offering,
    });
  }

  function toReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (deliveryEnabled && hasPartialDeliveryAddress(delivery)) {
      setStepError("Bitte die Lieferadresse vollständig angeben.");
      return;
    }
    if (!hasRecipient(recipient)) {
      setShowMissing(true);
      setStepError("Bitte Name, Straße, PLZ und Ort für die Rechnung angeben.");
      return;
    }
    setShowMissing(false);
    setStepError("");
    goToStep(3);
  }

  if (queuedOrder && buyer) {
    return (
      <QueuedConfirmation
        actionId={actionId}
        buyer={buyer}
        order={queuedOrder}
        sponsor={sponsor}
      />
    );
  }
  const result = savedOrder ?? existing.data;
  const showDelivery = (order: CommitmentResponse) =>
    Boolean(
      deliveryEnabled ||
        order.deliveryRecipient ||
        order.deliveryWindowSnapshot ||
        order.deliveryContact,
    );
  if (result) {
    return (
      <CaptureSuccess
        actionId={actionId}
        client={client}
        commitment={result}
        onCompleted={setSavedOrder}
        showDelivery={showDelivery(result)}
        sponsor={sponsor}
      />
    );
  }
  if (existingId) {
    return existing.isError ? (
      <StatusMessage tone="error">
        <p>
          Diese Bestellung konnte nicht geöffnet werden. Du benötigst deine
          ursprüngliche Erfassung und eine weiterhin bestehende
          Sponsorzuordnung.
        </p>
        <Button onClick={() => void existing.refetch()} variant="secondary">
          Erneut versuchen
        </Button>
      </StatusMessage>
    ) : (
      <div aria-label="Bestellung wird geladen" role="status">
        <SkeletonRows rows={3} />
      </div>
    );
  }

  if (memberships.length === 0) {
    return (
      <EmptyState
        description="Sobald du einer Charity-Aktion als Akquisiteur zugeordnet bist, kannst du hier Bestellungen erfassen."
        headingLevel={2}
        title="Noch keine Akquise-Aktion"
      />
    );
  }
  if (context.isPending || sponsors.isPending) {
    return (
      <div aria-label="Bestellformular wird geladen" role="status">
        <SkeletonRows rows={4} />
      </div>
    );
  }
  if (context.isError || sponsors.isError) {
    return (
      <StatusMessage tone="error">
        <div>
          <strong>Bestellangaben nicht erreichbar</strong>
          <p>
            {context.error instanceof StaleReadCacheError ||
            sponsors.error instanceof StaleReadCacheError
              ? STALE_READ_CACHE_TEXT
              : "Prüfe deine Verbindung und lade die Angaben erneut."}
          </p>
          <Button
            onClick={() => {
              void context.refetch();
              void sponsors.refetch();
            }}
            variant="secondary"
          >
            Erneut laden
          </Button>
        </div>
      </StatusMessage>
    );
  }

  // No sponsor chosen: orders start from a sponsor, as in the prototype.
  if (!sponsor || !buyer) {
    const items = sponsors.data.workItems;
    return (
      <>
        <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
          Bestellung erfassen
        </h1>
        <ActionChoice
          actionId={actionId}
          memberships={memberships}
          onChange={(next) => {
            setActionId(next);
          }}
        />
        <p className="small muted">Für welchen Sponsor?</p>
        {items.length ? (
          <ul className="pwa-list" data-testid="commitment-sponsors">
            {items.map((item) => (
              <SponsorRow
                actionId={actionId}
                href={`${PWA_BASE}commitments/new?action=${encodeURIComponent(actionId)}&assignment=${encodeURIComponent(item.assignmentId)}`}
                item={item}
                key={item.assignmentId}
                userId={identity.userId}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            action={
              <a
                className={buttonClassName({ variant: "primary" })}
                href={`${PWA_BASE}sponsors?action=${encodeURIComponent(actionId)}&view=new`}
              >
                Sponsor erfassen
              </a>
            }
            description="Eine Bestellung gehört immer zu einem deiner Sponsoren."
            title="Noch kein Sponsor zugeordnet"
          />
        )}
      </>
    );
  }

  const total = (offering?.unitPriceMinor ?? 0) * quantity;
  const unitPlural = offering ? unitLabels[offering.unit][1] : "Stück";
  const chosenWindow = configuration?.windows.find(
    (item) => item.id === delivery.windowId,
  );
  const back = sponsorHref(actionId, sponsor.assignmentId);

  return (
    <>
      <a className="pwa-back" href={back} onClick={followInPage}>
        <Icon icon={ArrowLeft} size={18} /> Abbrechen
      </a>
      <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
        Bestellung für {sponsor.partyDisplayName}
      </h1>
      <StepList step={step} />
      <h2 className="sr-only" ref={stepHeading} tabIndex={-1}>
        Schritt {step} von {STEPS.length}: {STEPS[step - 1]}
      </h2>

      {step === 1 ? (
        <div className="stack">
          {offerings.length ? (
            <>
              <fieldset
                className="pwa-fieldset"
                data-testid="commitment-offering"
              >
                <legend className="field-label">Angebot</legend>
                <div className="pwa-options">
                  {offerings.map((item) => (
                    <label
                      className={`pwa-option${offeringId === item.id ? " is-checked" : ""}`}
                      key={item.id}
                    >
                      <input
                        checked={offeringId === item.id}
                        name="offering"
                        onChange={() => setOfferingId(item.id)}
                        type="radio"
                        value={item.id}
                      />
                      <span className="pwa-option-text">
                        {item.name}
                        <span className="small muted">
                          {item.piecesPerUnit
                            ? `${item.piecesPerUnit} Stück · `
                            : ""}
                          {formatMoney(item.unitPriceMinor, item.currency)} je{" "}
                          {unitLabels[item.unit][0]}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <Stepper
                label={`Anzahl ${unitPlural}`}
                onChange={setQuantity}
                value={quantity}
              />
              <p
                className="pwa-total num"
                data-testid="commitment-preview-total"
              >
                Summe {offering ? formatMoney(total, offering.currency) : "–"}
              </p>
              {priceFrom ? (
                <p className="small muted" data-testid="commitment-price-from">
                  {`Preis vom ${formatDateTime(priceFrom)}. Ändert er sich, fragt LeonAid dich vor dem Senden.`}
                </p>
              ) : null}
              <Button
                className="pwa-wide"
                disabled={!offering}
                onClick={() => goToStep(2)}
                size="lg"
                variant="primary"
              >
                Weiter
              </Button>
            </>
          ) : (
            <EmptyState
              description="Bitte die Aktionsleitung, Angebot und Zeitraum zu prüfen."
              title="Kein Angebot bestellbar"
            />
          )}
        </div>
      ) : null}

      {step === 2 ? (
        <form className="stack" noValidate onSubmit={toReview}>
          {deliveryEnabled && configuration ? (
            <DeliveryFields
              configuration={configuration}
              invoiceAddress={{
                city: recipient.city,
                countryCode: "DE",
                postalCode: recipient.postalCode,
                recipientName: recipient.recipientName,
                streetLine1: recipient.streetLine1,
              }}
              onChange={setDelivery}
              refresh={() => void context.refetch()}
              refreshing={context.isFetching}
              value={delivery}
            />
          ) : null}
          <fieldset className="pwa-fieldset stack">
            <legend className="field-label">Rechnung</legend>
            <p className="small muted">
              Die Rechnung geht später an diese Anschrift. Bezahlt wird per
              Überweisung.
            </p>
            <Field
              error={
                showMissing && !recipient.recipientName.trim()
                  ? "Bitte ausfüllen."
                  : undefined
              }
              label="Name"
              required
            >
              <Input
                autoComplete="organization"
                id="commitment-recipient-name"
                maxLength={200}
                onChange={(event) =>
                  setRecipient({
                    ...recipient,
                    recipientName: event.target.value,
                  })
                }
                value={recipient.recipientName}
              />
            </Field>
            <Field
              error={
                showMissing && !recipient.streetLine1.trim()
                  ? "Bitte ausfüllen."
                  : undefined
              }
              label="Straße und Hausnummer"
              required
            >
              <Input
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
                value={recipient.streetLine1}
              />
            </Field>
            <div className="pwa-two">
              <Field
                error={
                  showMissing && !recipient.postalCode.trim()
                    ? "Bitte ausfüllen."
                    : undefined
                }
                label="PLZ"
                required
              >
                <Input
                  autoComplete="postal-code"
                  id="commitment-postal-code"
                  maxLength={20}
                  onChange={(event) =>
                    setRecipient({
                      ...recipient,
                      postalCode: event.target.value,
                    })
                  }
                  value={recipient.postalCode}
                />
              </Field>
              <Field
                error={
                  showMissing && !recipient.city.trim()
                    ? "Bitte ausfüllen."
                    : undefined
                }
                label="Ort"
                required
              >
                <Input
                  autoComplete="address-level2"
                  id="commitment-city"
                  maxLength={120}
                  onChange={(event) =>
                    setRecipient({ ...recipient, city: event.target.value })
                  }
                  value={recipient.city}
                />
              </Field>
            </div>
            <Field label="Rechnungs-E-Mail" optional>
              <Input
                autoComplete="email"
                id="commitment-email"
                maxLength={320}
                onChange={(event) =>
                  setRecipient({ ...recipient, email: event.target.value })
                }
                type="email"
                value={recipient.email}
              />
            </Field>
          </fieldset>
          {stepError ? (
            <StatusMessage tone="error">
              <span id="commitment-step-error">{stepError}</span>
            </StatusMessage>
          ) : null}
          <div className="pwa-two">
            <Button onClick={() => goToStep(1)} size="lg" variant="secondary">
              Zurück
            </Button>
            <Button
              aria-describedby={stepError ? "commitment-step-error" : undefined}
              size="lg"
              type="submit"
              variant="primary"
            >
              Weiter
            </Button>
          </div>
        </form>
      ) : null}

      {step === 3 && offering ? (
        <div className="stack">
          <section className="pwa-card">
            <dl className="pwa-dl">
              <div>
                <dt>Angebot</dt>
                <dd>
                  {quantity} × {offering.name}
                </dd>
              </div>
              {deliveryEnabled ? (
                <>
                  <div>
                    <dt>Lieferung</dt>
                    <dd>
                      {chosenWindow
                        ? configuredWindowLabel(chosenWindow)
                        : "Noch kein Lieferfenster"}
                    </dd>
                  </div>
                  <div>
                    <dt>Adresse</dt>
                    <dd>
                      {hasDeliveryAddress(delivery)
                        ? `${delivery.streetLine1}, ${delivery.postalCode} ${delivery.city}`
                        : "Noch keine Lieferadresse"}
                    </dd>
                  </div>
                </>
              ) : null}
              <div>
                <dt>Rechnung</dt>
                <dd>
                  {recipient.recipientName}, {recipient.streetLine1},{" "}
                  {recipient.postalCode} {recipient.city}
                </dd>
              </div>
              <div>
                <dt>Summe</dt>
                <dd className="num">
                  <strong>{formatMoney(total, offering.currency)}</strong>
                </dd>
              </div>
            </dl>
          </section>
          <p className="small muted">
            LeonAid berechnet den verbindlichen Preis beim Speichern erneut.
          </p>
          {!completeDelivery ? (
            <StatusMessage tone="info">
              Ohne Lieferadresse und Lieferfenster kannst du die Bestellung nur
              als Entwurf speichern.
            </StatusMessage>
          ) : null}
          {create.isError && isPriceChange(create.error) ? (
            <StatusMessage tone="warning">
              <div className="stack" data-testid="commitment-price-changed">
                <p>{priceChangeText(create.error)}</p>
                <Button
                  data-testid="commitment-accept-price"
                  loading={create.isPending}
                  onClick={() => save(true)}
                  variant="primary"
                >
                  Neuen Preis übernehmen
                </Button>
                <p className="small muted">
                  Oder lass sie in der Warteschlange und entscheide später.
                </p>
              </div>
            </StatusMessage>
          ) : create.isError && !isFullWindowError(create.error) ? (
            <StatusMessage tone="error">
              {captureError(create.error)}
            </StatusMessage>
          ) : null}
          <div className="pwa-two">
            <Button
              disabled={create.isPending}
              onClick={() => goToStep(2)}
              size="lg"
              variant="secondary"
            >
              Zurück
            </Button>
            <Button
              data-testid="commitment-save-ready"
              disabled={!completeDelivery || context.isFetching}
              loading={create.isPending}
              onClick={() => save(true)}
              size="lg"
              variant="primary"
            >
              Verbindlich erfassen
            </Button>
          </div>
          <Button
            className="pwa-wide"
            data-testid="commitment-save-draft"
            disabled={create.isPending}
            onClick={() => save(false)}
            variant="ghost"
          >
            Als Entwurf speichern
          </Button>
        </div>
      ) : null}

      <FullWindowConfirm
        onCancel={() => {
          // The order stays in the queue as a decision (§10.2).
          setConfirmFull(false);
          if (pendingEntry.current) {
            setQueuedOrder({
              currency: offering?.currency ?? "EUR",
              queued: "conflict",
              readyForReview: true,
              totalMinor: total,
            });
            pendingEntry.current = null;
          }
          create.reset();
        }}
        onConfirm={() => save(true, true)}
        pending={create.isPending}
        window={
          confirmFull
            ? (fullWindow ??
              configuration?.windows.find(
                (item) => item.id === delivery.windowId,
              ))
            : undefined
        }
      />
    </>
  );
}
