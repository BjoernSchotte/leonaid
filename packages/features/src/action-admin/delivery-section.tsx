import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  ApiError,
  type DeliveryConfigurationResponse,
  type DeliveryWindowRequest,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

interface Props {
  client: LeonAidApiClient;
  actionId: string;
  startsOn: string;
  endsOn: string;
  disabled?: boolean;
}

interface WindowDraft extends DeliveryWindowRequest {
  key: string;
  retired: boolean;
}
interface Day {
  key: string;
  date: string;
  windows: WindowDraft[];
}

function daysFor(config: DeliveryConfigurationResponse): Day[] {
  return [...new Set(config.windows.map((window) => window.deliveryOn))]
    .sort()
    .map((date) => ({
      key: date,
      date,
      windows: config.windows
        .filter((window) => window.deliveryOn === date)
        .sort((a, b) => a.startsAt.localeCompare(b.startsAt))
        .map((window) => ({ ...window, key: window.id })),
    }));
}

function newWindow(date: string): WindowDraft {
  return {
    key: crypto.randomUUID(),
    deliveryOn: date,
    startsAt: "",
    endsAt: "",
    retired: false,
  };
}

function displayDate(date: string): string {
  return new Intl.DateTimeFormat("de-DE", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}

export function DeliverySection(props: Props) {
  const query = useQuery({
    queryKey: ["delivery-configuration", props.actionId],
    queryFn: () => props.client.getDeliveryConfiguration(props.actionId),
    refetchOnWindowFocus: false,
    retry: false,
  });
  if (query.isPending)
    return <StatusMessage>Lieferplanung wird geladen …</StatusMessage>;
  if (query.isError)
    return (
      <StatusMessage tone="error">
        Die Lieferplanung konnte nicht geladen werden.
        <Button variant="secondary" onClick={() => void query.refetch()}>
          Erneut versuchen
        </Button>
      </StatusMessage>
    );
  return (
    <DeliveryEditor key={props.actionId} {...props} initial={query.data} />
  );
}

function DeliveryEditor({
  initial,
  client,
  actionId,
  startsOn,
  endsOn,
  disabled = false,
}: Props & { initial: DeliveryConfigurationResponse }) {
  const cache = useQueryClient();
  const [saved, setSaved] = useState(initial);
  const [enabled, setEnabled] = useState(initial.enabled);
  const [timezone, setTimezone] = useState(initial.timezone);
  const [days, setDays] = useState(() => daysFor(initial));
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{
    error: boolean;
    text: string;
    conflict?: boolean;
  }>();
  const availableCount = days
    .flatMap((day) => day.windows)
    .filter((window) => !window.retired).length;
  const locked = disabled || pending;

  function updateDay(key: string, change: Partial<Day>) {
    setDays((current) =>
      current.map((day) => (day.key === key ? { ...day, ...change } : day)),
    );
    setFeedback(undefined);
  }

  function updateWindow(day: Day, key: string, change: Partial<WindowDraft>) {
    updateDay(day.key, {
      windows: day.windows.map((window) =>
        window.key === key ? { ...window, ...change } : window,
      ),
    });
  }

  async function reconcile() {
    setPending(true);
    try {
      const latest = await client.getDeliveryConfiguration(actionId);
      const additions = days
        .map((day) => ({
          ...day,
          windows: day.windows.filter((window) => !window.id),
        }))
        .filter((day) => day.windows.length);
      if (
        latest.windows.length > 0 &&
        timezone !== latest.timezone &&
        additions.length
      ) {
        setFeedback({
          error: true,
          conflict: true,
          text: `Die gespeicherte Zeitzone ist inzwischen ${latest.timezone}. Deine neuen Zeiten bleiben in ${timezone} erhalten. Gleiche sie im aktuellen Stand ab, bevor du speicherst.`,
        });
        return;
      }
      const retireIds = new Set(
        days
          .flatMap((day) => day.windows)
          .filter((window) => window.retired)
          .map((window) => window.id),
      );
      const merged = daysFor(latest).map((day) => ({
        ...day,
        windows: day.windows.map((window) => ({
          ...window,
          retired: window.retired || retireIds.has(window.id),
        })),
      }));
      for (const addition of additions) {
        const existing = merged.find((day) => day.date === addition.date);
        if (existing) existing.windows.push(...addition.windows);
        else merged.push(addition);
      }
      setDays(merged);
      setSaved(latest);
      if (latest.enabled) setEnabled(true);
      if (latest.windows.length) setTimezone(latest.timezone);
      setFeedback({
        error: false,
        text: "Aktueller Stand geladen. Deine neuen Fenster und vorgesehenen Stilllegungen bleiben erhalten. Prüfe die gemeinsame Planung und speichere erneut.",
      });
    } catch {
      setFeedback({
        error: true,
        conflict: true,
        text: "Der aktuelle Stand konnte nicht geladen werden. Deine Eingaben bleiben erhalten; bitte erneut versuchen.",
      });
    } finally {
      setPending(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (locked) return;
    if (
      days.some((day) => !day.date || !day.windows.length) ||
      new Set(days.map((day) => day.date)).size !== days.length
    ) {
      setFeedback({
        error: true,
        text: "Lege jeden Liefertag einmal an und ergänze mindestens ein Zeitfenster je Tag.",
      });
      return;
    }
    setPending(true);
    setFeedback(undefined);
    try {
      const result = await client.saveDeliveryConfiguration(actionId, {
        expectedRevision: saved.revision,
        enabled,
        timezone,
        windows: days.flatMap((day) =>
          day.windows.map((window) => ({
            ...(window.id ? { id: window.id } : {}),
            deliveryOn: day.date,
            startsAt: window.startsAt,
            endsAt: window.endsAt,
            retired: window.retired,
          })),
        ),
      });
      setSaved(result);
      setEnabled(result.enabled);
      setTimezone(result.timezone);
      setDays(daysFor(result));
      cache.setQueryData(["delivery-configuration", actionId], result);
      await cache.invalidateQueries({
        queryKey: ["commitment-capture-context", actionId],
      });
      setFeedback({
        error: false,
        text: "Lieferplanung gespeichert. Die Fenster gelten für Akquise und öffentliche Bestellungen.",
      });
    } catch (error) {
      const conflict =
        error instanceof ApiError &&
        error.detail.code === "delivery_configuration_conflict";
      setFeedback({
        error: true,
        conflict,
        text: conflict
          ? "Die Lieferplanung wurde inzwischen geändert. Deine Eingaben bleiben erhalten. Vergleiche sie mit dem aktuellen Stand."
          : error instanceof ApiError
            ? error.detail.message
            : "Speichern ist gerade nicht möglich. Deine Eingaben bleiben erhalten; bitte erneut versuchen.",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="action-edit-section" aria-labelledby="delivery-heading">
      <header>
        <div>
          <h2 id="delivery-heading">Lieferung planen</h2>
          <p>
            Lege Tage und Zeitfenster für die Krapfentaxi-Lieferungen fest. Alle
            Uhrzeiten gelten in der gewählten Zeitzone.
          </p>
        </div>
      </header>
      <form onSubmit={(event) => void save(event)} className="delivery-editor">
        <fieldset disabled={locked}>
          <legend className="sr-only">Lieferkonfiguration</legend>
          {saved.enabled ? (
            <p>
              Lieferplanung ist aktiv. Neue verbindliche Bestellungen benötigen
              eine Lieferadresse und ein verfügbares Zeitfenster.
            </p>
          ) : (
            <label className="delivery-check">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              <span>Lieferplanung für diese Aktion aktivieren</span>
            </label>
          )}
          <label className="action-field delivery-timezone">
            <span>Zeitzone</span>
            <input
              aria-label="Zeitzone"
              list="delivery-timezones"
              value={timezone}
              readOnly={saved.windows.length > 0}
              required
              onChange={(event) => setTimezone(event.target.value)}
            />
            <datalist id="delivery-timezones">
              <option value="Europe/Berlin" />
              <option value="Europe/Vienna" />
              <option value="Europe/Zurich" />
              <option value="UTC" />
            </datalist>
            {saved.windows.length > 0 && (
              <small>Die Zeitzone bleibt für gespeicherte Termine fest.</small>
            )}
          </label>
          {days.length === 0 && (
            <p className="delivery-empty">
              Noch keine Lieferfenster. Ein Entwurf darf so gespeichert bleiben.
              Vor dem Einplanen oder Aktivieren der Aktion ist mindestens ein
              zukünftiges Fenster nötig.
            </p>
          )}
          {days.map((day, index) => {
            const persisted = day.windows.some((window) => window.id);
            return (
              <fieldset className="delivery-day" key={day.key}>
                <legend>
                  {persisted
                    ? displayDate(day.date)
                    : `Neuer Liefertag ${index + 1}`}
                </legend>
                {!persisted && (
                  <label className="action-field delivery-date">
                    <span>Datum</span>
                    <input
                      aria-label={`Datum für Liefertag ${index + 1}`}
                      type="date"
                      required
                      min={startsOn}
                      max={endsOn}
                      value={day.date}
                      onChange={(event) =>
                        updateDay(day.key, { date: event.target.value })
                      }
                    />
                  </label>
                )}
                {day.windows.map((window, slot) => {
                  const retired = saved.windows.some(
                    (existing) => existing.id === window.id && existing.retired,
                  );
                  return (
                    <div
                      className="delivery-window"
                      key={window.key}
                      data-retired={window.retired || undefined}
                    >
                      {window.id ? (
                        <div className="delivery-window-time">
                          <strong>
                            {window.startsAt.slice(0, 5)}–
                            {window.endsAt.slice(0, 5)} Uhr
                          </strong>
                          <span>
                            {retired
                              ? "Stillgelegt"
                              : window.retired
                                ? "Wird stillgelegt"
                                : "Gespeicherter Termin"}
                          </span>
                        </div>
                      ) : (
                        <div className="delivery-window-inputs">
                          <label className="action-field">
                            <span>Beginn</span>
                            <input
                              aria-label={`Beginn ${slot + 1} am Liefertag ${index + 1}`}
                              type="time"
                              required
                              value={window.startsAt.slice(0, 5)}
                              onChange={(event) =>
                                updateWindow(day, window.key, {
                                  startsAt: event.target.value,
                                })
                              }
                            />
                          </label>
                          <label className="action-field">
                            <span>Ende</span>
                            <input
                              aria-label={`Ende ${slot + 1} am Liefertag ${index + 1}`}
                              type="time"
                              required
                              value={window.endsAt.slice(0, 5)}
                              onChange={(event) =>
                                updateWindow(day, window.key, {
                                  endsAt: event.target.value,
                                })
                              }
                            />
                          </label>
                        </div>
                      )}
                      {window.id ? (
                        !retired && (
                          <label className="delivery-check">
                            <input
                              type="checkbox"
                              checked={Boolean(window.retired)}
                              onChange={(event) =>
                                updateWindow(day, window.key, {
                                  retired: event.target.checked,
                                })
                              }
                            />
                            <span>
                              {window.startsAt.slice(0, 5)}–
                              {window.endsAt.slice(0, 5)} Uhr stilllegen
                            </span>
                          </label>
                        )
                      ) : (
                        <Button
                          variant="ghost"
                          aria-label={`Zeitfenster ${slot + 1} am Liefertag ${index + 1} entfernen`}
                          onClick={() =>
                            updateDay(day.key, {
                              windows: day.windows.filter(
                                (item) => item.key !== window.key,
                              ),
                            })
                          }
                        >
                          Entfernen
                        </Button>
                      )}
                    </div>
                  );
                })}
                <div className="action-inline-actions">
                  <Button
                    variant="secondary"
                    onClick={() =>
                      updateDay(day.key, {
                        windows: [...day.windows, newWindow(day.date)],
                      })
                    }
                  >
                    Zeitfenster hinzufügen
                  </Button>
                  {!persisted && (
                    <Button
                      variant="ghost"
                      onClick={() =>
                        setDays((current) =>
                          current.filter((item) => item.key !== day.key),
                        )
                      }
                    >
                      Liefertag entfernen
                    </Button>
                  )}
                </div>
              </fieldset>
            );
          })}
          <div className="action-inline-actions">
            <Button
              variant="secondary"
              onClick={() =>
                setDays((current) => [
                  ...current,
                  {
                    key: crypto.randomUUID(),
                    date: "",
                    windows: [newWindow("")],
                  },
                ])
              }
            >
              Weiteren Tag hinzufügen
            </Button>
          </div>
          <p className="action-form-help">
            Gespeicherte Termine bleiben unverändert. Für einen anderen Termin
            legst du das bisherige Fenster still und fügst ein neues hinzu.
            Bestehende Bestellungen behalten ihren gebuchten Zeitraum.
          </p>
          {enabled && availableCount === 0 && (
            <StatusMessage>
              Ohne verfügbare Lieferfenster können keine neuen verbindlichen
              Bestellungen abgeschlossen werden. Zum Pausieren der Bestellungen
              kannst du alle Fenster stilllegen.
            </StatusMessage>
          )}
          <Button type="submit">
            {pending ? "Wird gespeichert …" : "Lieferplanung speichern"}
          </Button>
        </fieldset>
        {feedback && (
          <StatusMessage tone={feedback.error ? "error" : "success"}>
            {feedback.text}
            {feedback.conflict && (
              <>
                <Button
                  variant="secondary"
                  disabled={locked}
                  onClick={() => void reconcile()}
                >
                  Aktuellen Stand laden und Eingaben behalten
                </Button>
                <a
                  href={`/admin/actions/${actionId}#delivery`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Aktuellen Stand in neuem Tab öffnen
                </a>
              </>
            )}
          </StatusMessage>
        )}
      </form>
    </section>
  );
}
