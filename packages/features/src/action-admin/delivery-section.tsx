import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
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
  disabled: boolean;
}
interface Day {
  key: string;
  date: string;
  windows: DeliveryWindowRequest[];
}
function daysFor(config: DeliveryConfigurationResponse): Day[] {
  return [...new Set(config.windows.map((w) => w.deliveryOn))].map((date) => ({
    key: crypto.randomUUID(),
    date,
    windows: config.windows.filter((w) => w.deliveryOn === date),
  }));
}

export function DeliverySection(props: Props) {
  const query = useQuery({
    queryKey: ["delivery-configuration", props.actionId],
    queryFn: () => props.client.getDeliveryConfiguration(props.actionId),
  });
  if (query.isPending)
    return <StatusMessage>Lieferplanung wird geladen …</StatusMessage>;
  if (query.isError)
    return (
      <StatusMessage tone="error">
        Die Lieferplanung konnte nicht geladen werden.{" "}
        <Button variant="ghost" onClick={() => void query.refetch()}>
          Erneut laden
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
  disabled,
}: Props & { initial: DeliveryConfigurationResponse }) {
  const cache = useQueryClient();
  const [revision, setRevision] = useState(initial.revision);
  const [enabled, setEnabled] = useState(initial.enabled);
  const [timezone, setTimezone] = useState(initial.timezone);
  const [conflict, setConflict] = useState(false);
  const [comparison, setComparison] = useState<DeliveryConfigurationResponse>();
  const [days, setDays] = useState(() => daysFor(initial));
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{ error: boolean; text: string }>();
  const feedbackRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (feedback?.error) feedbackRef.current?.focus();
  }, [feedback]);
  function updateDay(key: string, change: Partial<Day>) {
    setDays((current) =>
      current.map((day) => (day.key === key ? { ...day, ...change } : day)),
    );
  }
  function updateWindow(
    day: Day,
    id: string,
    change: Partial<DeliveryWindowRequest>,
  ) {
    updateDay(day.key, {
      windows: day.windows.map((w) => (w.id === id ? { ...w, ...change } : w)),
    });
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (
      days.some((day) => !day.date || !day.windows.length) ||
      new Set(days.map((day) => day.date)).size !== days.length
    ) {
      setFeedback({
        error: true,
        text: "Bitte jeden Liefertag einmal anlegen und mindestens ein Zeitfenster je Tag ergänzen.",
      });
      return;
    }
    setPending(true);
    setConflict(false);
    setFeedback(undefined);
    try {
      const result = await client.saveDeliveryConfiguration(actionId, {
        revision,
        enabled,
        timezone,
        windows: days.flatMap((day) =>
          day.windows.map((w) => ({ ...w, deliveryOn: day.date })),
        ),
      });
      setComparison(undefined);
      setRevision(result.revision);
      setDays(daysFor(result));
      await cache.invalidateQueries({
        queryKey: ["commitment-capture-context", actionId],
      });
      await cache.invalidateQueries({
        queryKey: ["delivery-configuration", actionId],
      });
      setFeedback({
        error: false,
        text: "Lieferplanung gespeichert. Die Fenster gelten für Akquise und öffentliche Bestellungen.",
      });
    } catch (error) {
      setConflict(
        error instanceof ApiError &&
          error.detail.code === "delivery_revision_conflict",
      );
      setFeedback({
        error: true,
        text:
          error instanceof ApiError
            ? error.detail.code === "delivery_revision_conflict"
              ? "Die Planung wurde inzwischen geändert. Deine Eingaben bleiben erhalten. Lade den aktuellen Stand zum Vergleichen."
              : error.detail.message
            : "Speichern nicht möglich. Deine Eingaben bleiben erhalten; bitte erneut versuchen.",
      });
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="action-edit-section" aria-labelledby="delivery-heading">
      <header>
        <div>
          <h2 id="delivery-heading">Lieferplanung</h2>
          <p>
            Lege die Liefertage und Zeitfenster für diese Aktion fest. Uhrzeiten
            gelten für {timezone}.
          </p>
        </div>
      </header>
      <form onSubmit={(event) => void save(event)} className="delivery-editor">
        <fieldset disabled={disabled || pending}>
          <legend>Bestellungen mit Lieferung</legend>
          <label className="delivery-enable">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />{" "}
            Lieferung für diese Aktion aktivieren
          </label>
          <p>
            Bei aktiver Lieferung sind Lieferadresse und ein Zeitfenster
            erforderlich. Ansprechpartner, Telefonnummer und Lieferhinweise sind
            optional – in beiden Bestellformularen.
          </p>
          {!days.length && (
            <p>
              Noch keine Lieferfenster. Füge einen Tag hinzu und trage Beginn
              und Ende ein.
            </p>
          )}
          {days.map((day, index) => (
            <fieldset className="delivery-day" key={day.key}>
              <legend>Liefertag {index + 1}</legend>
              <div className="delivery-day-header">
                <label>
                  Datum
                  <input
                    type="date"
                    required
                    min={startsOn}
                    max={endsOn}
                    value={day.date}
                    onChange={(e) =>
                      updateDay(day.key, { date: e.target.value })
                    }
                  />
                </label>
                <Button
                  variant="ghost"
                  onClick={() =>
                    setDays((current) => [
                      ...current,
                      {
                        key: crypto.randomUUID(),
                        date: "",
                        windows: day.windows
                          .filter((w) => !w.retired)
                          .map((w) => ({ ...w, id: crypto.randomUUID() })),
                      },
                    ])
                  }
                >
                  Fenster auf neuen Tag kopieren
                </Button>
              </div>
              {day.windows.map((window, slot) => (
                <div className="delivery-window" key={window.id}>
                  <label>
                    Beginn {slot + 1}
                    <input
                      type="time"
                      required
                      value={window.startsAt.slice(0, 5)}
                      onChange={(e) =>
                        updateWindow(day, window.id, {
                          startsAt: e.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    Ende {slot + 1}
                    <input
                      type="time"
                      required
                      value={window.endsAt.slice(0, 5)}
                      onChange={(e) =>
                        updateWindow(day, window.id, { endsAt: e.target.value })
                      }
                    />
                  </label>
                  <label className="delivery-enable">
                    <input
                      type="checkbox"
                      checked={!window.retired}
                      onChange={(e) =>
                        updateWindow(day, window.id, {
                          retired: !e.target.checked,
                        })
                      }
                    />{" "}
                    Zur Auswahl
                  </label>
                  <Button
                    variant="ghost"
                    aria-label={`Zeitfenster ${slot + 1} am Liefertag ${index + 1} entfernen`}
                    onClick={() =>
                      updateDay(day.key, {
                        windows: day.windows.filter((w) => w.id !== window.id),
                      })
                    }
                  >
                    Entfernen
                  </Button>
                </div>
              ))}
              <Button
                variant="secondary"
                onClick={() =>
                  updateDay(day.key, {
                    windows: [
                      ...day.windows,
                      {
                        id: crypto.randomUUID(),
                        deliveryOn: day.date,
                        startsAt: "",
                        endsAt: "",
                        retired: false,
                      },
                    ],
                  })
                }
              >
                Zeitfenster hinzufügen
              </Button>
              <Button
                variant="ghost"
                onClick={() =>
                  setDays((current) => current.filter((d) => d.key !== day.key))
                }
              >
                Liefertag entfernen
              </Button>
            </fieldset>
          ))}
          <Button
            variant="secondary"
            onClick={() =>
              setDays((current) => [
                ...current,
                { key: crypto.randomUUID(), date: "", windows: [] },
              ])
            }
          >
            Tag hinzufügen
          </Button>
          <p>
            Bereits gebuchte Fenster lassen sich nur aus der Auswahl nehmen.
            Ihre Zeiten bleiben für bestehende Bestellungen erhalten.
          </p>
          <Button type="submit">
            {pending ? "Wird gespeichert …" : "Lieferplanung speichern"}
          </Button>
        </fieldset>
        {conflict && (
          <Button
            type="button"
            variant="secondary"
            onClick={async () => {
              try {
                setComparison(await client.getDeliveryConfiguration(actionId));
              } catch {
                setFeedback({
                  error: true,
                  text: "Der aktuelle Stand konnte nicht geladen werden. Deine Eingaben bleiben erhalten.",
                });
              }
            }}
          >
            Aktuelle Lieferplanung vergleichen
          </Button>
        )}
        {comparison && (
          <section aria-label="Aktuell gespeicherte Lieferplanung">
            <h3>Aktuell gespeichert · Revision {comparison.revision}</h3>
            <p>
              Lieferung {comparison.enabled ? "aktiviert" : "deaktiviert"} ·{" "}
              {comparison.timezone}
            </p>
            <ul>
              {comparison.windows.map((window) => (
                <li key={window.id}>
                  {window.deliveryOn} · {window.startsAt.slice(0, 5)}–
                  {window.endsAt.slice(0, 5)} ·{" "}
                  {window.retired ? "nicht zur Auswahl" : "zur Auswahl"}
                </li>
              ))}
            </ul>
            <p>
              Vergleiche die gespeicherten Fenster mit deinen Eingaben oben.
              Wenn du deine Planung übernimmst, ersetzt das nächste Speichern
              den hier angezeigten Stand. Bereits gebuchte Zeiten bleiben
              geschützt.
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setRevision(comparison.revision);
                setTimezone(comparison.timezone);
                setComparison(undefined);
                setConflict(false);
                setFeedback({
                  error: false,
                  text: "Deine Eingaben bleiben erhalten. Prüfe die Planung und speichere sie anschließend.",
                });
              }}
            >
              Eigene Planung nach Abgleich übernehmen
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setRevision(comparison.revision);
                setTimezone(comparison.timezone);
                setEnabled(comparison.enabled);
                setDays(daysFor(comparison));
                setComparison(undefined);
                setConflict(false);
                setFeedback({
                  error: false,
                  text: "Gespeicherte Planung übernommen. Deine vorherigen Eingaben wurden verworfen.",
                });
              }}
            >
              Eigene Eingaben verwerfen und gespeicherte Planung laden
            </Button>
          </section>
        )}
        {feedback && (
          <div ref={feedbackRef} tabIndex={-1} data-testid="delivery-feedback">
            <StatusMessage tone={feedback.error ? "error" : "success"}>
              {feedback.text}
            </StatusMessage>
          </div>
        )}
      </form>
    </section>
  );
}
