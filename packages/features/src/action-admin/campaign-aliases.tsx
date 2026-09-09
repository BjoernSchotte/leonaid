import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import type {
  CampaignAliasItemResponse,
  CampaignAliasTargetResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import { actionErrorMessage } from "./errors";

interface Props {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly disabled: boolean;
}

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
    <p role="status">
      {!item.enabled
        ? "Deaktiviert"
        : query.isPending
          ? "Freigabe wird geprüft …"
          : query.isError
            ? "Core-Freigabe derzeit nicht prüfbar."
            : query.data.redirectPath
              ? "Core-Freigabe aktiv. Die Zielseite benötigt zusätzlich veröffentlichte Inhalte."
              : "Keine öffentliche Weiterleitung freigegeben."}
    </p>
  );
}

function AliasEditor({
  actionId,
  client,
  disabled,
  item,
  saved,
  targets,
}: Props & {
  readonly item?: CampaignAliasItemResponse;
  readonly saved: () => Promise<void>;
  readonly targets: readonly CampaignAliasTargetResponse[];
}) {
  const [alias, setAlias] = useState(item?.alias ?? "");
  const [enabled, setEnabled] = useState(item?.enabled ?? true);
  const [revision, setRevision] = useState(item?.revision ?? 0);
  const [targetActionId, setTargetActionId] = useState(actionId);
  const [remove, setRemove] = useState(false);
  const [feedback, setFeedback] = useState<{
    message: string;
    error: boolean;
    conflict?: boolean;
  }>();
  const command = useRef<
    | {
        fingerprint: string;
        commandId: string;
        aliasId: string;
      }
    | undefined
  >(undefined);
  const mutation = useMutation({
    mutationFn: async (operation: "save" | "remove") => {
      const payload = {
        alias: alias.trim(),
        enabled,
        revision,
        operation,
        targetActionId,
      };
      const fingerprint = JSON.stringify(payload);
      if (command.current?.fingerprint !== fingerprint) {
        command.current = {
          fingerprint,
          commandId: crypto.randomUUID(),
          aliasId: item?.aliasId ?? crypto.randomUUID(),
        };
      }
      const { commandId, aliasId } = command.current;
      if (item && operation === "remove") {
        return client.removeCampaignAlias(actionId, aliasId, {
          commandId,
          revision,
        });
      }
      if (item) {
        return client.updateCampaignAlias(actionId, aliasId, {
          commandId,
          revision,
          targetActionId,
          alias: payload.alias,
          enabled,
        });
      }
      return client.createCampaignAlias(actionId, {
        commandId,
        aliasId,
        alias: payload.alias,
        enabled,
      });
    },
    async onSuccess(result) {
      command.current = undefined;
      setRevision(result.revision);
      if (!item) setAlias("");
      setFeedback({ message: "Die Adresse wurde gespeichert.", error: false });
      await saved();
    },
    onError(error) {
      const details = actionErrorMessage(error);
      setFeedback({
        message: details.message,
        error: true,
        conflict: details.conflict,
      });
    },
  });
  return (
    <form
      className="campaign-alias-editor"
      onSubmit={(event) => {
        event.preventDefault();
        setFeedback(undefined);
        mutation.mutate("save");
      }}
    >
      <fieldset disabled={disabled || mutation.isPending}>
        <div className="action-form-grid">
          {item ? (
            <label className="action-field action-field--wide">
              <span>Zielkampagne</span>
              <select
                value={targetActionId}
                onChange={(event) =>
                  setTargetActionId(event.currentTarget.value)
                }
                required
              >
                {!targets.some(
                  (target) => target.actionId === targetActionId,
                ) ? (
                  <option value={targetActionId} disabled>
                    Ziel nicht mehr verfügbar — bitte neu wählen
                  </option>
                ) : null}
                {targets.map((target) => (
                  <option key={target.actionId} value={target.actionId}>
                    {target.name} · {target.canonicalPath}
                  </option>
                ))}
              </select>
              <small>
                {targetActionId !== actionId
                  ? "Nach dem Speichern wird diese Adresse bei der Zielkampagne verwaltet. Die bisherige Kampagnenseite bleibt unverändert."
                  : "Core zeigt nur Kampagnen an, deren Adressen du verwalten darfst."}
              </small>
            </label>
          ) : null}
          <label className="action-field">
            <span>{item ? "Kurzadresse bearbeiten" : "Neue Kurzadresse"}</span>
            <input
              required
              maxLength={160}
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              value={alias}
              onChange={(event) => setAlias(event.currentTarget.value)}
            />
            <small>
              Nur Kleinbuchstaben, Ziffern und Bindestriche; ohne Domain oder
              Schrägstrich.
            </small>
          </label>
          <label className="action-field">
            <span>Weiterleitung</span>
            <select
              value={enabled ? "enabled" : "disabled"}
              onChange={(event) =>
                setEnabled(event.currentTarget.value === "enabled")
              }
            >
              <option value="enabled">Aktiviert</option>
              <option value="disabled">Deaktiviert</option>
            </select>
            <small>
              Auch aktiviert nur während der Freigabe durch Core erreichbar.
            </small>
          </label>
        </div>
        <div className="action-form-actions">
          <Button type="submit" variant="secondary">
            {mutation.isPending
              ? "Wird gespeichert …"
              : item
                ? "Änderungen speichern"
                : "Adresse hinzufügen"}
          </Button>
          {item && !remove ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setRemove(true)}
            >
              Adresse entfernen
            </Button>
          ) : null}
        </div>
        {remove ? (
          <StatusMessage>
            <p>
              /{item?.alias} entfernen? Die Adresse ist anschließend wieder für
              andere Kampagnen verfügbar. Die Kampagnenseite bleibt bestehen.
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={() => mutation.mutate("remove")}
            >
              Entfernen bestätigen
            </Button>{" "}
            <Button
              type="button"
              variant="ghost"
              onClick={() => setRemove(false)}
            >
              Abbrechen
            </Button>
          </StatusMessage>
        ) : null}
      </fieldset>
      {feedback ? (
        <StatusMessage tone={feedback.error ? "error" : "success"}>
          {feedback.message}
          {feedback.conflict ? (
            <p>
              Deine Eingaben bleiben erhalten.{" "}
              <a
                href={`${window.location.pathname}#public`}
                target="_blank"
                rel="noreferrer"
              >
                Aktuellen Stand in einem neuen Tab öffnen
              </a>
            </p>
          ) : null}
        </StatusMessage>
      ) : null}
    </form>
  );
}

export function CampaignAliasesSection(props: Props) {
  const queryClient = useQueryClient();
  const queryKey = ["campaign-aliases", props.actionId] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => props.client.listCampaignAliases(props.actionId),
    retry: false,
    staleTime: 0,
  });
  const saved = async () => {
    await queryClient.invalidateQueries({ queryKey });
    await queryClient.invalidateQueries({
      queryKey: ["campaign-alias-availability"],
    });
  };
  return (
    <section
      className="action-edit-section"
      aria-labelledby="campaign-aliases-heading"
    >
      <header>
        <div>
          <h2 id="campaign-aliases-heading">Adressen und Weiterleitungen</h2>
          <p>
            Zusätzliche Kurzadressen führen zur dauerhaften Seite dieser
            Kampagne.
          </p>
        </div>
      </header>
      {query.isPending ? (
        <StatusMessage>Adressen werden geladen …</StatusMessage>
      ) : query.isError ? (
        <StatusMessage tone="error">
          Adressen konnten nicht geladen werden.{" "}
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Erneut laden
          </Button>
        </StatusMessage>
      ) : (
        <>
          <p className="campaign-alias-address">
            Dauerhafte Kampagnenadresse:{" "}
            <a href={query.data.canonicalPath}>{query.data.canonicalPath}</a>
          </p>
          {query.data.items.map((item) =>
            item.isPrimary ? (
              <p className="campaign-alias-address" key={item.aliasId}>
                Hauptadresse: <a href={`/${item.alias}`}>/{item.alias}</a>.
                Änderungen erfolgen oben unter „Öffentliche Seite“.
              </p>
            ) : (
              <div className="campaign-alias-row" key={item.aliasId}>
                <p className="campaign-alias-address">
                  <a href={`/${item.alias}`}>/{item.alias}</a> →{" "}
                  {query.data.canonicalPath}
                </p>
                <AliasAvailability client={props.client} item={item} />
                <AliasEditor
                  {...props}
                  item={item}
                  saved={saved}
                  targets={query.data.targets}
                />
              </div>
            ),
          )}
          {!query.data.items.some((item) => !item.isPrimary) ? (
            <p>
              Noch keine zusätzlichen Adressen. Lege beispielsweise eine kurze
              Adresse für Flyer an.
            </p>
          ) : null}
          <AliasEditor {...props} saved={saved} targets={query.data.targets} />
        </>
      )}
    </section>
  );
}
