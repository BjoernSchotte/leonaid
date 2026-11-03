import {
  Alert02Icon,
  ArrowLeft01Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
  Notification03Icon,
  PaintBoardIcon,
  TableIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  CircleAlert,
  CircleDot,
  Filter,
  PackageOpen,
  Plus,
  Search,
  Sparkles,
  Tag,
  Trash2,
  UserRound,
  Users,
} from "lucide-react";
import { useRef, useState } from "react";

import type { CurrentIdentityResponse } from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  Button,
  buttonClassName,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  Field,
  FormField,
  GO_TO_GROUP,
  HotkeyProvider,
  type HotkeyBinding,
  Icon,
  IconButton,
  Input,
  Kbd,
  Meter,
  PrefixHint,
  ShortcutHelp,
  OptionMenu,
  type OptionMenuOption,
  Popover,
  Modal,
  SkeletonRows,
  StatusIcon,
  StatusLabel,
  StatusMessage,
  statusShape,
  type StatusShape,
  useHotkeys,
  useShortcutHelp,
  Switch,
  TabPanel,
  Tabs,
  Textarea,
  useToast,
} from "@leonaid/ui";

import { ListViewDemo } from "./list-view-demo";

export interface UiSystemCatalogPageProps {
  readonly identity: CurrentIdentityResponse;
}

function PatternHeading({
  children,
  description,
  id,
}: {
  readonly children: React.ReactNode;
  readonly description: string;
  readonly id: string;
}) {
  return (
    <div className="ui-catalog-section__heading">
      <p>Basis-Pattern</p>
      <h2 id={id}>{children}</h2>
      <span>{description}</span>
    </div>
  );
}

const statusShapes: readonly (readonly [StatusShape, string])[] = [
  ["draft", "Entwurf"],
  ["open", "Offen / Eingegangen"],
  ["review", "Prüfbereit"],
  ["progress", "In Arbeit / Bestätigt"],
  ["done", "Erledigt / Bezahlt"],
  ["alert", "Überfällig / Fehler"],
  ["cancelled", "Storniert"],
];

const shortcutRows: readonly (readonly [string, string])[] = [
  ["mod+k", "Befehlspalette: Bereiche, Datensätze, Befehle"],
  ["?", "Alle Kürzel der aktuellen Seite"],
  ["g b", "Gehe zu Bestellungen (G und Buchstabe für jeden Bereich)"],
  ["j", "Nächste Zeile"],
  ["enter", "Öffnen"],
  ["escape", "Schließen, Auswahl aufheben, Feld verlassen"],
  ["shift+t", "Hell/Dunkel wechseln"],
];

/** Zones of the "g" map, keyed by server navigation key (preview only). */
const goToZones: readonly (readonly [string, string, string])[] = [
  ["d", "overview-web", "Übersicht"],
  ["a", "actions", "Aktionen"],
  ["b", "orders", "Bestellungen"],
  ["l", "delivery", "Auslieferung"],
  ["r", "invoices", "Rechnungen"],
  ["t", "tasks", "Aufgaben"],
  ["u", "surveys", "Umfragen"],
  ["e", "inbox", "Eingang"],
  ["x", "materials", "Material"],
  ["w", "knowledge", "Wissen"],
  ["f", "activities", "Aktivität"],
  ["m", "members", "Mitglieder"],
  ["k", "microsite", "Kampagnenseiten"],
  ["j", "legal", "Rechtliches"],
  ["s", "system", "System"],
  ["p", "acquisition-web", "Akquise-App"],
  ["o", "public", "Bestellseite"],
];

/**
 * Live preview of the hotkey registry: "?" opens the shortcut help, "g"
 * shows the prefix hint. The bindings only announce what they would do.
 */
function HotkeyPreview() {
  const toast = useToast();
  const help = useShortcutHelp();
  const preview = (text: string) => () =>
    toast.show({ title: `${text} (Vorschau)`, tone: "info" });
  const bindings: HotkeyBinding[] = [
    {
      keys: "mod+k",
      label: "Befehlspalette öffnen",
      group: "Allgemein",
      inDialog: true,
      allowInInput: true,
      run: preview("Befehlspalette öffnen"),
    },
    {
      keys: "shift+t",
      label: "Hell/Dunkel wechseln",
      group: "Allgemein",
      run: preview("Hell/Dunkel wechseln"),
    },
    ...goToZones.map(
      ([key, zone, label]): HotkeyBinding => ({
        keys: `g ${key}`,
        label,
        group: GO_TO_GROUP,
        zone,
        run: preview(`Gehe zu ${label}`),
      }),
    ),
  ];
  useHotkeys(bindings);
  return (
    <>
      <Button
        onClick={() => help.setOpen(true)}
        shortcut="?"
        variant="secondary"
      >
        Alle Tastenkürzel anzeigen
      </Button>
      <ShortcutHelp />
      <PrefixHint />
    </>
  );
}

const campaignStatuses = [
  "Aktiv",
  "Geplant",
  "Entwurf",
  "Abgeschlossen",
  "Archiviert",
] as const;
type CampaignStatus = (typeof campaignStatuses)[number];

const statusOptions: readonly OptionMenuOption<CampaignStatus>[] =
  campaignStatuses.map((status) => ({
    value: status,
    label: status,
    icon: <StatusIcon label={status} status={statusShape[status] ?? "open"} />,
  }));

const filterProps = [
  {
    value: "status",
    label: "Status",
    icon: <Icon icon={CircleDot} size={14} />,
    options: statusOptions as readonly OptionMenuOption<string>[],
  },
  {
    value: "kind",
    label: "Art",
    icon: <Icon icon={Tag} size={14} />,
    options: ["Krapfentaxi", "Weihnachtsmarkt", "Golfturnier"].map((kind) => ({
      value: kind,
      label: kind,
    })),
  },
  {
    value: "lead",
    label: "Leitung",
    icon: <Icon icon={UserRound} size={14} />,
    options: ["Klara Charity", "Anna Akquise", "Simone System"].map((name) => ({
      value: name,
      label: name,
      hint: "Mitglied",
    })),
  },
] as const;
type FilterProp = (typeof filterProps)[number]["value"];

/** Filter and inline-edit menus as the list views use them. */
function OptionMenuDemo() {
  const filterButton = useRef<HTMLButtonElement>(null);
  const statusButton = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const dialogStatusButton = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState<
    | { kind: "filter-prop" }
    | { kind: "filter-values"; prop: FilterProp }
    | { kind: "status" }
    | { kind: "dialog-status" }
    | null
  >(null);
  const [filters, setFilters] = useState<Record<string, readonly string[]>>({
    status: ["Aktiv", "Geplant"],
  });
  const [status, setStatus] = useState<CampaignStatus>("Aktiv");
  const [dialogStatus, setDialogStatus] = useState<CampaignStatus>("Geplant");
  const close = () => setMenu(null);
  const filterProp =
    menu?.kind === "filter-values"
      ? filterProps.find((prop) => prop.value === menu.prop)
      : undefined;
  const filterCount = Object.values(filters).flat().length;

  return (
    <div className="ui-catalog-cluster">
      <Button
        aria-expanded={menu?.kind === "filter-prop" || Boolean(filterProp)}
        aria-haspopup="dialog"
        icon={Filter}
        onClick={() => setMenu({ kind: "filter-prop" })}
        ref={filterButton}
        size="sm"
        variant="secondary"
      >
        Filter{filterCount ? ` (${filterCount})` : ""}
      </Button>
      <Button
        aria-expanded={menu?.kind === "status"}
        aria-haspopup="dialog"
        icon={<StatusIcon label="" status={statusShape[status] ?? "open"} />}
        onClick={() => setMenu({ kind: "status" })}
        ref={statusButton}
        size="sm"
        variant="secondary"
      >
        Status: {status}
      </Button>
      <Button
        onClick={() => dialogRef.current?.showModal()}
        size="sm"
        variant="ghost"
      >
        Im Dialog
      </Button>
      <dialog
        aria-labelledby="ui-catalog-menu-dialog-title"
        className="ui-catalog-menu-dialog"
        onClose={close}
        ref={dialogRef}
      >
        <h3 id="ui-catalog-menu-dialog-title">Aktion bearbeiten</h3>
        <p className="ui-catalog-small">
          Menüs aus einem modalen Dialog liegen über dem Dialog und bleiben
          bedienbar.
        </p>
        <div className="ui-catalog-cluster">
          <Button
            aria-expanded={menu?.kind === "dialog-status"}
            aria-haspopup="dialog"
            icon={
              <StatusIcon
                label=""
                status={statusShape[dialogStatus] ?? "open"}
              />
            }
            onClick={() => setMenu({ kind: "dialog-status" })}
            ref={dialogStatusButton}
            size="sm"
            variant="secondary"
          >
            Status: {dialogStatus}
          </Button>
          <Button
            onClick={() => dialogRef.current?.close()}
            size="sm"
            variant="primary"
          >
            Fertig
          </Button>
        </div>
        <Popover
          anchor={dialogStatusButton}
          label="Status im Dialog ändern"
          onClose={close}
          open={menu?.kind === "dialog-status"}
        >
          <OptionMenu
            onSelect={(value) => {
              setDialogStatus(value);
              close();
            }}
            options={statusOptions}
            placeholder="Status ändern …"
            value={dialogStatus}
          />
        </Popover>
      </dialog>
      <Popover
        anchor={filterButton}
        label="Filter wählen"
        onClose={close}
        open={menu?.kind === "filter-prop"}
      >
        <OptionMenu
          onSelect={(prop) => setMenu({ kind: "filter-values", prop })}
          options={filterProps}
          placeholder="Filtern nach …"
          value={[]}
        />
      </Popover>
      <Popover
        anchor={filterButton}
        label={filterProp ? `Filter ${filterProp.label}` : "Filter"}
        onClose={close}
        open={Boolean(filterProp)}
      >
        {filterProp ? (
          <OptionMenu
            multiple
            onSelect={(value) =>
              setFilters((current) => {
                const values = current[filterProp.value] ?? [];
                return {
                  ...current,
                  [filterProp.value]: values.includes(value)
                    ? values.filter((entry) => entry !== value)
                    : [...values, value],
                };
              })
            }
            options={filterProp.options}
            placeholder={`${filterProp.label} …`}
            value={filters[filterProp.value] ?? []}
          />
        ) : null}
      </Popover>
      <Popover
        anchor={statusButton}
        label="Status ändern"
        onClose={close}
        open={menu?.kind === "status"}
      >
        <OptionMenu
          onSelect={(value) => {
            setStatus(value);
            close();
          }}
          options={statusOptions}
          placeholder="Status ändern …"
          value={status}
        />
      </Popover>
    </div>
  );
}

const viewTabs = [
  { count: 12, id: "open", label: "Offen" },
  { id: "review", label: "Prüfbereit" },
  { count: 40, id: "all", label: "Alle" },
] as const;

type ViewTab = (typeof viewTabs)[number]["id"];

const viewTabText: Record<ViewTab, string> = {
  all: "Alle Bestellungen der Aktion, unabhängig vom Status.",
  open: "Bestellungen, die noch bestätigt werden müssen.",
  review: "Bestellungen, die auf die zweite Freigabe warten.",
};

export function UiSystemCatalogPage({ identity }: UiSystemCatalogPageProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [viewTab, setViewTab] = useState<ViewTab>("open");
  const [required, setRequired] = useState(true);
  const toast = useToast();
  const isSystemAdmin = identity.globalRoles.includes("system_admin");
  const primaryAction = identity.actionMemberships[0];
  const responsibilityRows = [
    ...identity.globalRoles.map((role) => ({
      key: `global-${role}`,
      role: role === "system_admin" ? "System-Admin" : role,
      scope: "Gesamte Installation",
    })),
    ...identity.actionMemberships.map((membership) => ({
      key: `${membership.actionId}-${membership.role}`,
      role: membership.roleLabel,
      scope: membership.actionName,
    })),
  ];

  if (!isSystemAdmin) {
    return (
      <StatusMessage tone="error">
        <h1>Nur für System-Admins</h1>
        <p>
          Der Komponenten-Katalog ist eine interne Prüfoberfläche der
          LeonAid-Installation.
        </p>
      </StatusMessage>
    );
  }

  if (new URLSearchParams(window.location.search).has("listview")) {
    return <ListViewDemo />;
  }

  return (
    <div className="ui-catalog" data-testid="ui-catalog">
      <header className="ui-catalog-hero">
        <div className="ui-catalog-hero__icon" aria-hidden="true">
          <HugeiconsIcon icon={PaintBoardIcon} size={26} strokeWidth={1.7} />
        </div>
        <div>
          <p className="ui-catalog-hero__eyebrow">System · UI-Basis</p>
          <h1>LeonAid Komponenten</h1>
          <p>
            Reale Rollen- und Aktionsdaten treffen hier auf alle Basiszustände.
            Die Seite ist Prüfoberfläche und verbindliche Referenz für neue
            Funktionen.
          </p>
          <div className="ui-catalog-hero__facts">
            <span>
              <span aria-hidden="true" />
              Backend verbunden
            </span>
            <span>{identity.displayName}</span>
            <span>{identity.roleLabels.join(" · ")}</span>
          </div>
        </div>
        <a
          className={buttonClassName({ variant: "secondary" })}
          href="/admin/system"
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={ArrowLeft01Icon}
            size={18}
            strokeWidth={1.8}
          />
          Feature-Flags
        </a>
      </header>

      <nav aria-label="Katalogabschnitte" className="ui-catalog-jumpnav">
        <a href="#actions">Aktionen</a>
        <a href="#primitives">Grundbausteine</a>
        <a href="#feedback">Feedback</a>
        <a href="#forms">Formulare</a>
        <a href="#data">Daten</a>
        <a href="#lists">Listen</a>
      </nav>

      <section aria-labelledby="actions" className="ui-catalog-section">
        <PatternHeading
          description="Eine dominante Aktion, ergänzende Alternative und klar erkennbare Gefahr."
          id="actions"
        >
          Aktionen und Fokus
        </PatternHeading>
        <div className="ui-catalog-row">
          <Button>Primäre Aktion</Button>
          <Button variant="secondary">Sekundär</Button>
          <Button variant="ghost">Zurückhaltend</Button>
          <Button variant="danger">Kritische Aktion</Button>
          <Button disabled>Wird gespeichert …</Button>
        </div>
        <p className="ui-catalog-note">
          Tastaturfokus nutzt auf allen Bedienelementen denselben sichtbaren
          Fokus-Ring. Gefährliche Aktionen erhalten zusätzlich eine Bestätigung.
        </p>
      </section>

      <section aria-labelledby="primitives" className="ui-catalog-section">
        <PatternHeading
          description="Leitsystem-Bausteine: Status als Form, Kennzeichen, Eingabe, Fortschritt, Rückmeldung, Personen und Tastenkürzel."
          id="primitives"
        >
          Grundbausteine
        </PatternHeading>
        <div className="ui-catalog-components">
          <div className="ui-catalog-component">
            <h3>Knöpfe</h3>
            <div className="ui-catalog-cluster">
              <Button icon={Plus} variant="primary">
                Bestellung anlegen
              </Button>
              <Button variant="secondary">Rückfrage stellen</Button>
              <Button variant="ghost">Abbrechen</Button>
              <Button icon={Trash2} variant="danger">
                Stornieren
              </Button>
              <Button loading variant="secondary">
                Wird gesendet
              </Button>
            </div>
            <div className="ui-catalog-cluster">
              <Button size="sm" variant="secondary">
                Klein
              </Button>
              <Button icon={Search} shortcut="mod+k" variant="secondary">
                Suchen
              </Button>
              <Button shortcut="c" variant="primary">
                Neu
              </Button>
              <Button size="lg" variant="zone">
                Bereich
              </Button>
              <IconButton icon={Users} label="Mitglieder anzeigen" />
            </div>
          </div>
          <div className="ui-catalog-component">
            <h3>Status als Form</h3>
            <ul className="ui-catalog-shapes">
              {statusShapes.map(([shape, label]) => (
                <li key={shape}>
                  <StatusIcon label={label} size={16} status={shape} />
                  <span aria-hidden="true">{label}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="ui-catalog-component">
            <h3>Kennzeichen</h3>
            <div className="ui-catalog-cluster">
              <Badge tone="ok">Bezahlt</Badge>
              <Badge tone="warn">Prüfen</Badge>
              <Badge tone="danger">Überfällig</Badge>
              <Badge tone="info">Öffentlich</Badge>
              <Badge tone="accent">Neu</Badge>
              <Badge icon={CircleAlert} tone="danger">
                Versand fehlgeschlagen
              </Badge>
            </div>
            <div className="ui-catalog-cluster">
              <StatusLabel status="Bezahlt" />
              <StatusLabel status="Überfällig" />
              <StatusLabel status="Storniert" />
            </div>
          </div>
          <div className="ui-catalog-component">
            <h3>Eingabe</h3>
            <Field
              hint="Wir senden Ihnen einen Anmeldecode."
              id="demo-email"
              label="E-Mail-Adresse"
            >
              <input placeholder="name@beispiel.de" type="email" />
            </Field>
            <Field
              error="Bitte den vollständigen Rechnungsbetrag erfassen: 144,00 €."
              id="demo-amount"
              label="Betrag"
            >
              <input defaultValue="140,00" inputMode="decimal" />
            </Field>
          </div>
          <div className="ui-catalog-component">
            <h3>Fortschritt</h3>
            <div className="ui-catalog-stack" data-zone="actions">
              <span className="ui-catalog-small">
                <strong className="ui-catalog-num">7.128 €</strong> von 10.000 €
                für Kinderhafen und Jugendhilfe
              </span>
              <Meter
                label="Spendenziel Krapfentaxi 2026"
                max={10000}
                value={7128}
              />
            </div>
          </div>
          <div className="ui-catalog-component">
            <h3>Auswahlmenüs</h3>
            <OptionMenuDemo />
            <p className="ui-catalog-small">
              Tippen filtert, Pfeile wählen, Enter übernimmt, 1–9 springt
              direkt, Esc schließt.
            </p>
          </div>
          <div className="ui-catalog-component">
            <h3>Rückmeldung</h3>
            <div className="ui-catalog-cluster">
              <Button
                icon={Sparkles}
                onClick={() =>
                  toast.show({
                    action: {
                      label: "Rückgängig",
                      run: () => toast.show({ title: "Rückgängig gemacht." }),
                    },
                    title: "Bestellung bestätigt.",
                    tone: "success",
                  })
                }
                variant="secondary"
              >
                Meldung zeigen
              </Button>
              <Button onClick={() => setModalOpen(true)} variant="secondary">
                Dialog öffnen
              </Button>
            </div>
          </div>
          <div className="ui-catalog-component">
            <h3>Personen</h3>
            <div className="ui-catalog-cluster">
              <Avatar
                label={identity.displayName}
                name={identity.displayName}
              />
              <Avatar name={identity.displayName} size="md" />
              <Avatar name="Anna Akquise" size="xs" />
              <span className="ui-catalog-small">{identity.displayName}</span>
            </div>
          </div>
        </div>
        <div className="ui-catalog-keys-block">
          <h3>Tastatur</h3>
          <p className="ui-catalog-note">
            Kürzel wirken nicht, während Sie in ein Feld schreiben. Auf
            Touch-Geräten werden die Hinweise ausgeblendet.
          </p>
          <table className="ui-catalog-keys">
            <caption>Tastenkürzel</caption>
            <tbody>
              {shortcutRows.map(([keys, label]) => (
                <tr key={keys}>
                  <td>
                    <Kbd keys={keys} />
                  </td>
                  <td>{label}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="ui-catalog-cluster" id="hotkeys">
            <HotkeyProvider>
              <HotkeyPreview />
            </HotkeyProvider>
          </div>
        </div>
        <p className="ui-catalog-note">
          <Icon icon={CircleAlert} size={14} /> Icons stammen aus Lucide
          (14/16/20 px). Sie stehen nie allein: Jeder Icon-Knopf hat eine
          Beschriftung für Screenreader und einen Tooltip.
        </p>
      </section>

      <section aria-labelledby="feedback" className="ui-catalog-section">
        <PatternHeading
          description="Status wird immer mit Symbol und Text vermittelt, nie nur über Farbe."
          id="feedback"
        >
          Feedback und Bestätigung
        </PatternHeading>
        <div className="ui-catalog-feedback-grid">
          <StatusMessage tone="info">
            <strong>Hinweis</strong>
            <p>Die Änderungen gelten nach dem Speichern für diese Aktion.</p>
          </StatusMessage>
          <StatusMessage tone="success">
            <strong>Gespeichert</strong>
            <p>Die Zuordnung wurde erfolgreich aktualisiert.</p>
          </StatusMessage>
          <StatusMessage tone="error">
            <strong>Nicht gespeichert</strong>
            <p>Prüfen Sie das markierte Feld und versuchen Sie es erneut.</p>
          </StatusMessage>
        </div>
        <ErrorState
          onRetry={() =>
            toast.show({ title: "Bestellungen werden neu geladen." })
          }
          title="Bestellungen konnten nicht geladen werden"
        >
          Die Verbindung zum Server ist unterbrochen. Ihre Filter bleiben
          erhalten.
        </ErrorState>
        <div className="ui-catalog-row">
          <Button
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={Notification03Icon}
                size={18}
                strokeWidth={1.8}
              />
            }
            onClick={() =>
              toast.show({
                description:
                  "Der kurze Hinweis bleibt in dieser Prüfoberfläche bis zum Schließen sichtbar.",
                timeout: 0,
                title: "Änderung gespeichert",
                tone: "success",
              })
            }
            variant="secondary"
          >
            Toast anzeigen
          </Button>
          <Button onClick={() => setDialogOpen(true)} variant="danger">
            Bestätigung öffnen
          </Button>
        </div>
      </section>

      <section aria-labelledby="forms" className="ui-catalog-section">
        <PatternHeading
          description="Label, kurze Hilfestellung und konkrete Korrektur bleiben am Feld."
          id="forms"
        >
          Formulare und Fehler
        </PatternHeading>
        <div className="ui-catalog-form-grid">
          <FormField
            description="Der Name wird für Mitglieder und auf der öffentlichen Seite verwendet."
            label="Name der Aktion"
            required
          >
            <input
              defaultValue={primaryAction?.actionName ?? "Krapfentaxi 2026"}
              name="catalog-action-name"
            />
          </FormField>
          <FormField
            description="Kurze, eindeutige Adresse ohne Jahreszahl."
            error="Geben Sie einen Alias wie „krapfentaxi“ ein."
            label="Öffentlicher Alias"
            required
          >
            <input name="catalog-alias" placeholder="z. B. krapfentaxi" />
          </FormField>
          <FormField
            description="Wird aus der gewählten Vorlage übernommen."
            label="Vorlage"
          >
            <select defaultValue="krapfentaxi" name="catalog-template">
              <option value="krapfentaxi">Krapfentaxi</option>
              <option value="blank">Leere Aktion</option>
            </select>
          </FormField>
          <FormField
            description="Nach der Veröffentlichung nicht mehr frei änderbar."
            label="Archiv-Slug"
          >
            <input
              defaultValue="krapfentaxi-2026"
              disabled
              name="catalog-archive-slug"
            />
          </FormField>
          <Field
            hint="Erscheint nur intern bei der Bestellung."
            label="Notiz"
            optional
          >
            <Textarea name="catalog-note" />
          </Field>
          <div className="ui-catalog-stack">
            <Switch
              checked={required}
              label="Pflichtfrage"
              onChange={(event) => setRequired(event.target.checked)}
            />
            <Switch
              defaultChecked
              disabled
              label="Gesperrt (Umfrage ist live)"
            />
          </div>
        </div>
      </section>

      <section aria-labelledby="data" className="ui-catalog-section">
        <PatternHeading
          description="Echte Golden-Data-Zuordnungen aus der laufenden API; auf kleinen Breiten horizontal fokussierbar."
          id="data"
        >
          Tabelle und Leerzustand
        </PatternHeading>
        <Tabs
          idPrefix="catalog-view"
          items={viewTabs}
          label="Ansichten"
          onChange={setViewTab}
          value={viewTab}
        />
        <TabPanel
          className="ui-catalog-note"
          idPrefix="catalog-view"
          tabId={viewTab}
        >
          {viewTabText[viewTab]}
        </TabPanel>
        {responsibilityRows.length > 0 ? (
          <DataTable caption="Rollen und Zuständigkeiten der angemeldeten Person">
            <thead>
              <tr>
                <th scope="col">Rolle</th>
                <th scope="col">Zuständigkeit</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {responsibilityRows.map((row) => (
                <tr key={row.key}>
                  <td>{row.role}</td>
                  <td>{row.scope}</td>
                  <td>
                    <span className="ui-catalog-status">
                      <HugeiconsIcon
                        aria-hidden="true"
                        icon={CheckmarkCircle02Icon}
                        size={16}
                        strokeWidth={1.8}
                      />
                      Zugeordnet
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        ) : (
          <StatusMessage tone="info">
            Für diese Person liefert das Backend noch keine Aktionszuordnungen.
          </StatusMessage>
        )}
        <div
          aria-busy="true"
          aria-label="Bestellungen werden geladen"
          role="region"
        >
          <SkeletonRows rows={3} />
        </div>
        <EmptyState
          action={<Button variant="secondary">Filter zurücksetzen</Button>}
          description="Passen Sie die Filter an oder erfassen Sie einen neuen Eintrag."
          icon={PackageOpen}
          title="Keine passenden Bestellungen"
        />
      </section>

      <section aria-labelledby="lists" className="ui-catalog-section">
        <PatternHeading
          description="Gespeicherte Ansichten, Filter-Chips, Gruppen, Tastatur (J/K, Enter, Esc, X, F, /) und Detailbereich mit Beispieldaten."
          id="lists"
        >
          Listenansicht
        </PatternHeading>
        <p className="ui-catalog-note">
          Die Listenansicht braucht die volle Seitenbreite. Filter und Ansicht
          stehen in der Adresse und bleiben nach dem Neuladen erhalten.
        </p>
        <div className="ui-catalog-row">
          <a
            className={buttonClassName({ variant: "secondary" })}
            href="/admin/system/ui?listview"
          >
            Listenansicht öffnen
          </a>
        </div>
      </section>

      <section
        aria-labelledby="semantics"
        className="ui-catalog-section ui-catalog-section--compact"
      >
        <PatternHeading
          description="Komponenten verwenden ausschließlich semantische Tokens und freie Icon-Pakete."
          id="semantics"
        >
          Technische Leitplanken
        </PatternHeading>
        <ul className="ui-catalog-guardrails">
          <li>
            <HugeiconsIcon
              aria-hidden="true"
              icon={PaintBoardIcon}
              size={18}
              strokeWidth={1.8}
            />
            Light, Dark und System nutzen denselben semantischen Vertrag.
          </li>
          <li>
            <HugeiconsIcon
              aria-hidden="true"
              icon={TableIcon}
              size={18}
              strokeWidth={1.8}
            />
            Tabellen bleiben nativ, beschriftet und per Tastatur scrollbar.
          </li>
          <li>
            <HugeiconsIcon
              aria-hidden="true"
              icon={InformationCircleIcon}
              size={18}
              strokeWidth={1.8}
            />
            UI-Zustände enthalten verständliche Ursache und nächsten Schritt.
          </li>
          <li>
            <HugeiconsIcon
              aria-hidden="true"
              icon={Alert02Icon}
              size={18}
              strokeWidth={1.8}
            />
            Kritische Änderungen werden bestätigt und nie nur farblich markiert.
          </li>
        </ul>
      </section>

      <Modal
        description="Die Rechnung bleibt sichtbar und erhält den Stempel „Storniert“. Eine Stornorechnung wird erzeugt."
        footer={
          <>
            <Button onClick={() => setModalOpen(false)} variant="ghost">
              Abbrechen
            </Button>
            <Button
              onClick={() => {
                setModalOpen(false);
                toast.show({ title: "KT26-0004 storniert.", tone: "success" });
              }}
              variant="danger"
            >
              Stornieren
            </Button>
          </>
        }
        onClose={() => setModalOpen(false)}
        open={modalOpen}
        title="Rechnung stornieren?"
      >
        <Field id="demo-reason" label="Grund">
          <Input defaultValue="Doppelt erfasst" />
        </Field>
      </Modal>

      <ConfirmDialog
        confirmLabel="Aktion bestätigen"
        description="Diese Vorschau zeigt das verbindliche Pattern für kritische Änderungen. Im Fachfluss nennt der Text immer die konkrete Auswirkung."
        onConfirm={() => {
          setDialogOpen(false);
          toast.show({
            description: "Die Beispielaktion wurde bestätigt.",
            title: "Bestätigung abgeschlossen",
            tone: "success",
          });
        }}
        onOpenChange={setDialogOpen}
        open={dialogOpen}
        title="Kritische Aktion bestätigen?"
        tone="danger"
      />
    </div>
  );
}
