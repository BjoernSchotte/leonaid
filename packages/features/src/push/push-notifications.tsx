import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, BellRing, Send } from "lucide-react";
import { useEffect, useState } from "react";

import {
  ApiError,
  type LeonAidApiClient,
  type PushConfigurationResponse,
  type PushKindResponse,
} from "@leonaid/api-client";
import {
  Button,
  ErrorState,
  SkeletonRows,
  StatusMessage,
  Switch,
} from "@leonaid/ui";

import {
  browserPushDevice,
  liveSubscription,
  type PushDevice,
  type PushPermission,
} from "./push-device";

export interface PushNotificationsPageProps {
  readonly client: LeonAidApiClient;
  /** The browser's push features; the real browser unless a test passes one. */
  readonly device?: PushDevice;
}

type PushKind = PushKindResponse["kind"];

const KIND_COPY: Record<
  PushKind,
  { readonly label: string; readonly hint: string }
> = {
  follow_ups: {
    label: "Wiedervorlagen",
    hint: "Einmal am Tag ab 8 Uhr, wenn Wiedervorlagen fällig oder überfällig sind.",
  },
  feed: {
    label: "Neue Bestellungen",
    hint: "Wenn unter „Neues“ eine Bestellung für dich eingeht.",
  },
  tasks: {
    label: "Aufgaben",
    hint: "Wenn dir jemand eine Aufgabe zuweist.",
  },
  delivery: {
    label: "Lieferungen",
    hint: "Wenn dir Lieferungen für eine Tour zugewiesen werden.",
  },
};

const QUERY_KEY = ["push-configuration"] as const;

/**
 * What this device is doing: `checking` until the browser answered, then
 * `off` (no subscription) or `on` with Core's id of the device.
 */
type DeviceState =
  | { readonly status: "checking" }
  | { readonly status: "off" }
  | {
      readonly status: "on";
      /**
       * Core's id of the device. null: the browser is subscribed, but Core
       * took no registration just now (too many in the last hour), so the
       * page cannot name the device to Core until later.
       */
      readonly id: string | null;
    };

function errorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.detail.code : null;
}

/**
 * "Benachrichtigungen" of the acquisition app (specs/mails-documents-
 * donations-push §10): the permission step, the home-screen note for the
 * iPhone, one switch per kind and the test push. Says plainly when the
 * browser cannot do it, when it is blocked there, and when the operator
 * has not set it up.
 */
export function PushNotificationsPage({
  client,
  device = browserPushDevice,
}: PushNotificationsPageProps) {
  const queries = useQueryClient();
  const configuration = useQuery({
    queryFn: () => client.getPushConfiguration(),
    queryKey: QUERY_KEY,
    retry: false,
  });
  const support = device.support();
  const [permission, setPermission] = useState<PushPermission>(() =>
    support === "supported" ? device.permission() : "default",
  );
  const [deviceState, setDeviceState] = useState<DeviceState>({
    status: "checking",
  });
  const [notice, setNotice] = useState<{
    readonly tone: "error" | "success";
    readonly text: string;
  } | null>(null);
  const publicKey = configuration.data?.publicKey ?? null;
  const ready = support === "supported" && publicKey !== null;

  // A device that is subscribed already says so to Core again: the row
  // belongs to the session, and a new sign-in is a new session.
  useEffect(() => {
    if (!ready || publicKey === null) return;
    let live = true;
    if (permission !== "granted") {
      setDeviceState({ status: "off" });
      return;
    }
    void (async () => {
      try {
        // Also replaces a subscription of an earlier key of the installation,
        // so "eingeschaltet" is never shown for a device no push can reach.
        const subscription = await liveSubscription(device, publicKey);
        const id = subscription
          ? (await client.savePushSubscription(subscription)).id
          : null;
        if (live) setDeviceState(id ? { id, status: "on" } : { status: "off" });
      } catch (error) {
        if (!live) return;
        // Past the limit of registrations the device is still subscribed:
        // say so, instead of showing it as off for an hour.
        setDeviceState(
          error instanceof ApiError && error.status === 429
            ? { id: null, status: "on" }
            : { status: "off" },
        );
      }
    })();
    return () => {
      live = false;
    };
  }, [client, device, permission, publicKey, ready]);

  const switchOn = useMutation({
    mutationFn: async () => {
      if (!publicKey) throw new Error("not configured");
      const granted =
        permission === "granted"
          ? permission
          : await device.requestPermission();
      setPermission(granted);
      if (granted !== "granted") return null;
      const subscription = await device.subscribe(publicKey);
      return (await client.savePushSubscription(subscription)).id;
    },
    onError: (error) =>
      setNotice({
        text:
          errorCode(error) === "push_device_limit"
            ? "Du hast schon zehn Geräte angemeldet. Schalte Benachrichtigungen zuerst auf einem anderen Gerät aus."
            : error instanceof ApiError && error.status === 429
              ? "Das waren viele Versuche in kurzer Zeit. Versuche es in einer Stunde wieder."
              : "Dieses Gerät konnte nicht angemeldet werden. Prüfe die Verbindung und versuche es erneut.",
        tone: "error",
      }),
    onMutate: () => setNotice(null),
    onSuccess: (id) => {
      if (id) setDeviceState({ id, status: "on" });
    },
  });

  const switchOff = useMutation({
    mutationFn: async (id: string) => {
      await device.unsubscribe();
      try {
        await client.deletePushSubscription(id);
      } catch (error) {
        // Already gone at Core (signed out elsewhere): that is the goal.
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
    },
    onError: () =>
      setNotice({
        text: "Das Gerät konnte nicht abgemeldet werden. Versuche es erneut.",
        tone: "error",
      }),
    onMutate: () => setNotice(null),
    onSuccess: () => setDeviceState({ status: "off" }),
  });

  const prefer = useMutation({
    mutationFn: (change: {
      readonly kind: PushKind;
      readonly enabled: boolean;
    }) => client.updatePushPreferences({ preferences: [change] }),
    onError: () =>
      setNotice({
        text: "Die Einstellung konnte nicht gespeichert werden. Versuche es erneut.",
        tone: "error",
      }),
    onMutate: () => setNotice(null),
    onSuccess: (data: PushConfigurationResponse) =>
      queries.setQueryData(QUERY_KEY, data),
  });

  const test = useMutation({
    mutationFn: (id: string) => client.sendTestPush({ subscriptionId: id }),
    onError: (error) =>
      setNotice({
        text:
          error instanceof ApiError && error.status === 429
            ? "Das waren viele Tests in kurzer Zeit. Versuche es in ein paar Minuten wieder."
            : "Der Test konnte nicht gesendet werden. Versuche es erneut.",
        tone: "error",
      }),
    onMutate: () => setNotice(null),
    onSuccess: () =>
      setNotice({
        text: "Der Test ist unterwegs. Kommt in einer Minute nichts an, prüfe die Benachrichtigungs-Einstellungen deines Geräts für LeonAid.",
        tone: "success",
      }),
  });

  // A plain function, not a component: the buttons keep their focus when
  // the page renders again.
  const deviceActions = (deviceId: string) => (
    <>
      <p>
        Benachrichtigungen sind auf diesem Gerät eingeschaltet. Mit dem Test
        siehst du, ob sie ankommen.
      </p>
      <div className="push-actions">
        <Button
          data-testid="push-test"
          disabled={test.isPending}
          icon={Send}
          onClick={() => test.mutate(deviceId)}
          variant="secondary"
        >
          Test senden
        </Button>
        <Button
          data-testid="push-switch-off"
          disabled={switchOff.isPending}
          icon={BellOff}
          onClick={() => switchOff.mutate(deviceId)}
          variant="ghost"
        >
          Auf diesem Gerät ausschalten
        </Button>
      </div>
    </>
  );

  return (
    <div className="push" data-testid="push-page">
      <header className="push-head">
        <h1 className="pwa-h1">Benachrichtigungen</h1>
        <p>
          LeonAid kann dir auf diesem Gerät Bescheid geben, wenn Arbeit auf dich
          wartet, auch wenn die App zu ist.
        </p>
      </header>
      {configuration.isPending ? (
        <SkeletonRows rows={4} />
      ) : configuration.isError ? (
        errorCode(configuration.error) === "feature_flag_disabled" ? (
          <StatusMessage tone="info">
            <div data-testid="push-disabled">
              <strong>Benachrichtigungen sind nicht freigeschaltet.</strong>{" "}
              Dein Club hat sie für diese Installation nicht eingeschaltet.
            </div>
          </StatusMessage>
        ) : (
          <ErrorState
            onRetry={() => void configuration.refetch()}
            title="Die Einstellungen konnten nicht geladen werden"
          >
            Prüfe deine Verbindung.
          </ErrorState>
        )
      ) : !configuration.data.configured ? (
        <StatusMessage tone="warning">
          <div data-testid="push-not-configured">
            <strong>Benachrichtigungen sind noch nicht eingerichtet.</strong>{" "}
            Der Betreiber dieser Installation muss dafür einen Schlüssel
            hinterlegen. Bis dahin lässt sich hier nichts einschalten.
          </div>
        </StatusMessage>
      ) : support === "needs-home-screen" ? (
        <StatusMessage tone="info">
          <div data-testid="push-home-screen">
            <strong>Lege LeonAid zuerst auf den Home-Bildschirm.</strong> Auf
            iPhone und iPad gibt es Benachrichtigungen nur für Apps auf dem
            Home-Bildschirm:
            <ol className="push-steps">
              <li>Öffne LeonAid in Safari und tippe auf „Teilen“.</li>
              <li>Wähle „Zum Home-Bildschirm“.</li>
              <li>
                Öffne LeonAid über das neue Symbol und komm auf diese Seite
                zurück.
              </li>
            </ol>
          </div>
        </StatusMessage>
      ) : support === "unsupported" ? (
        <StatusMessage tone="warning">
          <div data-testid="push-unsupported">
            <strong>
              Dieser Browser kann keine Benachrichtigungen empfangen.
            </strong>{" "}
            Nutze LeonAid in einem aktuellen Chrome, Edge, Firefox oder Safari.
            Auf iPhone und iPad muss LeonAid auf dem Home-Bildschirm liegen.
          </div>
        </StatusMessage>
      ) : permission === "denied" ? (
        <StatusMessage tone="warning">
          <div data-testid="push-blocked">
            <strong>Benachrichtigungen sind im Browser blockiert.</strong>{" "}
            LeonAid darf dich deshalb nicht noch einmal fragen. Erlaube
            Benachrichtigungen für diese Seite in den Einstellungen deines
            Browsers (das Schloss- oder Einstellungssymbol neben der Adresse)
            und lade die Seite neu.
          </div>
        </StatusMessage>
      ) : deviceState.status === "checking" ? (
        <SkeletonRows rows={4} />
      ) : deviceState.status === "off" ? (
        <section className="panel panel-pad push-step" data-testid="push-off">
          <h2>Auf diesem Gerät einschalten</h2>
          <p>
            Dein Browser fragt gleich, ob LeonAid dir Benachrichtigungen senden
            darf. Wähle dort „Zulassen“. Danach bestimmst du hier, worüber du
            Bescheid bekommst.
          </p>
          <p className="push-note">
            Auf iPhone und iPad muss LeonAid dafür auf dem Home-Bildschirm
            liegen und von dort geöffnet sein.
          </p>
          <Button
            data-testid="push-switch-on"
            disabled={switchOn.isPending}
            icon={BellRing}
            onClick={() => switchOn.mutate()}
            variant="primary"
          >
            Benachrichtigungen einschalten
          </Button>
        </section>
      ) : (
        <>
          <section className="panel push-kinds" data-testid="push-on">
            <div className="panel-header">
              <h2>Worüber möchtest du Bescheid bekommen?</h2>
            </div>
            {configuration.data.kinds.length === 0 ? (
              <p className="push-empty">
                Für dein Konto gibt es zurzeit nichts zu melden.
              </p>
            ) : (
              <ul>
                {configuration.data.kinds.map((item) => (
                  <li key={item.kind}>
                    <Switch
                      aria-describedby={`push-hint-${item.kind}`}
                      checked={item.enabled}
                      data-testid={`push-kind-${item.kind}`}
                      disabled={prefer.isPending}
                      label={KIND_COPY[item.kind].label}
                      onChange={(event) =>
                        prefer.mutate({
                          enabled: event.currentTarget.checked,
                          kind: item.kind,
                        })
                      }
                    />
                    <p id={`push-hint-${item.kind}`}>
                      {KIND_COPY[item.kind].hint}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel panel-pad push-step">
            <h2>Dieses Gerät</h2>
            {deviceState.id === null ? (
              <p data-testid="push-busy">
                Benachrichtigungen sind auf diesem Gerät eingeschaltet. LeonAid
                konnte die Anmeldung des Geräts gerade nicht erneuern, weil es
                in der letzten Stunde zu viele Versuche gab. Den Test und das
                Ausschalten findest du hier wieder, wenn du es in etwa einer
                Stunde noch einmal versuchst.
              </p>
            ) : (
              deviceActions(deviceState.id)
            )}
          </section>
        </>
      )}
      {notice ? (
        <StatusMessage tone={notice.tone}>
          <span data-testid="push-notice">{notice.text}</span>
        </StatusMessage>
      ) : null}
      <p className="push-privacy">
        Benachrichtigungen enthalten keine Namen, Adressen oder Beträge. Zu
        jeder Art kommt höchstens eine in 15 Minuten. Wenn du dich auf diesem
        Gerät abmeldest, enden sie hier.
      </p>
    </div>
  );
}
