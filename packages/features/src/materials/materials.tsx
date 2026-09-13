import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import { AccessMembersPanel } from "../shared/access-members";
import {
  ActionContextSearch,
  useActionContexts,
} from "../shared/action-contexts";
import "./materials.css";

type Material = Awaited<ReturnType<LeonAidApiClient["getMaterial"]>>;

function Upload({
  client,
  material,
  canEdit = true,
  onCreated,
}: {
  client: LeonAidApiClient;
  material?: Material;
  canEdit?: boolean;
  onCreated?: (material: Material) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [actionId, setActionId] = useState("");
  const [revision, setRevision] = useState(material?.revision);
  const [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const key = useRef(crypto.randomUUID());
  const cache = useQueryClient();
  const contexts = useActionContexts(client);
  const upload = useMutation({
    mutationFn: () => {
      if (!file || file.size < 1 || file.size > 25 * 1024 * 1024)
        throw new Error("Dateigröße ungültig");
      return material
        ? client.addMaterialVersion(material.id, {
            file,
            expectedRevision: revision!,
            idempotencyKey: key.current,
          })
        : client.createMaterial({
            file,
            title: title.trim(),
            actionId: actionId || null,
            idempotencyKey: key.current,
          });
    },
    onSuccess: async (result) => {
      setFile(null);
      setTitle("");
      setRevision(result.revision);
      key.current = crypto.randomUUID();
      if (input.current) input.current.value = "";
      setNotice(`Dateiversion ${result.currentVersion} wurde gespeichert.`);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["materials"] }),
        cache.invalidateQueries({ queryKey: ["material", result.id] }),
      ]);
      onCreated?.(result);
    },
  });
  const changed = () => {
    key.current = crypto.randomUUID();
    upload.reset();
    setNotice("");
  };
  const valid = file && file.size > 0 && file.size <= 25 * 1024 * 1024;
  useEffect(() => {
    if (!file) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [file]);
  if (!canEdit && !file) return null;
  return (
    <form
      className="material-upload"
      onSubmit={(event) => {
        event.preventDefault();
        upload.mutate();
      }}
    >
      <h2>{material ? "Neue Dateiversion" : "Material hochladen"}</h2>
      {notice && <p role="status">{notice}</p>}
      {upload.error && (
        <StatusMessage tone="error">
          {upload.error instanceof ApiError && upload.error.status === 409
            ? "Das Material wurde inzwischen geändert oder dieser Upload hat einen Konflikt. Die Dateiauswahl bleibt erhalten. Lade die Seite neu und wähle die Datei erneut aus."
            : "Upload fehlgeschlagen. Die Dateiauswahl bleibt erhalten. Prüfe deinen Zugriff und versuche es erneut."}
        </StatusMessage>
      )}
      {!canEdit && (
        <p role="status">
          Du hast momentan kein Bearbeitungsrecht. Deine Dateiauswahl bleibt
          erhalten.
        </p>
      )}
      <fieldset disabled={upload.isPending || !canEdit}>
        {!material && (
          <>
            <label>
              Materialtitel
              <input
                required
                maxLength={240}
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  changed();
                }}
              />
            </label>
            <ActionContextSearch contexts={contexts} />
            <label>
              Kontext des Materials
              <select
                value={actionId}
                onChange={(e) => {
                  setActionId(e.target.value);
                  changed();
                }}
              >
                <option value="">Eigenständig</option>
                {actionId &&
                  !contexts.managedActions.some(([id]) => id === actionId) && (
                    <option value={actionId}>
                      Ausgewählte Aktion beibehalten
                    </option>
                  )}
                {contexts.managedActions.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <p>
              {actionId
                ? "Aktuelle Mitglieder dieser Aktion können das Material lesen. Zusätzliche Bearbeitungsrechte verwaltet die Aktionsverwaltung."
                : "Das neue Material ist zunächst nur für dich sichtbar."}
            </p>
          </>
        )}
        <label>
          Datei
          <input
            ref={input}
            type="file"
            required
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setRevision(material?.revision);
              changed();
            }}
          />
        </label>
        <p>
          Eine Datei bis 25 MiB. Neue Versionen erhalten frühere Dateistände.
        </p>
        {file && !valid && (
          <StatusMessage tone="error">
            Die Datei ist leer oder größer als 25 MiB.
          </StatusMessage>
        )}
        <Button type="submit" disabled={!valid || (!material && !title.trim())}>
          {upload.isPending
            ? "Wird hochgeladen …"
            : material
              ? "Neue Version hochladen"
              : "Hochladen"}
        </Button>
      </fieldset>
    </form>
  );
}

function Detail({
  client,
  materialId,
  basePath,
}: {
  client: LeonAidApiClient;
  materialId: string;
  basePath: string;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const material = useQuery({
    queryKey: ["material", materialId],
    queryFn: () => client.getMaterial(materialId),
    retry: false,
  });
  const rights = useQuery({
    queryKey: ["material-permissions", materialId],
    queryFn: () => client.getMaterialPermissions(materialId),
    retry: false,
    refetchInterval: 30000,
  });
  const number = selected ?? material.data?.currentVersion;
  const version = useQuery({
    queryKey: ["material-version", materialId, number],
    queryFn: () => client.getMaterialVersion(materialId, number!),
    enabled: !!number && !!material.data && !material.error,
    retry: false,
  });
  const download = useMutation({
    mutationFn: async () => {
      const metadata = version.data!;
      const blob = await client.downloadMaterialVersion(
        materialId,
        metadata.version,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = metadata.filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  return (
    <>
      <a href={basePath}>Zur Materialübersicht</a>
      {material.isPending && <p role="status">Material wird geladen …</p>}
      {(material.error || rights.error) && (
        <StatusMessage tone="error">
          Das Material ist nicht verfügbar oder dein Zugriff wurde geändert.{" "}
          <Button
            variant="secondary"
            onClick={() => {
              void material.refetch();
              void rights.refetch();
            }}
          >
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      {material.data && (
        <>
          <header>
            <h1>{material.data.title}</h1>
            <p>
              {material.data.actionId
                ? "Aktionsmaterial"
                : "Eigenständiges Material"}{" "}
              · Aktuelle Dateiversion {material.data.currentVersion}
            </p>
          </header>
          {rights.data?.canManage && !rights.error && !material.error && (
            <AccessMembersPanel
              client={client}
              objectId={materialId}
              kind="material"
              actionScoped={!!material.data.actionId}
            />
          )}
          <label>
            Dateiversion
            <input
              type="number"
              min={1}
              max={material.data.currentVersion}
              step={1}
              value={number ?? 1}
              onChange={(event) => {
                const value = event.target.valueAsNumber;
                if (
                  Number.isInteger(value) &&
                  value >= 1 &&
                  value <= material.data!.currentVersion
                ) {
                  setSelected(value);
                  download.reset();
                }
              }}
            />
          </label>
          {version.isPending && (
            <p role="status">Dateiversion wird geladen …</p>
          )}
          {version.error && (
            <StatusMessage tone="error">
              Die Dateiversion ist nicht verfügbar.{" "}
              <Button
                variant="secondary"
                onClick={() => void version.refetch()}
              >
                Erneut laden
              </Button>
            </StatusMessage>
          )}
          {version.data &&
            !version.error &&
            !material.error &&
            !rights.error && (
              <div>
                <p>
                  {version.data.filename} ·{" "}
                  {new Intl.NumberFormat("de-DE").format(
                    version.data.sizeBytes,
                  )}{" "}
                  Bytes
                </p>
                <Button
                  disabled={download.isPending}
                  onClick={() => download.mutate()}
                >
                  {download.isPending
                    ? "Download wird vorbereitet …"
                    : "Dateiversion herunterladen"}
                </Button>
              </div>
            )}
          {download.error && (
            <StatusMessage tone="error">
              Download fehlgeschlagen. Prüfe deinen Zugriff und versuche es
              erneut.
            </StatusMessage>
          )}
          <Upload
            client={client}
            material={material.data}
            canEdit={!!rights.data?.canEdit && !rights.error && !material.error}
          />
        </>
      )}
    </>
  );
}

export function MaterialsPage({
  client,
  materialId,
  basePath,
}: ModulePageContext & { materialId?: string; basePath: string }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [actionId, setActionId] = useState("");
  const contexts = useActionContexts(client);
  const materials = useQuery({
    queryKey: ["materials", search, offset, actionId],
    queryFn: () =>
      client.listMaterials({ search, offset, actionId: actionId || undefined }),
    enabled: !materialId,
    retry: false,
  });
  return (
    <section className="materials-workspace">
      {materialId ? (
        <Detail client={client} materialId={materialId} basePath={basePath} />
      ) : (
        <>
          <header>
            <h1>Materialien</h1>
            <p>Dateien gemeinsam nutzen und frühere Versionen behalten.</p>
          </header>
          <details>
            <summary>Neues Material</summary>
            <Upload
              client={client}
              onCreated={(result) =>
                window.location.assign(`${basePath}/${result.id}`)
              }
            />
          </details>
          <ActionContextSearch contexts={contexts} />
          <label>
            Materialien nach Aktion filtern
            <select
              value={actionId}
              onChange={(e) => {
                setActionId(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Alle zugänglichen Materialien</option>
              {actionId &&
                !contexts.knownActions.some(([id]) => id === actionId) && (
                  <option value={actionId}>
                    Ausgewählte Aktion beibehalten
                  </option>
                )}
              {contexts.knownActions.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Materialien suchen
            <input
              type="search"
              maxLength={200}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
            />
          </label>
          {materials.isPending && (
            <p role="status">Materialien werden geladen …</p>
          )}
          {materials.error && (
            <StatusMessage tone="error">
              Materialien konnten nicht geladen werden.{" "}
              <Button
                variant="secondary"
                onClick={() => void materials.refetch()}
              >
                Erneut laden
              </Button>
            </StatusMessage>
          )}
          {materials.data && !materials.error && (
            <>
              <ul className="material-results">
                {materials.data.items.map((item) => (
                  <li key={item.id}>
                    <h2>
                      <a href={`${basePath}/${item.id}`}>{item.title}</a>
                    </h2>
                    <p>
                      {item.actionId
                        ? "Aktionsmaterial"
                        : "Eigenständiges Material"}{" "}
                      · Dateiversion {item.currentVersion}
                    </p>
                  </li>
                ))}
              </ul>
              {!materials.data.items.length && (
                <p>
                  Keine passenden Materialien. Hier erscheinen Dateien, auf die
                  du Zugriff hast.
                </p>
              )}
              <nav aria-label="Material-Ergebnisseiten">
                <Button
                  variant="secondary"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Zurück
                </Button>{" "}
                <Button
                  variant="secondary"
                  disabled={materials.data.nextOffset === null}
                  onClick={() => setOffset(materials.data!.nextOffset!)}
                >
                  Weitere Materialien
                </Button>
              </nav>
            </>
          )}
        </>
      )}
    </section>
  );
}
