import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarRange, Ban, Plus } from "lucide-react";
import { useId, useMemo, useState } from "react";

import {
  ApiError,
  type DeliveryConfigurationResponse,
  type DeliveryWindowRequest,
  type DeliveryWindowResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  Input,
  Modal,
  NextStep,
  ReadOnlyNotice,
  SkeletonRows,
  StatusMessage,
  Switch,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

interface Props {
  readonly client: LeonAidApiClient;
  readonly actionId: string;
  readonly actionName?: string;
  readonly startsOn: string;
  readonly endsOn: string;
  /** Read-only (archived action, or no ordering): no changes offered. */
  readonly disabled?: boolean;
  /** Why it is read-only; picks the "Nur lesen." text. */
  readonly disabledReason?: "archived" | "no-ordering";
  /** Read the booked boxes per window (the action takes orders). */
  readonly ordering?: boolean;
  /** Standalone use (new action): an own heading above the windows. */
  readonly heading?: boolean;
}

const TIMEZONES = ["Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "UTC"];

/** "Fr 04.12. · 08–10 Uhr" (prototype window label). */
export function windowLabel(window: {
  readonly deliveryOn: string;
  readonly startsAt: string;
  readonly endsAt: string;
}) {
  const day = new Date(`${window.deliveryOn}T12:00:00Z`);
  const weekday = new Intl.DateTimeFormat("de-DE", {
    weekday: "short",
    timeZone: "UTC",
  })
    .format(day)
    .replace(".", "");
  const [, month, date] = window.deliveryOn.split("-");
  return `${weekday} ${date}.${month}. · ${window.startsAt.slice(0, 5)}–${window.endsAt.slice(0, 5)} Uhr`;
}

function windowRequest(window: DeliveryWindowResponse): DeliveryWindowRequest {
  return {
    id: window.id,
    deliveryOn: window.deliveryOn,
    startsAt: window.startsAt,
    endsAt: window.endsAt,
    retired: window.retired,
  };
}

/** Whether the window has begun, compared in the action's time zone. */
export function windowStarted(
  window: Pick<DeliveryWindowResponse, "deliveryOn" | "startsAt">,
  timezone: string,
  now: Date = new Date(),
) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .map((part) => [part.type, part.value]),
  );
  const local = `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  return `${window.deliveryOn} ${window.startsAt.slice(0, 5)}` <= local;
}

function sorted(windows: readonly DeliveryWindowResponse[]) {
  return [...windows].sort(
    (a, b) =>
      a.deliveryOn.localeCompare(b.deliveryOn) ||
      a.startsAt.localeCompare(b.startsAt),
  );
}

/**
 * Lieferfenster (prototype Campaigns.tsx Windows). Saved windows stay as
 * they are: a change is a new window, an unwanted one is retired.
 * Every change saves the whole configuration with its revision.
 */
export function DeliverySection(props: Props) {
  const queryKey = ["delivery-configuration", props.actionId] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => props.client.getDeliveryConfiguration(props.actionId),
    refetchOnWindowFocus: false,
    retry: false,
  });
  const bookings = useQuery({
    enabled: Boolean(props.ordering),
    queryKey: ["commitments", props.actionId],
    queryFn: () => props.client.listCommitments(props.actionId),
    retry: false,
  });
  const booked = useMemo(() => {
    const boxes = new Map<string, number>();
    for (const { commitment } of bookings.data?.items ?? []) {
      if (!commitment.deliveryWindowId || commitment.status === "cancelled")
        continue;
      boxes.set(
        commitment.deliveryWindowId,
        (boxes.get(commitment.deliveryWindowId) ?? 0) + commitment.totalBoxes,
      );
    }
    return boxes;
  }, [bookings.data]);

  const heading = props.heading ? (
    <h2 className="tab-h2" id={`delivery-heading-${props.actionId}`}>
      Lieferung planen
    </h2>
  ) : null;

  if (query.isPending) {
    return (
      <section className="stack" aria-busy="true">
        {heading}
        <SkeletonRows rows={3} />
      </section>
    );
  }
  if (query.isError) {
    return (
      <section className="stack">
        {heading}
        <ErrorState
          onRetry={() => void query.refetch()}
          title="Die Lieferfenster konnten nicht geladen werden"
        >
          Der Server hat nicht geantwortet. Prüfen Sie die Verbindung und
          versuchen Sie es erneut.
        </ErrorState>
      </section>
    );
  }
  return (
    <DeliveryWindows
      {...props}
      booked={bookings.isSuccess ? booked : undefined}
      config={query.data}
      heading={heading}
      queryKey={queryKey}
    />
  );
}

function DeliveryWindows({
  actionId,
  actionName,
  booked,
  client,
  config,
  disabled = false,
  disabledReason = "archived",
  endsOn,
  heading,
  queryKey,
  startsOn,
}: Omit<Props, "heading"> & {
  readonly booked?: ReadonlyMap<string, number>;
  readonly config: DeliveryConfigurationResponse;
  readonly heading: React.ReactNode;
  readonly queryKey: readonly unknown[];
}) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const [adding, setAdding] = useState(false);
  const [pausing, setPausing] = useState<DeliveryWindowResponse>();
  const [enabling, setEnabling] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const windows = sorted(config.windows);
  const open = windows.filter((window) => !window.retired);

  /** The "ausgebucht" switch saves at once and keeps the form revision. */
  async function setFullyBooked(
    window: DeliveryWindowResponse,
    fullyBooked: boolean,
  ) {
    setPending(true);
    setError(undefined);
    try {
      const result = await client.setDeliveryWindowFullyBooked(
        actionId,
        window.id,
        { fullyBooked },
      );
      cache.setQueryData(queryKey, result);
      await cache.invalidateQueries({
        queryKey: ["commitment-capture-context", actionId],
      });
      toast?.show({
        title: fullyBooked
          ? `${windowLabel(window)} ist als ausgebucht markiert.`
          : `${windowLabel(window)} ist wieder buchbar.`,
        tone: "success",
      });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409)
        await cache.invalidateQueries({ queryKey });
      setError(actionErrorMessage(cause).message);
    } finally {
      setPending(false);
    }
  }

  /** Saves the configuration; false when it failed (message shown). */
  async function save(
    change: Partial<
      Pick<DeliveryConfigurationResponse, "enabled" | "timezone">
    >,
    nextWindows: DeliveryWindowRequest[],
    done: string,
  ): Promise<boolean> {
    setPending(true);
    setError(undefined);
    try {
      const result = await client.saveDeliveryConfiguration(actionId, {
        expectedRevision: config.revision,
        enabled: change.enabled ?? config.enabled,
        timezone: change.timezone ?? config.timezone,
        windows: nextWindows,
      });
      cache.setQueryData(queryKey, result);
      await cache.invalidateQueries({
        queryKey: ["commitment-capture-context", actionId],
      });
      toast?.show({ title: done, tone: "success" });
      return true;
    } catch (cause) {
      const conflict =
        cause instanceof ApiError &&
        cause.detail.code === "delivery_configuration_conflict";
      if (conflict) await cache.invalidateQueries({ queryKey });
      setError(
        conflict
          ? "Die Lieferfenster wurden inzwischen geändert. Der aktuelle Stand ist geladen; Ihre Eingaben bleiben erhalten. Prüfen Sie sie und speichern Sie erneut."
          : actionErrorMessage(cause).message,
      );
      return false;
    } finally {
      setPending(false);
    }
  }

  const addButton = (
    <Button
      disabled={pending}
      icon={Plus}
      onClick={() => setAdding(true)}
      variant="primary"
    >
      Lieferfenster hinzufügen
    </Button>
  );

  return (
    <section
      aria-labelledby={heading ? `delivery-heading-${actionId}` : undefined}
      className="stack delivery-windows"
    >
      {heading}
      {disabled ? (
        <ReadOnlyNotice data-testid="delivery-read-only">
          {disabledReason === "no-ordering"
            ? "Lieferfenster gibt es nur für Aktionen mit Bestellungen. Aktivieren Sie unter „Bearbeiten“ die Funktion Bestellungen."
            : "Die Lieferfenster der archivierten Aktion bleiben nachvollziehbar, lassen sich aber nicht mehr ändern."}
        </ReadOnlyNotice>
      ) : open.length === 0 ? (
        <NextStep
          action={addButton}
          consequence="Erstes Lieferfenster anlegen. Sponsoren wählen beim Bestellen eines dieser Fenster; vor dem Einplanen der Aktion ist mindestens ein zukünftiges Fenster nötig."
          data-testid="delivery-next-step"
        />
      ) : !config.enabled ? (
        <NextStep
          action={
            <Button
              data-testid="delivery-enable"
              disabled={pending}
              onClick={() => setEnabling(true)}
              variant="primary"
            >
              Lieferplanung aktivieren
            </Button>
          }
          alternatives={
            <Button
              disabled={pending}
              icon={Plus}
              onClick={() => setAdding(true)}
              variant="ghost"
            >
              Lieferfenster hinzufügen
            </Button>
          }
          consequence="Lieferplanung aktivieren. Danach brauchen neue verbindliche Bestellungen eine Lieferadresse und ein freies Fenster."
          data-testid="delivery-next-step"
        />
      ) : (
        <div className="tab-head">
          <p className="muted small">
            Sponsoren wählen beim Bestellen eines dieser Fenster. Alle Zeiten
            gelten in der Zeitzone {config.timezone}.
          </p>
          {addButton}
        </div>
      )}

      {error && !adding ? (
        <StatusMessage tone="error">
          <span data-testid="delivery-error">{error}</span>
        </StatusMessage>
      ) : null}

      {config.enabled && open.length === 0 && windows.length > 0 ? (
        <div className="callout tone-warn" role="status">
          <Icon icon={AlertTriangle} size={16} />
          <span>
            Alle Fenster sind stillgelegt. Ohne freies Lieferfenster können
            keine neuen verbindlichen Bestellungen abgeschlossen werden.
          </span>
        </div>
      ) : null}

      {windows.length === 0 ? (
        <EmptyState
          description="Lieferfenster legen fest, wann geliefert wird. Ein Entwurf darf ohne Fenster gespeichert bleiben."
          headingLevel={3}
          icon={CalendarRange}
          title="Noch keine Lieferfenster"
        />
      ) : (
        <div
          aria-label={`Lieferfenster${actionName ? ` von ${actionName}` : ""}`}
          className="table-wrap"
          role="region"
          tabIndex={0}
        >
          <table className="table" data-testid="delivery-windows">
            <caption className="sr-only">
              Lieferfenster{actionName ? ` von ${actionName}` : ""}
            </caption>
            <thead>
              <tr>
                <th scope="col">Zeitraum</th>
                <th scope="col">Status</th>
                {!disabled ? <th scope="col">Ausgebucht</th> : null}
                {booked ? (
                  <th className="right" scope="col">
                    Gebuchte Boxen
                  </th>
                ) : null}
                <th scope="col">
                  <span className="sr-only">Befehle</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {windows.map((window) => (
                <tr
                  data-retired={window.retired || undefined}
                  data-testid={`delivery-window-${window.id}`}
                  key={window.id}
                >
                  <td className={window.retired ? "is-struck" : undefined}>
                    {windowLabel(window)}
                  </td>
                  <td>
                    {window.retired ? (
                      <Badge tone="neutral">Stillgelegt</Badge>
                    ) : window.fullyBooked ? (
                      <Badge tone="warn">Ausgebucht</Badge>
                    ) : (
                      <Badge tone="ok">Buchbar</Badge>
                    )}
                  </td>
                  {!disabled ? (
                    <td>
                      {!window.retired &&
                      !windowStarted(window, config.timezone) ? (
                        <Switch
                          aria-label={`${windowLabel(window)} ausgebucht`}
                          checked={window.fullyBooked}
                          data-testid={`delivery-window-full-${window.id}`}
                          disabled={pending}
                          onChange={(event) =>
                            void setFullyBooked(window, event.target.checked)
                          }
                        />
                      ) : null}
                    </td>
                  ) : null}
                  {booked ? (
                    <td className="right num">{booked.get(window.id) ?? 0}</td>
                  ) : null}
                  <td className="right">
                    {!window.retired && !disabled ? (
                      <Button
                        aria-label={`${windowLabel(window)} stilllegen`}
                        disabled={pending}
                        icon={Ban}
                        onClick={() => setPausing(window)}
                        size="sm"
                        variant="ghost"
                      >
                        Stilllegen
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small subtle table-note">
            Gespeicherte Fenster bleiben unverändert, damit bestehende
            Bestellungen ihren Zeitraum behalten. Für einen anderen Termin legen
            Sie das Fenster still und legen ein neues an.
          </p>
          {!disabled ? (
            <p className="small subtle table-note">
              Ein ausgebuchtes Fenster ist im öffentlichen Bestellformular
              gesperrt. Admin und Akquise können es nach einer Rückfrage
              trotzdem buchen. Stilllegen hebt „Ausgebucht“ auf.
            </p>
          ) : null}
        </div>
      )}

      <WindowModal
        endsOn={endsOn}
        lockedTimezone={windows.length > 0 ? config.timezone : undefined}
        onClose={() => setAdding(false)}
        onSave={(window, timezone) =>
          save(
            { timezone },
            [
              ...config.windows.map(windowRequest),
              { ...window, retired: false },
            ],
            `Lieferfenster ${windowLabel(window)} angelegt.`,
          )
        }
        open={adding}
        pending={pending}
        startsOn={startsOn}
        timezone={config.timezone}
        error={adding ? error : undefined}
      />
      <ConfirmDialog
        confirmLabel="Fenster stilllegen"
        description={
          pausing
            ? `${windowLabel(pausing)} wird im Bestellformular und in der Akquise nicht mehr angeboten. Bestehende Bestellungen${booked?.get(pausing.id) ? ` (${booked.get(pausing.id)} gebuchte Boxen)` : ""} behalten ihren Zeitraum. Das lässt sich nicht rückgängig machen; legen Sie bei Bedarf ein neues Fenster an.`
            : ""
        }
        onConfirm={() => {
          if (!pausing) return;
          void save(
            {},
            config.windows.map((window) => ({
              ...windowRequest(window),
              retired: window.retired || window.id === pausing.id,
            })),
            `${windowLabel(pausing)} ist stillgelegt.`,
          ).then(() => setPausing(undefined));
        }}
        onOpenChange={(next) => {
          if (!next && !pending) setPausing(undefined);
        }}
        open={Boolean(pausing)}
        pending={pending}
        title="Lieferfenster stilllegen?"
        tone="danger"
      />
      <ConfirmDialog
        confirmLabel="Lieferplanung aktivieren"
        description="Neue verbindliche Bestellungen brauchen danach eine Lieferadresse und ein freies Lieferfenster. Die Lieferplanung bleibt für diese Aktion aktiv."
        onConfirm={() => {
          void save(
            { enabled: true },
            config.windows.map(windowRequest),
            "Lieferplanung ist aktiv.",
          ).then(() => setEnabling(false));
        }}
        onOpenChange={(next) => {
          if (!next && !pending) setEnabling(false);
        }}
        open={enabling}
        pending={pending}
        title="Lieferplanung aktivieren?"
      />
    </section>
  );
}

function WindowModal({
  endsOn,
  error,
  lockedTimezone,
  onClose,
  onSave,
  open,
  pending,
  startsOn,
  timezone: savedTimezone,
}: {
  readonly endsOn: string;
  readonly error?: string;
  /** Saved windows fix the time zone. */
  readonly lockedTimezone?: string;
  readonly onClose: () => void;
  readonly onSave: (
    window: Omit<DeliveryWindowRequest, "id" | "retired">,
    timezone: string,
  ) => Promise<boolean>;
  readonly open: boolean;
  readonly pending: boolean;
  readonly startsOn: string;
  readonly timezone: string;
}) {
  const formId = useId();
  const [day, setDay] = useState("");
  const [from, setFrom] = useState("09:00");
  const [to, setTo] = useState("11:00");
  const [timezone, setTimezone] = useState(savedTimezone);
  const [submitted, setSubmitted] = useState(false);
  const dayError = !day
    ? "Bitte einen Tag wählen."
    : day < startsOn || day > endsOn
      ? "Der Tag muss im Zeitraum der Aktion liegen."
      : "";
  const timeError = from >= to ? "Das Ende muss nach dem Beginn liegen." : "";

  function close() {
    setDay("");
    setFrom("09:00");
    setTo("11:00");
    setSubmitted(false);
    onClose();
  }

  return (
    <Modal
      description="Änderungen gelten sofort für Akquise und öffentliches Bestellformular."
      footer={
        <>
          <Button disabled={pending} onClick={close} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="delivery-window-save"
            form={formId}
            loading={pending}
            type="submit"
            variant="primary"
          >
            Speichern
          </Button>
        </>
      }
      onClose={() => {
        if (!pending) close();
      }}
      open={open}
      title="Lieferfenster hinzufügen"
    >
      <form
        className="form-grid"
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(true);
          if (dayError || timeError) return;
          void onSave(
            { deliveryOn: day, startsAt: from, endsAt: to },
            lockedTimezone ?? timezone,
          ).then((saved) => {
            if (saved) close();
          });
        }}
      >
        <Field error={submitted ? dayError : undefined} label="Tag">
          <Input
            data-testid="delivery-window-day"
            max={endsOn}
            min={startsOn}
            onChange={(event) => setDay(event.target.value)}
            type="date"
            value={day}
          />
        </Field>
        <div className="form-row">
          <Field label="Von">
            <Input
              data-testid="delivery-window-from"
              onChange={(event) => setFrom(event.target.value)}
              type="time"
              value={from}
            />
          </Field>
          <Field error={submitted ? timeError : undefined} label="Bis">
            <Input
              data-testid="delivery-window-to"
              onChange={(event) => setTo(event.target.value)}
              type="time"
              value={to}
            />
          </Field>
        </div>
        {lockedTimezone ? (
          <p className="small muted">
            Zeitzone {lockedTimezone}; sie bleibt für gespeicherte Fenster fest.
          </p>
        ) : (
          <Field
            hint="Alle Uhrzeiten dieser Aktion gelten in dieser Zeitzone. Nach dem ersten Fenster bleibt sie fest."
            label="Zeitzone"
          >
            <select
              className="input select"
              data-testid="delivery-window-timezone"
              onChange={(event) => setTimezone(event.target.value)}
              value={timezone}
            >
              {[...new Set([timezone, ...TIMEZONES])].map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </Field>
        )}
        {error ? (
          <StatusMessage tone="error">
            <span>{error}</span>
          </StatusMessage>
        ) : null}
      </form>
    </Modal>
  );
}
