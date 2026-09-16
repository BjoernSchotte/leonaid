import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import "./picker.css";

type Material = Awaited<ReturnType<LeonAidApiClient["getMaterial"]>>;
export function MaterialPicker({
  client,
  onInsert,
  onClose,
}: {
  client: LeonAidApiClient;
  onInsert: (materialId: string, version: number) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Material | null>(null);
  const [version, setVersion] = useState(1);
  const materials = useQuery({
    queryKey: ["materials", "picker", search, offset],
    queryFn: () => client.listMaterials({ search, offset }),
    retry: false,
  });
  const metadata = useQuery({
    queryKey: ["material-version", selected?.id, version],
    queryFn: () => client.getMaterialVersion(selected!.id, version),
    enabled: !!selected,
    retry: false,
  });
  return (
    <section className="material-picker" aria-label="Material verknüpfen">
      <h2>Material verknüpfen</h2>
      <p>
        Die gewählte Dateiversion bleibt fest verknüpft. Ein Verweis erteilt
        keinen zusätzlichen Materialzugriff.
      </p>
      <label>
        Materialien zum Verknüpfen suchen
        <input
          autoFocus
          type="search"
          maxLength={200}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      {materials.isPending && <p role="status">Materialien werden geladen …</p>}
      {materials.error && (
        <StatusMessage tone="error">
          Materialien konnten nicht geladen werden.{" "}
          <Button variant="secondary" onClick={() => void materials.refetch()}>
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      {materials.data && !materials.error && (
        <>
          <ul>
            {materials.data.items.map((item) => (
              <li key={item.id}>
                <Button
                  variant="secondary"
                  aria-pressed={selected?.id === item.id}
                  onClick={() => {
                    setSelected(item);
                    setVersion(item.currentVersion);
                  }}
                >
                  {item.title}
                </Button>
              </li>
            ))}
          </ul>
          {!materials.data.items.length && (
            <p>
              Keine passenden Materialien. Lade Dateien bei Bedarf zuerst im
              Bereich Materialien hoch.
            </p>
          )}
          <div className="material-picker-paging">
            <Button
              variant="secondary"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Vorherige Materialien
            </Button>
            <Button
              variant="secondary"
              disabled={materials.data.nextOffset === null}
              onClick={() => setOffset(materials.data!.nextOffset!)}
            >
              Weitere Materialien
            </Button>
          </div>
        </>
      )}
      {selected && (
        <>
          <p>Ausgewählt: {selected.title}</p>
          <label>
            Verknüpfte Dateiversion
            <input
              type="number"
              min={1}
              max={selected.currentVersion}
              step={1}
              value={version}
              onChange={(event) => {
                const value = event.target.valueAsNumber;
                if (
                  Number.isInteger(value) &&
                  value >= 1 &&
                  value <= selected.currentVersion
                )
                  setVersion(value);
              }}
            />
          </label>
          {metadata.isPending && (
            <p role="status">Dateiversion wird geprüft …</p>
          )}
          {metadata.error && (
            <StatusMessage tone="error">
              Diese Dateiversion ist nicht verfügbar.{" "}
              <Button
                variant="secondary"
                onClick={() => void metadata.refetch()}
              >
                Dateiversion erneut prüfen
              </Button>
            </StatusMessage>
          )}
          {metadata.data && !metadata.error && (
            <p>
              {metadata.data.filename} · Dateiversion {metadata.data.version}
            </p>
          )}
          <Button
            disabled={!metadata.data || !!metadata.error || metadata.isFetching}
            onClick={() => onInsert(selected.id, version)}
          >
            Dateiversion einfügen
          </Button>
        </>
      )}
      <Button variant="secondary" onClick={onClose}>
        Materialauswahl schließen
      </Button>
    </section>
  );
}
