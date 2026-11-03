import {
  Download01Icon,
  Link01Icon,
  RefreshIcon,
  Unlink01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  ApiError,
  type Case,
  type LeonAidApiClient,
  type MaterialVersion,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import { MaterialPicker } from "../materials/picker";
import { downloadMaterial } from "../materials/download";

export function InboxMaterials({
  client,
  item,
}: {
  client: LeonAidApiClient;
  item: Case;
}) {
  const cache = useQueryClient();
  const [picking, setPicking] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef<{ key: string; signature: string } | null>(null);
  const references = useQuery({
    queryKey: ["inbox-materials", item.id],
    queryFn: () => client.listInboxMaterialReferences(item.id),
    retry: false,
    refetchInterval: 30000,
  });
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
      cache.setQueryData(["inbox-case", item.id], value);
      void cache.invalidateQueries({ queryKey: ["inbox-materials", item.id] });
      void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
      pending.current = null;
      setPicking(false);
      setNotice("Materialverweise aktualisiert.");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void cache.invalidateQueries({ queryKey: ["inbox-case", item.id] });
    },
  });
  const download = useMutation({
    mutationFn: (file: MaterialVersion) => downloadMaterial(client, file),
  });
  return (
    <section aria-labelledby="inbox-materials-heading">
      <h2 id="inbox-materials-heading">Materialien</h2>
      <p>
        Verknüpfte Dateiversionen bleiben erhalten. Das Entfernen eines
        Verweises löscht keine Datei.
      </p>
      {references.isPending && (
        <p role="status">Materialverweise werden geladen …</p>
      )}
      {references.error && (
        <StatusMessage tone="error">
          <p>Materialverweise konnten nicht geladen werden.</p>
          <Button
            icon={
              <HugeiconsIcon
                icon={RefreshIcon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="secondary"
            onClick={() => void references.refetch()}
          >
            Materialverweise erneut laden
          </Button>
        </StatusMessage>
      )}
      {!references.error && references.data && (
        <ul className="inbox-results">
          {references.data.items.map((reference) => (
            <li key={`${reference.materialId}:${reference.materialVersion}`}>
              <p>
                {reference.file
                  ? `${reference.file.filename} · Dateiversion ${reference.materialVersion}`
                  : "Material nicht verfügbar"}
              </p>
              <div className="inbox-paging">
                {reference.file && (
                  <Button
                    icon={
                      <HugeiconsIcon
                        icon={Download01Icon}
                        size={16}
                        strokeWidth={1.7}
                        aria-hidden="true"
                      />
                    }
                    variant="secondary"
                    disabled={download.isPending}
                    onClick={() => download.mutate(reference.file!)}
                  >
                    Dateiversion herunterladen
                  </Button>
                )}
                <Button
                  icon={
                    <HugeiconsIcon
                      icon={Unlink01Icon}
                      size={16}
                      strokeWidth={1.7}
                      aria-hidden="true"
                    />
                  }
                  variant="secondary"
                  disabled={change.isPending}
                  onClick={() => {
                    setNotice("");
                    change.mutate({
                      materialId: reference.materialId,
                      materialVersion: reference.materialVersion,
                      present: false,
                    });
                  }}
                >
                  Verweis entfernen
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!references.error && references.data?.items.length === 0 && (
        <p>Noch keine Materialien verknüpft.</p>
      )}
      <Button
        icon={
          <HugeiconsIcon
            icon={Link01Icon}
            size={16}
            strokeWidth={1.7}
            aria-hidden="true"
          />
        }
        variant="secondary"
        disabled={change.isPending || picking}
        onClick={() => {
          setPicking(true);
          change.reset();
          setNotice("");
        }}
      >
        Material verknüpfen
      </Button>
      {picking && (
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
      )}
      {change.error && (
        <StatusMessage tone="error">
          <p>
            {change.error instanceof ApiError && change.error.status === 409
              ? "Der Fall wurde inzwischen geändert. Prüfe die aktuellen Verweise und wiederhole deine Auswahl."
              : "Der Materialverweis konnte nicht geändert werden. Prüfe deinen Zugriff und versuche es erneut."}
          </p>
        </StatusMessage>
      )}
      {download.error && (
        <StatusMessage tone="error">
          <p>
            Download fehlgeschlagen. Prüfe deinen Zugriff und versuche es
            erneut.
          </p>
        </StatusMessage>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
