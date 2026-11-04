import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Pencil, Plus, Tag, Trash2 } from "lucide-react";
import { useId, useRef, useState } from "react";

import type {
  CampaignAliasItemResponse,
  CampaignAliasListResponse,
  CampaignAliasTargetResponse,
  LeonAidApiClient,
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
  SkeletonRows,
  StatusMessage,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage, type ActionErrorMessage } from "./errors";
import { isRevisionConflict } from "./use-action-error";

interface Props {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly disabled: boolean;
}

const ALIAS = /^[a-z0-9]+(-[a-z0-9]+)*$/;

function AliasAvailability({
  client,
  item,
}: {
  readonly client: LeonAidApiClient;
  readonly item: CampaignAliasItemResponse;
}) {
  const query = useQuery({
    queryKey: ["campaign-alias-availability", item.alias, item.revision],
    queryFn: () => client.resolvePublicActionAlias(item.alias),
    enabled: item.enabled,
    retry: false,
    staleTime: 0,
  });
  return (
    <span className="small subtle" role="status">
      {!item.enabled
        ? "Deaktiviert"
        : query.isPending
          ? "Freigabe wird geprüft …"
          : query.isError
            ? "Freigabe derzeit nicht prüfbar."
            : query.data.redirectPath
              ? "Freigegeben. Die Zielseite braucht zusätzlich veröffentlichte Inhalte."
              : "Keine öffentliche Weiterleitung freigegeben."}
    </span>
  );
}

type Operation =
  | {
      readonly kind: "create";
      readonly alias: string;
      readonly enabled: boolean;
    }
  | {
      readonly kind: "update";
      readonly item: CampaignAliasItemResponse;
      readonly alias: string;
      readonly enabled: boolean;
      readonly targetActionId: string;
    }
  | { readonly kind: "remove"; readonly item: CampaignAliasItemResponse };

/**
 * Create, update and remove with an idempotent command id per unchanged
 * request (a retry after a lost answer is not a second command).
 */
function useAliasCommand(
  actionId: string,
  client: LeonAidApiClient,
  onDone: () => Promise<void>,
  onRemoveFailed: () => void,
) {
  const toast = useOptionalToast();
  const [error, setError] = useState<ActionErrorMessage>();
  const command = useRef<
    { fingerprint: string; commandId: string; aliasId: string } | undefined
  >(undefined);
  const mutation = useMutation({
    mutationFn: async (operation: Operation) => {
      const fingerprint = JSON.stringify(operation);
      if (command.current?.fingerprint !== fingerprint) {
        command.current = {
          fingerprint,
          commandId: crypto.randomUUID(),
          aliasId:
            operation.kind === "create"
              ? crypto.randomUUID()
              : operation.item.aliasId,
        };
      }
      const { commandId, aliasId } = command.current;
      if (operation.kind === "remove") {
        return client.removeCampaignAlias(actionId, aliasId, {
          commandId,
          revision: operation.item.revision,
        });
      }
      if (operation.kind === "update") {
        return client.updateCampaignAlias(actionId, aliasId, {
          commandId,
          revision: operation.item.revision,
          targetActionId: operation.targetActionId,
          alias: operation.alias,
          enabled: operation.enabled,
        });
      }
      return client.createCampaignAlias(actionId, {
        commandId,
        aliasId,
        alias: operation.alias,
        enabled: operation.enabled,
      });
    },
    async onSuccess(result, operation) {
      command.current = undefined;
      setError(undefined);
      toast?.show({
        title:
          operation.kind === "remove"
            ? `/${result.alias} ist entfernt.`
            : operation.kind === "update" &&
                operation.targetActionId !== actionId
              ? `/${result.alias} zeigt jetzt auf eine andere Aktion.`
              : `/${result.alias} ist gespeichert.`,
        tone: "success",
      });
      await onDone();
    },
    onError(cause, operation) {
      setError(actionErrorMessage(cause));
      // The confirmation closes; the error shows under the list.
      if (operation.kind === "remove") onRemoveFailed();
    },
  });
  return { error, mutation, setError };
}

function AliasError({ error }: { readonly error?: ActionErrorMessage }) {
  if (!error) return null;
  return (
    <StatusMessage tone="error">
      <span>{error.message}</span>
      {isRevisionConflict(error) || error.conflict ? (
        <span> Ihre Eingaben bleiben erhalten.</span>
      ) : null}
    </StatusMessage>
  );
}

function AliasModal({
  actionId,
  canonicalPath,
  error,
  item,
  onClose,
  onSubmit,
  open,
  pending,
  targets,
}: {
  readonly actionId: string;
  readonly canonicalPath: string;
  readonly error?: ActionErrorMessage;
  /** Edit this alias; without it the modal adds a new one. */
  readonly item?: CampaignAliasItemResponse;
  readonly onClose: () => void;
  readonly onSubmit: (operation: Operation) => void;
  readonly open: boolean;
  readonly pending: boolean;
  readonly targets: readonly CampaignAliasTargetResponse[];
}) {
  const formId = useId();
  const [alias, setAlias] = useState(item?.alias ?? "");
  const [enabled, setEnabled] = useState(item?.enabled ?? true);
  const [targetActionId, setTargetActionId] = useState(actionId);
  const [submitted, setSubmitted] = useState(false);
  const aliasError = ALIAS.test(alias.trim())
    ? ""
    : "Nur Kleinbuchstaben, Ziffern und Bindestriche, zum Beispiel „krapfen-flyer“.";
  const target = targets.find((entry) => entry.actionId === targetActionId);
  const moving = Boolean(item) && targetActionId !== actionId;

  return (
    <Modal
      description={
        item
          ? `Weiterleitung von /${item.alias} auf ${canonicalPath}.`
          : `Eine weitere kurze Adresse, die auf ${canonicalPath} weiterleitet, zum Beispiel für Flyer.`
      }
      footer={
        <>
          <Button disabled={pending} onClick={onClose} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="alias-save"
            form={formId}
            loading={pending}
            type="submit"
            variant="primary"
          >
            {moving ? "Alias umstellen" : "Speichern"}
          </Button>
        </>
      }
      onClose={() => {
        if (!pending) onClose();
      }}
      open={open}
      title={item ? `/${item.alias} bearbeiten` : "Alias hinzufügen"}
    >
      <form
        className="form-grid"
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(true);
          if (aliasError) return;
          onSubmit(
            item
              ? {
                  kind: "update",
                  item,
                  alias: alias.trim(),
                  enabled,
                  targetActionId,
                }
              : { kind: "create", alias: alias.trim(), enabled },
          );
        }}
      >
        <Field
          error={submitted ? aliasError : undefined}
          hint="Ohne Domain und ohne Schrägstrich."
          label="Alias"
          required
        >
          <Input
            autoComplete="off"
            className="mono"
            data-testid="alias-input"
            maxLength={160}
            onChange={(event) => setAlias(event.currentTarget.value)}
            value={alias}
          />
        </Field>
        <Field
          hint="Auch aktiviert ist der Alias nur erreichbar, solange die Aktion öffentlich freigegeben ist."
          label="Weiterleitung"
        >
          <select
            className="input select"
            data-testid="alias-enabled"
            onChange={(event) =>
              setEnabled(event.currentTarget.value === "enabled")
            }
            value={enabled ? "enabled" : "disabled"}
          >
            <option value="enabled">Aktiviert</option>
            <option value="disabled">Deaktiviert</option>
          </select>
        </Field>
        {item ? (
          <Field
            hint="Sie sehen nur Aktionen, deren Adressen Sie verwalten dürfen."
            label="Ziel"
          >
            <select
              className="input select"
              data-testid="alias-target"
              onChange={(event) => setTargetActionId(event.currentTarget.value)}
              value={targetActionId}
            >
              {!targets.some((entry) => entry.actionId === targetActionId) ? (
                <option disabled value={targetActionId}>
                  Ziel nicht mehr verfügbar, bitte neu wählen
                </option>
              ) : null}
              {targets.map((entry) => (
                <option key={entry.actionId} value={entry.actionId}>
                  {entry.name} · {entry.canonicalPath}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        {moving && item ? (
          <div className="callout">
            <Icon icon={Info} size={16} />
            <span>
              Wer /{item.alias} aufruft, sieht danach{" "}
              {target?.name ?? "die neue Aktion"}. Diese Aktion bleibt unter{" "}
              {canonicalPath} erreichbar; bereits eingegangene Bestellungen
              ändern sich nicht.
            </span>
          </div>
        ) : null}
        <AliasError error={error} />
      </form>
    </Modal>
  );
}

/**
 * Aliase (prototype Campaigns.tsx Aliases): the active alias from the
 * publication, the extra redirect aliases and the permanent archive
 * address. The server lists the targets this account may manage.
 */
export function CampaignAliasesSection(props: Props) {
  const queryClient = useQueryClient();
  const queryKey = ["campaign-aliases", props.actionId] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => props.client.listCampaignAliases(props.actionId),
    retry: false,
    staleTime: 0,
  });
  const [editing, setEditing] = useState<
    CampaignAliasItemResponse | "new" | null
  >(null);
  const [removing, setRemoving] = useState<CampaignAliasItemResponse>();
  const saved = async () => {
    setEditing(null);
    setRemoving(undefined);
    await queryClient.invalidateQueries({ queryKey });
    await queryClient.invalidateQueries({
      queryKey: ["campaign-alias-availability"],
    });
  };
  const { error, mutation, setError } = useAliasCommand(
    props.actionId,
    props.client,
    saved,
    () => setRemoving(undefined),
  );

  if (query.isPending) return <SkeletonRows rows={3} />;
  if (query.isError) {
    return (
      <ErrorState
        onRetry={() => void query.refetch()}
        title="Die Aliase konnten nicht geladen werden"
      >
        Der Server hat nicht geantwortet. Prüfen Sie die Verbindung und
        versuchen Sie es erneut.
      </ErrorState>
    );
  }

  const data: CampaignAliasListResponse = query.data;
  const extra = data.items.filter((item) => !item.isPrimary);
  const primary = data.items.find((item) => item.isPrimary);

  return (
    <section
      aria-labelledby={`campaign-aliases-${props.actionId}`}
      className="stack"
    >
      <h2 className="sr-only" id={`campaign-aliases-${props.actionId}`}>
        Adressen und Weiterleitungen
      </h2>
      <div className="tab-head">
        <p className="muted small">
          Der aktive Alias ist die kurze Adresse für Flyer und QR-Codes. Weitere
          Aliase leiten auf diese Aktion weiter; die Archivadresse bleibt
          dauerhaft erreichbar.
        </p>
        {!props.disabled ? (
          <Button
            data-testid="alias-add"
            icon={Plus}
            onClick={() => {
              setError(undefined);
              setEditing("new");
            }}
            variant="secondary"
          >
            Alias hinzufügen
          </Button>
        ) : null}
      </div>
      {data.items.length === 0 && !data.canonicalPath ? (
        <EmptyState
          description="Diese Aktion ist noch nicht veröffentlicht."
          icon={Tag}
          title="Keine öffentliche Adresse"
        />
      ) : (
        <ul className="alias-list" data-testid="alias-list">
          {primary ? (
            <li className="alias-row" data-testid="alias-primary">
              <a className="mono alias-path" href={`/${primary.alias}`}>
                /{primary.alias}
              </a>
              <Badge tone="ok">Aktiver Alias</Badge>
              <span className="small subtle">
                Zeitraum und Alias unter „Öffentliche Seite“
              </span>
            </li>
          ) : null}
          {extra.map((item) => (
            <li
              className="alias-row campaign-alias-row"
              data-testid={`alias-${item.alias}`}
              key={item.aliasId}
            >
              <a className="mono alias-path" href={`/${item.alias}`}>
                /{item.alias}
              </a>
              <Badge tone={item.enabled ? "neutral" : "warn"}>
                {item.enabled ? "Weiterleitung" : "Deaktiviert"}
              </Badge>
              <AliasAvailability client={props.client} item={item} />
              {!props.disabled ? (
                <span className="alias-commands">
                  <Button
                    aria-label={`/${item.alias} bearbeiten`}
                    icon={Pencil}
                    onClick={() => {
                      setError(undefined);
                      setEditing(item);
                    }}
                    size="sm"
                    variant="ghost"
                  >
                    Bearbeiten
                  </Button>
                  <Button
                    aria-label={`/${item.alias} entfernen`}
                    icon={Trash2}
                    onClick={() => {
                      setError(undefined);
                      setRemoving(item);
                    }}
                    size="sm"
                    variant="ghost"
                  >
                    Entfernen
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
          <li className="alias-row" data-testid="alias-canonical">
            <a className="mono alias-path" href={data.canonicalPath}>
              {data.canonicalPath}
            </a>
            <Badge tone="neutral">Dauerhafte Adresse</Badge>
          </li>
        </ul>
      )}
      {extra.length === 0 ? (
        <p className="small subtle">
          Noch keine weiteren Aliase. Legen Sie zum Beispiel eine kurze Adresse
          für Flyer an.
        </p>
      ) : null}
      {!editing ? <AliasError error={error} /> : null}

      {editing ? (
        <AliasModal
          actionId={props.actionId}
          canonicalPath={data.canonicalPath}
          error={error}
          item={editing === "new" ? undefined : editing}
          key={editing === "new" ? "new" : editing.aliasId}
          onClose={() => setEditing(null)}
          onSubmit={(operation) => mutation.mutate(operation)}
          open
          pending={mutation.isPending}
          targets={data.targets}
        />
      ) : null}
      <ConfirmDialog
        confirmLabel="Entfernen bestätigen"
        description={
          removing
            ? `/${removing.alias} entfernen? Der Alias ist danach wieder für andere Aktionen frei. Die Aktionsseite bleibt bestehen.`
            : ""
        }
        onConfirm={() => {
          if (removing) mutation.mutate({ kind: "remove", item: removing });
        }}
        onOpenChange={(next) => {
          if (!next && !mutation.isPending) setRemoving(undefined);
        }}
        open={Boolean(removing)}
        pending={mutation.isPending}
        title="Alias entfernen?"
        tone="danger"
      />
    </section>
  );
}
