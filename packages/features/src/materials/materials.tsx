import {
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ChevronDown,
  Download,
  FileArchive,
  FileImage,
  FileSpreadsheet,
  FileText,
  Package,
  Search,
  Upload as UploadIcon,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  type LeonAidApiClient,
  type Material,
  type MaterialVersion,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  IconButton,
  Kbd,
  Modal,
  ReadOnlyNotice,
  StatusMessage,
  useHotkeys,
  useLeaveGuard,
  useOptionalToast,
} from "@leonaid/ui";

import { consumeCreateRequest } from "../command-palette/create-request";
import { useContextCommands } from "../command-palette/store";
import type { ModulePageContext } from "../modules";
import {
  AccessMembersPanel,
  type AccessMemberSource,
} from "../shared/access-members";
import {
  ActionContextSearch,
  useActionContexts,
} from "../shared/action-contexts";
import { downloadMaterial } from "./download";
import "./materials.css";

type Address = "Sie" | "du";
const says = (address: Address, du: string, sie: string) =>
  address === "du" ? du : sie;

const LIMIT = 25 * 1024 * 1024;
const PAGE = 50;
/** Versions shown before "Ältere Versionen anzeigen". */
const RECENT_VERSIONS = 5;

export function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function fileIcon(name: string | undefined) {
  const lower = (name ?? "").toLowerCase();
  if (lower.endsWith(".zip")) return FileArchive;
  if (/\.(xlsx?|csv|ods)$/.test(lower)) return FileSpreadsheet;
  if (/\.(png|jpe?g|gif|svg|webp)$/.test(lower)) return FileImage;
  return FileText;
}

function versionQuery(client: LeonAidApiClient, id: string, version: number) {
  return {
    queryKey: ["material-version", id, version],
    queryFn: () => client.getMaterialVersion(id, version),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  } as const;
}

function permissionsQuery(client: LeonAidApiClient, id: string) {
  return {
    queryKey: ["material-permissions", id],
    queryFn: () => client.getMaterialPermissions(id),
    retry: false,
    staleTime: 60_000,
  } as const;
}

function materialMemberSource(
  client: LeonAidApiClient,
  materialId: string,
): AccessMemberSource {
  return {
    queryKey: "material-members",
    label: "Materialfreigaben",
    accessLabel: "Materialzugriff",
    subject: "dieses Material",
    list: async (search, offset) => {
      const result = await client.listMaterialMembers(materialId, {
        search,
        offset,
      });
      return { ...result, revision: result.accessRevision };
    },
    change: (command, expectedRevision, idempotencyKey) => {
      const common = {
        expectedAccessRevision: expectedRevision,
        idempotencyKey,
      };
      return "email" in command
        ? client.setMaterialMemberByEmail(materialId, { ...common, ...command })
        : client.setMaterialMember(materialId, { ...common, ...command });
    },
    dependentQueryKeys: [
      ["material-permissions", materialId],
      ["material", materialId],
      ["material-members", materialId, "summary"],
    ],
  };
}

/* ---------- upload dialog ---------- */

type UploadTarget =
  | { readonly kind: "new" }
  | { readonly kind: "version"; readonly material: Material };

function UploadDialog({
  address,
  client,
  onClose,
  onUploaded,
  target,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly onClose: () => void;
  readonly onUploaded: (material: Material, filename: string) => void;
  readonly target: UploadTarget | null;
}) {
  const material = target?.kind === "version" ? target.material : null;
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [actionId, setActionId] = useState("");
  const [touched, setTouched] = useState(false);
  const key = useRef(crypto.randomUUID());
  const contexts = useActionContexts(client);
  const rights = useQuery({
    ...permissionsQuery(client, material?.id ?? ""),
    enabled: !!material,
  });
  const fileError =
    file && (file.size < 1 || file.size > LIMIT)
      ? file.size < 1
        ? "Die Datei ist leer."
        : says(
            address,
            `Die Datei ist ${formatSize(file.size)} groß. Erlaubt sind höchstens 25 MiB – bitte verkleinere sie oder teile sie als ZIP.`,
            `Die Datei ist ${formatSize(file.size)} groß. Erlaubt sind höchstens 25 MiB – bitte verkleinern oder als ZIP teilen.`,
          )
      : undefined;
  const upload = useMutation({
    mutationFn: async () => {
      if (!file || fileError) throw new Error("invalid file");
      if (material) {
        // The current revision, not the one the list loaded long ago.
        const current = await client.getMaterial(material.id);
        return client.addMaterialVersion(material.id, {
          file,
          expectedRevision: current.revision,
          idempotencyKey: key.current,
        });
      }
      return client.createMaterial({
        file,
        title: title.trim(),
        actionId: actionId || null,
        idempotencyKey: key.current,
      });
    },
    onSuccess: (result) => {
      onUploaded(result, file?.name ?? "");
      reset();
      onClose();
    },
  });
  const reset = () => {
    setFile(null);
    setTitle("");
    setActionId("");
    setTouched(false);
    key.current = crypto.randomUUID();
    upload.reset();
  };
  const changed = () => {
    key.current = crypto.randomUUID();
    upload.reset();
  };
  useLeaveGuard(!!target && (!!file || !!title.trim()));
  const readOnly = !!material && rights.data?.canEdit === false;
  const close = () => {
    reset();
    onClose();
  };
  return (
    <Modal
      description={
        material
          ? `${material.title} – die bisherigen Versionen bleiben herunterladbar.`
          : "Flyer, Vorlagen und Logos – jede neue Version behält die früheren."
      }
      footer={
        <>
          <Button onClick={close} variant="ghost">
            Abbrechen
          </Button>
          {readOnly ? null : (
            <Button
              disabled={
                !file ||
                !!fileError ||
                (!material && !title.trim()) ||
                (!!material && rights.isPending)
              }
              form="material-upload-form"
              icon={UploadIcon}
              loading={upload.isPending}
              type="submit"
              variant="primary"
            >
              {upload.isPending ? "Wird hochgeladen …" : "Hochladen"}
            </Button>
          )}
        </>
      }
      onClose={close}
      open={!!target}
      title={material ? "Neue Version hochladen" : "Material hochladen"}
    >
      <form
        className="material-upload"
        id="material-upload-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setTouched(true);
          if (!file || fileError || (!material && !title.trim())) return;
          upload.mutate();
        }}
      >
        {readOnly ? (
          <ReadOnlyNotice>
            {says(
              address,
              "Du kannst dieses Material herunterladen, aber keine neue Version hochladen.",
              "Sie können dieses Material herunterladen, aber keine neue Version hochladen.",
            )}
          </ReadOnlyNotice>
        ) : null}
        {upload.error ? (
          <StatusMessage tone="error">
            {upload.error instanceof ApiError && upload.error.status === 409
              ? says(
                  address,
                  "Das Material wurde inzwischen geändert. Die Dateiauswahl bleibt erhalten; versuche es erneut.",
                  "Das Material wurde inzwischen geändert. Die Dateiauswahl bleibt erhalten; versuchen Sie es erneut.",
                )
              : says(
                  address,
                  "Upload fehlgeschlagen. Die Dateiauswahl bleibt erhalten. Prüfe deinen Zugriff und versuche es erneut.",
                  "Upload fehlgeschlagen. Die Dateiauswahl bleibt erhalten. Prüfen Sie Ihren Zugriff und versuchen Sie es erneut.",
                )}
          </StatusMessage>
        ) : null}
        {material ? null : (
          <>
            <Field
              error={
                touched && !title.trim()
                  ? "Bitte einen Titel angeben."
                  : undefined
              }
              label="Materialtitel"
              required
            >
              <input
                maxLength={240}
                onChange={(event) => {
                  setTitle(event.target.value);
                  changed();
                }}
                value={title}
              />
            </Field>
            <Field
              hint={
                actionId
                  ? "Aktuelle Mitglieder dieser Aktion können das Material lesen. Zusätzliche Bearbeitungsrechte verwaltet die Aktionsverwaltung."
                  : says(
                      address,
                      "Das neue Material ist zunächst nur für dich sichtbar.",
                      "Das neue Material ist zunächst nur für Sie sichtbar.",
                    )
              }
              label="Kontext des Materials"
            >
              <select
                onChange={(event) => {
                  setActionId(event.target.value);
                  changed();
                }}
                value={actionId}
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
            </Field>
            <ActionContextSearch contexts={contexts} />
          </>
        )}
        {readOnly ? null : (
          <Field
            error={
              fileError ??
              (touched && !file ? "Bitte eine Datei auswählen." : undefined)
            }
            hint="Höchstens 25 MiB. PDF, Office-Dateien, Bilder oder ZIP."
            label="Datei"
            required
          >
            <input
              className="file-input"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                changed();
              }}
              type="file"
            />
          </Field>
        )}
      </form>
    </Modal>
  );
}

/* ---------- one material ---------- */

function MaterialRow({
  address,
  client,
  expanded,
  focusable,
  material,
  onAccess,
  onFocus,
  onToggle,
  onUpload,
  registerToggle,
  userId,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly expanded: boolean;
  readonly focusable: boolean;
  readonly material: Material;
  readonly onAccess: () => void;
  readonly onFocus: () => void;
  readonly onToggle: () => void;
  readonly onUpload: () => void;
  readonly registerToggle: (element: HTMLButtonElement | null) => void;
  readonly userId: string;
}) {
  const toast = useOptionalToast();
  const [allVersions, setAllVersions] = useState(false);
  const numbers = useMemo(() => {
    const count = allVersions
      ? material.currentVersion
      : Math.min(material.currentVersion, RECENT_VERSIONS);
    return Array.from(
      { length: count },
      (_, index) => material.currentVersion - index,
    );
  }, [allVersions, material.currentVersion]);
  const versions = useQueries({
    queries: numbers.map((number) => ({
      ...versionQuery(client, material.id, number),
      enabled: expanded,
    })),
  });
  const current = useQuery({
    ...versionQuery(client, material.id, material.currentVersion),
    enabled: expanded,
  });
  // The owner may always edit; others learn their rights when they open it.
  const rights = useQuery({
    ...permissionsQuery(client, material.id),
    enabled: expanded,
  });
  const canEdit = material.ownerUserId === userId || !!rights.data?.canEdit;
  const canManage = !!rights.data?.canManage;
  const members = useQuery({
    queryKey: ["material-members", material.id, "summary"],
    queryFn: () => client.listMaterialMembers(material.id, { limit: 20 }),
    enabled: expanded && canManage,
    retry: false,
  });
  const download = useMutation({
    mutationFn: async (number: number) => {
      const version =
        versions[numbers.indexOf(number)]?.data ??
        (await client.getMaterialVersion(material.id, number));
      await downloadMaterial(client, version);
      return version;
    },
    onError: () =>
      toast?.show({
        title: "Der Download ist fehlgeschlagen.",
        description: says(
          address,
          "Prüfe deinen Zugriff und versuche es erneut.",
          "Prüfen Sie Ihren Zugriff und versuchen Sie es erneut.",
        ),
        tone: "error",
      }),
  });
  const FileGlyph = fileIcon(current.data?.filename);
  const count = material.currentVersion;
  const active = members.data?.items.filter((member) => member.active) ?? [];
  const editors = active.filter((member) => member.access === "editor");
  const readers = active.filter((member) => member.access === "viewer");
  return (
    <li
      className={expanded ? "material is-open" : "material"}
      data-material-id={material.id}
    >
      <div className="material-head">
        <button
          aria-controls={`versions-${material.id}`}
          aria-expanded={expanded}
          className="material-toggle"
          onClick={onToggle}
          onFocus={onFocus}
          ref={registerToggle}
          tabIndex={focusable ? 0 : -1}
          type="button"
        >
          <ChevronDown
            aria-hidden="true"
            className="material-chevron"
            size={14}
          />
          <span aria-hidden="true" className="material-icon">
            <FileGlyph size={18} />
          </span>
          <span className="material-text">
            <span className="material-title">{material.title}</span>
            <span className="small subtle">
              {material.actionId ? "Aktionsmaterial" : "Eigenständig"} · {count}{" "}
              {count === 1 ? "Version" : "Versionen"}
            </span>
          </span>
        </button>
        <span className="material-meta">
          {canManage && members.data ? (
            <Badge icon={Users}>
              {active.length + 1} {active.length === 0 ? "Person" : "Personen"}
            </Badge>
          ) : null}
          <Button
            aria-label={`Aktuelle Version von ${material.title} herunterladen`}
            disabled={download.isPending}
            icon={Download}
            onClick={() => download.mutate(material.currentVersion)}
            size="sm"
            variant="secondary"
          >
            Aktuell
          </Button>
          {canEdit || !rights.isFetched ? (
            <Button
              aria-label={`Neue Version von ${material.title}`}
              icon={UploadIcon}
              onClick={onUpload}
              size="sm"
              variant="ghost"
            >
              Neue Version
            </Button>
          ) : null}
        </span>
      </div>
      {expanded ? (
        <div className="versions" id={`versions-${material.id}`}>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">
                Versionen von {material.title}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Datei</th>
                  <th className="right" scope="col">
                    Größe
                  </th>
                  <th scope="col">Version</th>
                  <th scope="col">
                    <span className="sr-only">Aktion</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {numbers.map((number, index) => {
                  const version: MaterialVersion | undefined =
                    versions[index]?.data;
                  const failed = versions[index]?.isError;
                  return (
                    <tr key={number}>
                      <td>
                        <span className="mono">
                          {version?.filename ??
                            (failed ? "nicht verfügbar" : "…")}
                        </span>{" "}
                        {number === material.currentVersion ? (
                          <Badge tone="zone">Aktuell</Badge>
                        ) : null}
                      </td>
                      <td className="num right">
                        {version ? formatSize(version.sizeBytes) : ""}
                      </td>
                      <td className="num">{number}</td>
                      <td className="right">
                        <IconButton
                          disabled={!version || download.isPending}
                          icon={Download}
                          label={`${version?.filename ?? `Version ${number}`} herunterladen`}
                          onClick={() => download.mutate(number)}
                          size="sm"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!allVersions && count > RECENT_VERSIONS ? (
            <Button
              onClick={() => setAllVersions(true)}
              size="sm"
              variant="ghost"
            >
              Ältere Versionen anzeigen ({count - RECENT_VERSIONS})
            </Button>
          ) : null}
          <p className="small subtle versions-access">
            {canManage && members.data ? (
              <>
                {editors.length
                  ? `Bearbeiten: ${editors.map((member) => member.displayName).join(", ")}`
                  : "Bearbeiten: nur die Eigentümerin oder der Eigentümer"}
                {readers.length
                  ? ` · Lesen: ${readers.map((member) => member.displayName).join(", ")}`
                  : ""}
                {material.actionId ? " · dazu die Mitglieder der Aktion" : ""}{" "}
                <Button onClick={onAccess} size="sm" variant="ghost">
                  Zugriff verwalten
                </Button>
              </>
            ) : rights.data && !canEdit ? (
              says(
                address,
                "Nur lesen. Du kannst jede Version herunterladen.",
                "Nur lesen. Sie können jede Version herunterladen.",
              )
            ) : material.actionId ? (
              "Lesen: Mitglieder der Aktion"
            ) : (
              "Lesen: Personen mit Freigabe"
            )}
          </p>
        </div>
      ) : null}
    </li>
  );
}

/* ---------- page ---------- */

export function MaterialsPage({
  basePath,
  client,
  identity,
  materialId,
  surface,
}: ModulePageContext & {
  materialId?: string;
  basePath: string;
  surface?: "web" | "pwa";
}) {
  const address: Address =
    (surface ?? (basePath.startsWith("/app") ? "pwa" : "web")) === "pwa"
      ? "du"
      : "Sie";
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const contexts = useActionContexts(client);
  const [search, setSearch] = useState("");
  const [actionId, setActionId] = useState("");
  const [open, setOpen] = useState<ReadonlySet<string>>(
    () => new Set(materialId ? [materialId] : []),
  );
  const [focus, setFocus] = useState(0);
  const [upload, setUpload] = useState<UploadTarget | null>(null);
  const [access, setAccess] = useState<Material | null>(null);
  const toggles = useRef(new Map<string, HTMLButtonElement>());

  const list = useInfiniteQuery({
    queryKey: ["materials", search, actionId],
    queryFn: ({ pageParam }) =>
      client.listMaterials({
        search,
        offset: pageParam,
        limit: PAGE,
        actionId: actionId || undefined,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.nextOffset ?? undefined,
    retry: false,
  });
  // A deep link (/materials/<id>, search hits) shows that material first,
  // also when the list page does not hold it.
  const linked = useQuery({
    queryKey: ["material", materialId],
    queryFn: () => client.getMaterial(materialId!),
    enabled: !!materialId,
    retry: false,
  });
  const items = useMemo(() => {
    const loaded = list.data?.pages.flatMap((page) => page.items) ?? [];
    if (!linked.data || loaded.some((item) => item.id === linked.data.id)) {
      return loaded;
    }
    return [linked.data, ...loaded];
  }, [list.data, linked.data]);
  const focused = items[Math.min(focus, items.length - 1)];

  // Expand the first material once, as the prototype does.
  const expandedFirst = useRef(!!materialId);
  useEffect(() => {
    if (expandedFirst.current || !items[0]) return;
    expandedFirst.current = true;
    setOpen(new Set([items[0].id]));
  }, [items]);
  // Focus the linked material once it is there.
  const focusedLinked = useRef(false);
  useEffect(() => {
    if (!materialId || focusedLinked.current) return;
    const index = items.findIndex((item) => item.id === materialId);
    if (index < 0) return;
    focusedLinked.current = true;
    setFocus(index);
    requestAnimationFrame(() => {
      const element = toggles.current.get(materialId);
      element?.focus();
      element?.scrollIntoView?.({ block: "nearest" });
    });
  }, [items, materialId]);

  useEffect(() => {
    if (!materialId && consumeCreateRequest("material"))
      setUpload({ kind: "new" });
  }, [materialId]);

  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const move = (delta: number) => {
    if (!items.length) return;
    const next = Math.max(0, Math.min(items.length - 1, focus + delta));
    setFocus(next);
    toggles.current.get(items[next]!.id)?.focus();
  };
  useHotkeys([
    {
      keys: "j",
      label: "Nächstes Material",
      group: "Material",
      run: () => move(1),
    },
    {
      keys: "k",
      label: "Vorheriges Material",
      group: "Material",
      run: () => move(-1),
    },
    {
      keys: "u",
      label: "Neue Version hochladen",
      group: "Material",
      run: () => focused && setUpload({ kind: "version", material: focused }),
    },
  ]);
  useContextCommands([
    {
      id: "create:material",
      label: "Material hochladen",
      group: "Material",
      icon: UploadIcon,
      keywords: ["neu", "Datei"],
      run: () => setUpload({ kind: "new" }),
    },
    ...items.slice(0, 50).map((item) => ({
      id: `material:version:${item.id}`,
      label: `Neue Version: ${item.title}`,
      group: "Material",
      icon: UploadIcon,
      run: () => setUpload({ kind: "version" as const, material: item }),
    })),
  ]);

  const loadedCount = items.length;
  const filtered = !!search || !!actionId;
  return (
    <div className="materials-page" data-zone="materials">
      <header className="page-header">
        <div className="page-heading">
          <h1>Material</h1>
          {list.data ? (
            <span className="page-count num">
              {loadedCount}
              {list.hasNextPage ? "+" : ""}{" "}
              {loadedCount === 1 ? "Datei" : "Dateien"}
            </span>
          ) : null}
        </div>
        <div className="page-actions">
          <Button
            icon={UploadIcon}
            onClick={() => setUpload({ kind: "new" })}
            variant="primary"
          >
            Material hochladen
          </Button>
        </div>
      </header>

      <div className="materials-tools">
        <label className="search">
          <Search aria-hidden="true" size={15} />
          <span className="sr-only">Materialien suchen</span>
          <input
            maxLength={200}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Material durchsuchen"
            type="search"
            value={search}
          />
        </label>
        {contexts.knownActions.length > 0 || actionId ? (
          <label className="select-inline">
            <span className="sr-only">Materialien nach Aktion filtern</span>
            <select
              onChange={(event) => setActionId(event.target.value)}
              value={actionId}
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
        ) : null}
      </div>

      {materialId && linked.isError ? (
        <StatusMessage tone="error">
          {says(
            address,
            "Das Material ist nicht verfügbar oder dein Zugriff wurde geändert.",
            "Das Material ist nicht verfügbar oder Ihr Zugriff wurde geändert.",
          )}
        </StatusMessage>
      ) : null}
      {list.isError ? (
        <StatusMessage tone="error">
          Materialien konnten nicht geladen werden.{" "}
          <Button
            onClick={() => void list.refetch()}
            size="sm"
            variant="secondary"
          >
            Erneut laden
          </Button>
        </StatusMessage>
      ) : list.isPending ? (
        <p className="small subtle" role="status">
          Materialien werden geladen …
        </p>
      ) : items.length === 0 ? (
        <EmptyState
          action={
            filtered ? undefined : (
              <Button
                icon={UploadIcon}
                onClick={() => setUpload({ kind: "new" })}
                variant="primary"
              >
                Material hochladen
              </Button>
            )
          }
          description={
            filtered
              ? says(
                  address,
                  "Ändere die Suche oder den Aktionsfilter.",
                  "Ändern Sie die Suche oder den Aktionsfilter.",
                )
              : "Flyer, Vorlagen und Logos landen hier – mit allen Versionen."
          }
          headingLevel={2}
          icon={Package}
          title={filtered ? "Kein passendes Material" : "Noch kein Material"}
        />
      ) : (
        <ul className="materials">
          {items.map((item, index) => (
            <MaterialRow
              address={address}
              client={client}
              expanded={open.has(item.id)}
              focusable={index === Math.min(focus, items.length - 1)}
              key={item.id}
              material={item}
              onAccess={() => setAccess(item)}
              onFocus={() => setFocus(index)}
              onToggle={() => toggle(item.id)}
              onUpload={() => setUpload({ kind: "version", material: item })}
              registerToggle={(element) => {
                if (element) toggles.current.set(item.id, element);
                else toggles.current.delete(item.id);
              }}
              userId={identity.userId}
            />
          ))}
        </ul>
      )}
      {list.hasNextPage ? (
        <Button
          className="materials-more"
          loading={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
          variant="secondary"
        >
          Weitere Materialien
        </Button>
      ) : null}
      <p aria-hidden="true" className="list-hint">
        <Kbd announce={false} keys="j" /> <Kbd announce={false} keys="k" />{" "}
        bewegen · <Kbd announce={false} keys="enter" /> auf- und zuklappen ·{" "}
        <Kbd announce={false} keys="u" /> neue Version
      </p>

      <UploadDialog
        address={address}
        client={client}
        onClose={() => setUpload(null)}
        onUploaded={(result, filename) => {
          toast?.show({
            title:
              upload?.kind === "version"
                ? `Version „${filename}“ hochgeladen.`
                : `Material „${result.title}“ hochgeladen.`,
            tone: "success",
          });
          void Promise.all([
            cache.invalidateQueries({ queryKey: ["materials"] }),
            cache.invalidateQueries({ queryKey: ["material", result.id] }),
            cache.invalidateQueries({
              queryKey: ["material-permissions", result.id],
            }),
          ]);
          setOpen((current) => new Set([...current, result.id]));
        }}
        target={upload}
      />
      <Modal
        description={access ? access.title : undefined}
        onClose={() => setAccess(null)}
        open={!!access}
        size="lg"
        title="Zugriff verwalten"
      >
        {access ? (
          <AccessMembersPanel
            actionScoped={!!access.actionId}
            objectId={access.id}
            source={materialMemberSource(client, access.id)}
          />
        ) : null}
      </Modal>
    </div>
  );
}
