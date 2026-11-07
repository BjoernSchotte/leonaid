import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Globe, Info, Link2, Plus, Trash2 } from "lucide-react";
import { useId, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  type BindableActionResponse,
  type LeonAidApiClient,
  type SiteBindingResponse,
  type SiteHostListResponse,
  type SiteHostResponse,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  Input,
  Modal,
  Select,
  SkeletonRows,
  StatusMessage,
  useOptionalToast,
  type Tone,
} from "@leonaid/ui";

import {
  actionErrorMessage,
  type ActionErrorMessage,
} from "../action-admin/errors";
import { formatDateTime } from "../shared/dates";

export interface SiteHostsTabProps {
  readonly client: LeonAidApiClient;
}

const QUERY_KEY = ["site-hosts", "admin"] as const;
const SEGMENT = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const STATUS: Record<
  SiteHostResponse["status"],
  { label: string; tone: Tone; text: string }
> = {
  pending: {
    label: "Ausstehend",
    tone: "warn",
    text: "Noch nicht geprüft. Bitte den DNS-Eintrag anlegen und dann prüfen.",
  },
  verified: {
    label: "Geprüft",
    tone: "info",
    text: "Der Host zeigt auf diesen Server. Das Zertifikat entsteht beim ersten Aufruf.",
  },
  active: {
    label: "Aktiv",
    tone: "ok",
    text: "Erreichbar mit gültigem Zertifikat.",
  },
  disabled: {
    label: "Abgeschaltet",
    tone: "danger",
    text: "Wird nicht ausgeliefert und erhält kein Zertifikat.",
  },
};

const AVAILABILITY: Record<SiteBindingResponse["availability"], string> = {
  published: "läuft",
  archive: "beendet",
  inactive: "geplant",
};

const ENDED_REASON: Record<
  NonNullable<SiteBindingResponse["endedReason"]>,
  string
> = {
  segment_changed: "Pfad geändert",
  unbound: "gelöst",
  host_removed: "Domain entfernt",
};

/** A command id per payload: a retry of the same change reuses it. */
function useCommandId() {
  const current = useRef<{ key: string; id: string } | undefined>(undefined);
  return {
    for(key: string) {
      if (current.current?.key !== key) {
        current.current = { key, id: crypto.randomUUID() };
      }
      return current.current.id;
    },
    reset() {
      current.current = undefined;
    },
  };
}

function isSubdomainOf(hostname: string, base: string | null | undefined) {
  if (!base) return false;
  const parent = base.split(".").slice(-2).join(".");
  return hostname.endsWith(`.${parent}`);
}

function DnsHint({
  host,
  data,
}: {
  readonly host: SiteHostResponse;
  readonly data: SiteHostListResponse;
}) {
  const target = data.publicHost ?? data.adminHost;
  const sub = isSubdomainOf(host.hostname, target);
  return (
    <div className="site-dns small">
      <p className="muted">
        {sub ? (
          <>
            DNS: <code>CNAME</code> von <code>{host.hostname}</code> auf{" "}
            <code>{target}</code>, oder <code>A</code>/<code>AAAA</code> auf die
            Adresse dieses Servers.
          </>
        ) : (
          <>
            DNS: <code>A</code> und <code>AAAA</code> für{" "}
            <code>{host.hostname}</code> auf dieselben Adressen wie{" "}
            <code>{data.adminHost}</code>. Weiterleitungen beim Registrar
            funktionieren nicht.
          </>
        )}
      </p>
      <p className="subtle">
        Prüfadresse:{" "}
        <code>
          http://{host.hostname}
          {host.verificationPath}
        </code>
      </p>
    </div>
  );
}

type Dialog =
  | { readonly kind: "bind"; readonly host: SiteHostResponse }
  | { readonly kind: "move"; readonly host: SiteHostResponse }
  | { readonly kind: "redirect"; readonly host: SiteHostResponse }
  | { readonly kind: "remove"; readonly host: SiteHostResponse }
  | {
      readonly kind: "segment";
      readonly host: SiteHostResponse;
      readonly binding: SiteBindingResponse;
    }
  | {
      readonly kind: "unbind";
      readonly host: SiteHostResponse;
      readonly binding: SiteBindingResponse;
    };

/**
 * Domains (specs/multi-domain §7.1): campaign hosts and redirect hosts of
 * this installation. System admins only; every change asks the server,
 * which checks the role, the host revision and the fresh sign-in.
 */
export function SiteHostsTab({ client }: SiteHostsTabProps) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const hosts = useQuery({
    queryFn: () => client.listSiteHosts(),
    queryKey: QUERY_KEY,
    retry: false,
  });
  const [hostname, setHostname] = useState("");
  const [error, setError] = useState<ActionErrorMessage>();
  const [dialog, setDialog] = useState<Dialog>();
  const add = useCommandId();
  const addId = useId();

  const create = useMutation({
    mutationFn: (value: string) =>
      client.addSiteHost({ commandId: add.for(value), hostname: value }),
    onSuccess: async (host) => {
      add.reset();
      setHostname("");
      setError(undefined);
      toast?.show({
        title: `${host.displayHostname} eingetragen`,
        tone: "success",
      });
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (cause) => setError(actionErrorMessage(cause)),
  });

  if (hosts.isPending) return <SkeletonRows rows={3} />;
  if (hosts.isError) {
    const forbidden =
      hosts.error instanceof ApiError && hosts.error.status === 403;
    return (
      <ErrorState
        onRetry={forbidden ? undefined : () => void hosts.refetch()}
        title={forbidden ? "Nur für System-Admins" : "Domains nicht erreichbar"}
      >
        {forbidden
          ? "Domains und Kampagnen-Hosts verwaltet die System-Administration."
          : actionErrorMessage(hosts.error, { redirect: false }).message}
      </ErrorState>
    );
  }
  const data = hosts.data;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = hostname.trim();
    if (value) create.mutate(value);
  };

  return (
    <div className="site-hosts" data-testid="site-hosts">
      <section aria-labelledby="site-hosts-title" className="panel">
        <header className="panel-header">
          <h2 id="site-hosts-title">Domains für Aktionen</h2>
        </header>
        <div className="callout flag-note">
          <Icon icon={Info} size={16} />
          <span>
            Eine Aktion kann auf einer eigenen Domain oder Subdomain laufen,
            etwa <code>krapfentaxi.org</code>. Die Verwaltung bleibt auf{" "}
            <code>{data.adminHost}</code>
            {data.publicHost && data.publicHost !== data.adminHost ? (
              <>
                , die allgemeinen Seiten auf <code>{data.publicHost}</code>
              </>
            ) : null}
            . Eine neue Domain wird ohne Neustart aktiv, sobald die Prüfung
            gelingt.
          </span>
        </div>
        <form className="site-add" onSubmit={submit}>
          <Field
            error={error?.message}
            hint="Nur der Name, ohne https:// und ohne Pfad."
            id={addId}
            label="Domain"
          >
            <Input
              autoComplete="off"
              data-testid="site-host-name"
              inputMode="url"
              onChange={(event) => setHostname(event.target.value)}
              placeholder="krapfentaxi.org"
              spellCheck={false}
              value={hostname}
            />
          </Field>
          <Button
            disabled={!hostname.trim() || create.isPending}
            icon={Plus}
            type="submit"
          >
            Domain hinzufügen
          </Button>
        </form>
      </section>
      {data.hosts.length === 0 ? (
        <EmptyState
          description="Ohne eigene Domain sind Aktionen unter ihren bisherigen Adressen erreichbar."
          icon={Globe}
          title="Noch keine Domain eingetragen"
        />
      ) : (
        data.hosts.map((host) => (
          <SiteHostPanel
            client={client}
            data={data}
            host={host}
            key={host.id}
            onDialog={setDialog}
          />
        ))
      )}
      {dialog ? (
        <SiteHostDialog
          actions={data.actions}
          client={client}
          data={data}
          dialog={dialog}
          onClose={() => setDialog(undefined)}
        />
      ) : null}
    </div>
  );
}

function SiteHostPanel({
  client,
  data,
  host,
  onDialog,
}: {
  readonly client: LeonAidApiClient;
  readonly data: SiteHostListResponse;
  readonly host: SiteHostResponse;
  readonly onDialog: (dialog: Dialog) => void;
}) {
  const status = STATUS[host.status];
  const disabled = host.status === "disabled";
  const titleId = `site-host-${host.id}`;
  return (
    <section
      aria-labelledby={titleId}
      className="panel site-host"
      data-hostname={host.hostname}
      data-testid="site-host"
    >
      <header className="panel-header">
        <h2 id={titleId}>{host.displayHostname}</h2>
        <div className="cluster">
          {host.kind === "redirect" ? (
            <Badge icon={ArrowRightLeft} tone="neutral">
              Weiterleitung auf {host.redirectToHostname}
            </Badge>
          ) : null}
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
      </header>
      <div className="panel-pad stack">
        <p className="small muted">
          {status.text}
          {host.lastCheckedAt
            ? ` Letzte Prüfung ${formatDateTime(host.lastCheckedAt)}${
                host.lastCheckResult ? `: ${host.lastCheckResult}` : ""
              }.`
            : ""}
        </p>
        {host.status !== "active" ? <DnsHint data={data} host={host} /> : null}
        {host.kind === "campaign" ? (
          <EditionList client={client} host={host} onDialog={onDialog} />
        ) : null}
        {host.history.length ? (
          <details className="site-history">
            <summary className="small">
              Frühere Pfade ({host.history.length})
            </summary>
            <ul className="audit-list">
              {host.history.map((item) => (
                <li className="small" key={item.id}>
                  <code>/{item.segment}/</code> · {item.actionName} ·{" "}
                  {item.endedReason ? ENDED_REASON[item.endedReason] : ""}
                  {item.validTo
                    ? ` ${formatDateTime(item.validTo)}`
                    : ""} → {item.targetUrl ?? "nicht mehr öffentlich"}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <div className="cluster site-host-actions">
          {host.kind === "campaign" && !disabled ? (
            <>
              <Button
                icon={Link2}
                onClick={() => onDialog({ kind: "bind", host })}
                size="sm"
                variant="secondary"
              >
                Aktion binden
              </Button>
              {host.bindings.length ? (
                <Button
                  icon={ArrowRightLeft}
                  onClick={() => onDialog({ kind: "move", host })}
                  size="sm"
                  variant="secondary"
                >
                  Domain an Folgeaktion übergeben
                </Button>
              ) : null}
            </>
          ) : null}
          {!disabled && host.bindings.length === 0 ? (
            <Button
              onClick={() => onDialog({ kind: "redirect", host })}
              size="sm"
              variant="ghost"
            >
              {host.kind === "redirect"
                ? "Weiterleitung ändern"
                : "Als Weiterleitung nutzen"}
            </Button>
          ) : null}
          {!disabled || host.bindings.length ? (
            <Button
              icon={Trash2}
              onClick={() => onDialog({ kind: "remove", host })}
              size="sm"
              variant="ghost"
            >
              Domain entfernen
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function EditionList({
  client,
  host,
  onDialog,
}: {
  readonly client: LeonAidApiClient;
  readonly host: SiteHostResponse;
  readonly onDialog: (dialog: Dialog) => void;
}) {
  if (!host.bindings.length) {
    return (
      <p className="small subtle">
        Noch keine Aktion gebunden. „/“ zeigt bis dahin eine Fehlerseite.
      </p>
    );
  }
  return (
    <ul
      aria-label={`Ausgaben auf ${host.displayHostname}`}
      className="flag-list site-editions"
    >
      {host.bindings.map((binding) => (
        <li
          className="flag-row site-edition"
          data-segment={binding.segment}
          data-testid="site-edition"
          key={binding.id}
        >
          <div className="flag-text">
            <span className="flag-name">
              <code>/{binding.segment}/</code> — {binding.actionName}
            </span>
            <span className="small muted">
              {AVAILABILITY[binding.availability]}
              {binding.atRoot ? " · aktuell auf /" : ""}
              {binding.isPrimary ? "" : " · zweite Adresse"}
              {binding.campaignPage
                ? ""
                : " · ohne veröffentlichte Kampagnenseite"}
            </span>
            <a
              className="small"
              href={binding.editionUrl}
              rel="noreferrer"
              target="_blank"
            >
              {binding.editionUrl}
            </a>
          </div>
          <div className="cluster">
            {!binding.isPrimary ? (
              <PrimaryButton binding={binding} client={client} host={host} />
            ) : null}
            <Button
              onClick={() => onDialog({ kind: "segment", host, binding })}
              size="sm"
              variant="ghost"
            >
              Pfad ändern
            </Button>
            <Button
              onClick={() => onDialog({ kind: "unbind", host, binding })}
              size="sm"
              variant="ghost"
            >
              Lösen
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function PrimaryButton({
  binding,
  client,
  host,
}: {
  readonly binding: SiteBindingResponse;
  readonly client: LeonAidApiClient;
  readonly host: SiteHostResponse;
}) {
  const queryClient = useQueryClient();
  const command = useCommandId();
  const toast = useOptionalToast();
  const mutation = useMutation({
    mutationFn: () =>
      client.setPrimarySiteEdition(host.id, binding.id, {
        commandId: command.for(`${host.revision}`),
        revision: host.revision,
      }),
    onSuccess: async () => {
      command.reset();
      toast?.show({ title: "Hauptadresse geändert", tone: "success" });
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (cause) =>
      toast?.show({ title: actionErrorMessage(cause).message, tone: "error" }),
  });
  return (
    <Button
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
      size="sm"
      variant="ghost"
    >
      Als Hauptadresse
    </Button>
  );
}

function SiteHostDialog({
  actions,
  client,
  data,
  dialog,
  onClose,
}: {
  readonly actions: readonly BindableActionResponse[];
  readonly client: LeonAidApiClient;
  readonly data: SiteHostListResponse;
  readonly dialog: Dialog;
  readonly onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const command = useCommandId();
  const [error, setError] = useState<ActionErrorMessage>();
  const [actionId, setActionId] = useState("");
  const [segment, setSegment] = useState(
    dialog.kind === "segment" ? dialog.binding.segment : "",
  );
  const [atRoot, setAtRoot] = useState(
    dialog.kind === "bind" && !dialog.host.bindings.some((item) => item.atRoot),
  );
  const [target, setTarget] = useState(
    dialog.kind === "redirect" ? (dialog.host.redirectToHostId ?? "") : "",
  );
  const [confirmed, setConfirmed] = useState(false);
  const host = dialog.host;
  const revision = host.revision;
  const preview = useQuery({
    enabled: dialog.kind === "remove",
    queryFn: () => client.previewSiteHostRemoval(host.id),
    queryKey: ["site-hosts", "removal-preview", host.id, revision],
    retry: false,
  });
  const segmentValue = segment.trim().toLowerCase();
  const segmentInvalid = Boolean(segmentValue) && !SEGMENT.test(segmentValue);

  const mutation = useMutation({
    mutationFn: async () => {
      const key = JSON.stringify([
        dialog.kind,
        actionId,
        segmentValue,
        atRoot,
        target,
        confirmed,
        revision,
      ]);
      const commandId = command.for(key);
      switch (dialog.kind) {
        case "bind":
          return client.bindSiteEdition(host.id, {
            commandId,
            revision,
            actionId,
            segment: segmentValue || null,
            atRoot,
          });
        case "move":
          return client.moveSiteRoot(host.id, {
            commandId,
            revision,
            actionId,
            segment: segmentValue || null,
          });
        case "segment":
          return client.changeSiteEditionSegment(host.id, dialog.binding.id, {
            commandId,
            revision,
            segment: segmentValue,
          });
        case "unbind":
          return client.unbindSiteEdition(host.id, dialog.binding.id, {
            commandId,
            revision,
            confirmRootRemoval: confirmed,
          });
        case "redirect":
          return client.setSiteHostRedirect(host.id, {
            commandId,
            revision,
            targetHostId: target || null,
          });
        case "remove":
          return client.removeSiteHost(host.id, { commandId, revision });
      }
    },
    onSuccess: async () => {
      command.reset();
      toast?.show({ title: DONE[dialog.kind], tone: "success" });
      await queryClient.invalidateQueries({ queryKey: ["site-hosts"] });
      onClose();
    },
    onError: (cause) => setError(actionErrorMessage(cause)),
  });

  const bound = new Set(host.bindings.map((item) => item.actionId));
  const choices =
    dialog.kind === "move"
      ? actions.filter((item) => item.availability !== "archive")
      : actions.filter((item) => !bound.has(item.id));
  const chosen = actions.find((item) => item.id === actionId);
  const onlyRoot =
    dialog.kind === "unbind" &&
    dialog.binding.atRoot &&
    host.bindings.length === 1;
  const targets = data.hosts.filter(
    (item) =>
      item.id !== host.id &&
      item.kind === "campaign" &&
      item.status !== "disabled",
  );
  const ready =
    !mutation.isPending &&
    !segmentInvalid &&
    (dialog.kind === "bind" || dialog.kind === "move"
      ? Boolean(actionId)
      : dialog.kind === "segment"
        ? Boolean(segmentValue) && segmentValue !== dialog.binding.segment
        : dialog.kind === "unbind"
          ? !onlyRoot || confirmed
          : dialog.kind === "remove"
            ? preview.isSuccess && preview.data.redirectHosts.length === 0
            : true);

  const segmentField =
    dialog.kind === "bind" ||
    dialog.kind === "move" ||
    dialog.kind === "segment" ? (
      <Field
        error={
          segmentInvalid
            ? "Kleinbuchstaben, Ziffern und Bindestriche, zum Beispiel 2025."
            : undefined
        }
        hint={
          dialog.kind === "segment"
            ? "Der alte Pfad leitet danach dauerhaft auf den neuen."
            : "Leer lassen: das Jahr des Publikationsbeginns."
        }
        label="Pfad der Ausgabe"
        optional={dialog.kind !== "segment"}
      >
        <Input
          autoComplete="off"
          data-testid="site-edition-segment"
          onChange={(event) => setSegment(event.target.value)}
          placeholder="2025"
          spellCheck={false}
          value={segment}
        />
      </Field>
    ) : null;

  return (
    <Modal
      description={DESCRIPTION[dialog.kind](host.displayHostname)}
      footer={
        <>
          <Button
            disabled={mutation.isPending}
            onClick={onClose}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button
            data-testid="site-dialog-confirm"
            disabled={!ready}
            onClick={() => mutation.mutate()}
            variant={
              dialog.kind === "remove" || dialog.kind === "unbind"
                ? "danger"
                : "primary"
            }
          >
            {CONFIRM[dialog.kind]}
          </Button>
        </>
      }
      onClose={() => {
        if (!mutation.isPending) onClose();
      }}
      open
      title={TITLE[dialog.kind]}
    >
      <div className="stack">
        {dialog.kind === "bind" || dialog.kind === "move" ? (
          <Field label="Aktion" required>
            <Select
              data-testid="site-edition-action"
              onChange={(event) => setActionId(event.target.value)}
              value={actionId}
            >
              <option value="">Bitte wählen</option>
              {choices.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({AVAILABILITY[item.availability]})
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        {segmentField}
        {dialog.kind === "bind" &&
        !host.bindings.some((item) => item.atRoot) ? (
          <label className="cluster small">
            <input
              checked={atRoot}
              onChange={(event) => setAtRoot(event.target.checked)}
              type="checkbox"
            />
            Diese Ausgabe unter „/“ zeigen
          </label>
        ) : null}
        {chosen && !chosen.campaignPage ? (
          <StatusMessage tone="warning">
            <p>
              Diese Aktion hat keine veröffentlichte Kampagnenseite. Die Domain
              zeigt nur Kampagnenseiten des CMS.
            </p>
          </StatusMessage>
        ) : null}
        {dialog.kind === "move" && chosen ? (
          <MovePreview chosen={chosen} host={host} segment={segmentValue} />
        ) : null}
        {dialog.kind === "unbind" && onlyRoot ? (
          <label className="cluster small">
            <input
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              type="checkbox"
            />
            Ich weiß, dass „/“ danach eine Fehlerseite zeigt.
          </label>
        ) : null}
        {dialog.kind === "redirect" ? (
          <Field
            hint="Ganze Domain, der Pfad bleibt erhalten (308)."
            label="Weiterleiten auf"
          >
            <Select
              onChange={(event) => setTarget(event.target.value)}
              value={target}
            >
              <option value="">Keine Weiterleitung (Kampagnen-Host)</option>
              {targets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayHostname}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        {dialog.kind === "remove" ? (
          preview.isPending ? (
            <SkeletonRows rows={2} />
          ) : preview.isError ? (
            <StatusMessage tone="error">
              <p>
                {actionErrorMessage(preview.error, { redirect: false }).message}
              </p>
            </StatusMessage>
          ) : (
            <>
              {preview.data.redirectHosts.length ? (
                <StatusMessage tone="warning">
                  <p>
                    Diese Domains leiten noch hierher weiter:{" "}
                    {preview.data.redirectHosts.join(", ")}. Bitte zuerst
                    entfernen oder umstellen.
                  </p>
                </StatusMessage>
              ) : null}
              {preview.data.items.length ? (
                <ul className="audit-list" data-testid="site-removal-preview">
                  {preview.data.items.map((item) => (
                    <li className="small" key={item.bindingId}>
                      {item.actionName}: {item.currentUrl} →{" "}
                      {item.newUrl ?? "nicht mehr öffentlich erreichbar"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small muted">Keine Ausgabe ist gebunden.</p>
              )}
            </>
          )
        ) : null}
        {error ? (
          <StatusMessage tone="error">
            <p>{error.message}</p>
          </StatusMessage>
        ) : null}
      </div>
    </Modal>
  );
}

function MovePreview({
  chosen,
  host,
  segment,
}: {
  readonly chosen: BindableActionResponse;
  readonly host: SiteHostResponse;
  readonly segment: string;
}) {
  const root = host.bindings.find((item) => item.atRoot);
  const existing = host.bindings.find((item) => item.actionId === chosen.id);
  const running = host.bindings.filter(
    (item) => item.availability === "published" && item.actionId !== chosen.id,
  );
  const shown =
    existing?.segment ?? (segment || "Jahr des Publikationsbeginns");
  return (
    <div className="stack" data-testid="site-move-preview">
      <p className="small">Nach der Übergabe:</p>
      <ul className="audit-list">
        <li className="small">
          {host.displayHostname}/ → {chosen.name}
          {chosen.availability === "published"
            ? ""
            : " (ab Publikationsbeginn; bis dahin die neueste öffentliche Ausgabe)"}
        </li>
        <li className="small">
          {chosen.name} bleibt auch unter /{shown}/ erreichbar.
        </li>
        {root && root.actionId !== chosen.id ? (
          <li className="small">
            {root.actionName} → {host.displayHostname}/{root.segment}/ (Aliase
            und /campaigns/{root.archiveSlug}/ zeigen dorthin; verschickte
            Bestätigungen bleiben gültig)
          </li>
        ) : null}
      </ul>
      {running.length && chosen.availability === "published" ? (
        <StatusMessage tone="warning">
          <p>
            Es laufen dann zwei Ausgaben gleichzeitig. Die bisherige nimmt unter
            ihrem Pfad weiter Bestellungen an.
          </p>
        </StatusMessage>
      ) : null}
    </div>
  );
}

const TITLE: Record<Dialog["kind"], string> = {
  bind: "Aktion binden",
  move: "Domain an Folgeaktion übergeben",
  segment: "Pfad der Ausgabe ändern",
  unbind: "Ausgabe lösen",
  redirect: "Weiterleitung",
  remove: "Domain entfernen",
};

const DESCRIPTION: Record<Dialog["kind"], (host: string) => string> = {
  bind: (host) => `Die Aktion wird eine Ausgabe auf ${host}.`,
  move: (host) =>
    `Die Folgeaktion übernimmt „/“ auf ${host}. Frühere Ausgaben bleiben unter ihrem Pfad erreichbar.`,
  segment: (host) => `Die Ausgabe bekommt auf ${host} einen neuen Pfad.`,
  unbind: (host) =>
    `Die Ausgabe verschwindet von ${host}; ihr Pfad leitet auf die nächste öffentliche Adresse der Aktion.`,
  redirect: (host) =>
    `${host} leitet als Ganzes auf eine andere Domain weiter.`,
  remove: (host) =>
    `${host} wird abgeschaltet und erhält kein Zertifikat mehr. Alte Links auf diese Domain funktionieren danach nicht mehr.`,
};

const CONFIRM: Record<Dialog["kind"], string> = {
  bind: "Binden",
  move: "Übergeben",
  segment: "Pfad ändern",
  unbind: "Lösen",
  redirect: "Speichern",
  remove: "Entfernen",
};

const DONE: Record<Dialog["kind"], string> = {
  bind: "Aktion gebunden",
  move: "Domain übergeben",
  segment: "Pfad geändert",
  unbind: "Ausgabe gelöst",
  redirect: "Weiterleitung gespeichert",
  remove: "Domain entfernt",
};
