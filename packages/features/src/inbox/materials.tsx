import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Paperclip, RefreshCw, Unlink } from "lucide-react";
import { useRef, useState } from "react";

import {
  ApiError,
  type Case,
  type LeonAidApiClient,
  type MaterialVersion,
} from "@leonaid/api-client";
import { Button, IconButton, StatusMessage } from "@leonaid/ui";

import { downloadMaterial } from "../materials/download";
import { MaterialPicker } from "../materials/picker";
import { acceptCases, type Address } from "./inbox-model";
import { InboxLinkButton } from "./tasks";

export const materialReferencesKey = (caseId: string) => [
  "inbox-materials",
  caseId,
];

export function useMaterialReferences(
  client: LeonAidApiClient,
  caseId: string,
) {
  return useQuery({
    queryKey: materialReferencesKey(caseId),
    queryFn: () => client.listInboxMaterialReferences(caseId),
    retry: false,
    refetchInterval: 30000,
  });
}

/**
 * Linked file versions as reference chips (a click downloads that version),
 * plus the picker. Removing a reference deletes no file.
 */
export function InboxMaterials({
  address,
  client,
  item,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly item: Case;
}) {
  const cache = useQueryClient();
  const [picking, setPicking] = useState(false);
  const pending = useRef<{ key: string; signature: string } | null>(null);
  const references = useMaterialReferences(client, item.id);
  const sie = address === "Sie";
  const change = useMutation({
    mutationFn: ({
      materialId,
      materialVersion,
      present,
    }: {
      materialId: string;
      materialVersion: number;
      present: boolean;
    }) => {
      const signature = JSON.stringify([
        materialId,
        materialVersion,
        present,
        item.revision,
      ]);
      if (pending.current?.signature !== signature)
        pending.current = { key: crypto.randomUUID(), signature };
      return client.setInboxMaterialReference(item.id, {
        materialId,
        materialVersion,
        present,
        expectedRevision: item.revision,
        idempotencyKey: pending.current.key,
      });
    },
    onSuccess: (value) => {
      acceptCases(cache, [value]);
      void cache.invalidateQueries({
        queryKey: materialReferencesKey(item.id),
      });
      pending.current = null;
      setPicking(false);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
    },
  });
  const download = useMutation({
    mutationFn: (file: MaterialVersion) => downloadMaterial(client, file),
  });
  return (
    <>
      {references.error ? (
        <StatusMessage tone="error">
          <p>Materialverweise konnten nicht geladen werden.</p>
          <Button
            icon={RefreshCw}
            onClick={() => void references.refetch()}
            size="sm"
            variant="secondary"
          >
            Materialverweise erneut laden
          </Button>
        </StatusMessage>
      ) : null}
      {references.data?.items.map((reference) => {
        const name = reference.file
          ? `${reference.file.filename} · Dateiversion ${reference.materialVersion}`
          : "Material nicht verfügbar";
        return (
          <span
            className="ref-item"
            key={`${reference.materialId}:${reference.materialVersion}`}
          >
            {reference.file ? (
              <button
                className="ref-chip"
                disabled={download.isPending}
                onClick={() => download.mutate(reference.file!)}
                title="Dateiversion herunterladen"
                type="button"
              >
                <Paperclip aria-hidden="true" size={13} />
                {name}
              </button>
            ) : (
              <span className="ref-chip is-missing">
                <Paperclip aria-hidden="true" size={13} />
                {name}
              </span>
            )}
            <IconButton
              disabled={change.isPending}
              icon={Unlink}
              label={`Verweis entfernen: ${name}`}
              onClick={() =>
                change.mutate({
                  materialId: reference.materialId,
                  materialVersion: reference.materialVersion,
                  present: false,
                })
              }
              size="sm"
              variant="ghost"
            />
          </span>
        );
      })}
      <InboxLinkButton
        disabled={change.isPending || picking}
        label="Material verknüpfen"
        onClick={() => {
          setPicking(true);
          change.reset();
        }}
      />
      {picking ? (
        <fieldset className="inbox-picker" disabled={change.isPending}>
          <legend>Dateiversion auswählen</legend>
          <MaterialPicker
            client={client}
            onClose={() => setPicking(false)}
            onInsert={(materialId, materialVersion) =>
              change.mutate({ materialId, materialVersion, present: true })
            }
          />
        </fieldset>
      ) : null}
      {change.error ? (
        <StatusMessage tone="error">
          {change.error instanceof ApiError && change.error.status === 409
            ? sie
              ? "Die Anfrage wurde inzwischen geändert. Prüfen Sie die aktuellen Verweise und wiederholen Sie Ihre Auswahl."
              : "Die Anfrage wurde inzwischen geändert. Prüfe die aktuellen Verweise und wiederhole deine Auswahl."
            : sie
              ? "Der Materialverweis konnte nicht geändert werden. Prüfen Sie Ihren Zugriff und versuchen Sie es erneut."
              : "Der Materialverweis konnte nicht geändert werden. Prüfe deinen Zugriff und versuche es erneut."}
        </StatusMessage>
      ) : null}
      {download.error ? (
        <StatusMessage tone="error">
          {sie
            ? "Download fehlgeschlagen. Prüfen Sie Ihren Zugriff und versuchen Sie es erneut."
            : "Download fehlgeschlagen. Prüfe deinen Zugriff und versuche es erneut."}
        </StatusMessage>
      ) : null}
    </>
  );
}
