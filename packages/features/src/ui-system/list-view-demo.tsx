import {
  CalendarClock,
  CircleDot,
  Flag,
  Globe,
  MapPin,
  ShoppingBasket,
  Truck,
  UserRound,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  Avatar,
  Badge,
  Button,
  DetailProps,
  DetailSection,
  DetailTimeline,
  HotkeyProvider,
  ListView,
  PrefixHint,
  ShortcutHelp,
  StatusIcon,
  StatusLabel,
  statusShape,
  useOptionalHotkeyRegistry,
  useToast,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";

/*
 * Catalog demo of the Linear-style list (fixture rows, nothing is stored on
 * the server). It mirrors the prototype's orders list, so the fidelity check
 * can compare both.
 */

const STATUSES = [
  "Eingegangen",
  "Prüfbereit",
  "Entwurf",
  "Bestätigt",
  "Berechnet",
  "Geliefert",
  "Storniert",
] as const;
type OrderStatus = (typeof STATUSES)[number];

const WINDOWS = [
  { id: "w1", label: "Mi 11.11. · 07–09 Uhr" },
  { id: "w2", label: "Mi 11.11. · 09–11 Uhr" },
  { id: "w3", label: "Mi 11.11. · 11–13 Uhr" },
  { id: "w4", label: "Do 12.11. · 07–09 Uhr" },
] as const;

const ACQUIRERS = [
  "Anna Akquise",
  "Bernd Becker",
  "Carla Conrad",
  "Dennis Dorn",
] as const;

const SPONSORS = [
  ["Bäckerei Kern", "Hauptstraße 4, Ingolstadt"],
  ["Autohaus Nord", "Am Ring 12, Ingolstadt"],
  ["Café Mitte", "Ludwigstraße 1, Ingolstadt"],
  ["Druckerei Süd", "Gewerbepark 7, Gaimersheim"],
  ["Steuerbüro Weiß", "Schrannenplatz 3, Ingolstadt"],
  ["Physio am Park", "Parkstraße 9, Ingolstadt"],
  ["Elektro Huber", "Industriestraße 22, Manching"],
  ["Apotheke am Tor", "Kreuztor 2, Ingolstadt"],
  ["Gärtnerei Lindner", "Feldweg 5, Kösching"],
  ["Optik Sommer", "Theresienstraße 8, Ingolstadt"],
  ["Hotel Donaublick", "Uferweg 1, Ingolstadt"],
  ["Kanzlei Berger", "Rathausplatz 6, Ingolstadt"],
] as const;

interface DemoOrder {
  readonly id: string;
  readonly number: string;
  readonly sponsor: string;
  readonly address: string;
  readonly status: OrderStatus;
  readonly windowId: string | null;
  readonly acquirer: string;
  readonly source: "Akquise" | "Öffentlich";
  readonly boxes: number;
  readonly cents: number;
  readonly createdOn: string;
  readonly priority: boolean;
}

/** Deterministic fixture rows (a fixed LCG, so screenshots stay stable). */
function fixtureOrders(): DemoOrder[] {
  let seed = 26;
  const next = () => {
    seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648;
    return seed / 2_147_483_648;
  };
  const pick = <V,>(list: readonly V[]): V =>
    list[Math.floor(next() * list.length)]!;
  const flow: OrderStatus[] = [
    "Entwurf",
    "Prüfbereit",
    "Eingegangen",
    "Bestätigt",
    "Bestätigt",
    "Berechnet",
    "Berechnet",
    "Geliefert",
    "Storniert",
  ];
  return Array.from({ length: 24 }, (_unused, index) => {
    const [sponsor, address] = SPONSORS[index % SPONSORS.length]!;
    const status = index < 3 ? "Eingegangen" : pick(flow);
    const boxes = pick([1, 2, 2, 3, 4, 5, 6, 8, 10, 12]);
    const day = 1 + Math.floor(next() * 28);
    return {
      id: `b${index + 1}`,
      number: `B-26-${String(index + 1).padStart(3, "0")}`,
      sponsor,
      address,
      status,
      windowId: status === "Entwurf" ? null : pick(WINDOWS).id,
      acquirer: pick(ACQUIRERS),
      source: next() > 0.7 ? "Öffentlich" : "Akquise",
      boxes,
      cents: boxes * 3600,
      createdOn: `2026-10-${String(day).padStart(2, "0")}`,
      priority: next() > 0.85,
    };
  });
}

const euro = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
});
const shortDate = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.`;

function DemoList() {
  const toast = useToast();
  const [orders, setOrders] = useState(fixtureOrders);
  const patch = (ids: readonly string[], change: Partial<DemoOrder>) =>
    setOrders((current) =>
      current.map((order) =>
        ids.includes(order.id) ? { ...order, ...change } : order,
      ),
    );

  const properties = useMemo<ListProperty<DemoOrder>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: STATUSES.map((status) => ({
          value: status,
          label: status,
          icon: (
            <StatusIcon label={status} status={statusShape[status] ?? "open"} />
          ),
        })),
        edit: {
          key: "s",
          apply: (ids, value) => patch(ids, { status: value as OrderStatus }),
        },
        chip: (row) => <StatusLabel status={row.status} />,
      },
      {
        id: "window",
        label: "Lieferfenster",
        icon: CalendarClock,
        get: (row) => row.windowId ?? "none",
        options: [
          ...WINDOWS.map((window) => ({
            value: window.id,
            label: window.label,
          })),
          { value: "none", label: "Noch kein Fenster" },
        ],
        edit: {
          key: "l",
          apply: (ids, value) =>
            patch(ids, { windowId: value === "none" ? null : value }),
        },
        chip: (row) => (
          <>
            <Truck aria-hidden="true" size={13} />
            <span>
              {WINDOWS.find(
                (window) => window.id === row.windowId,
              )?.label.replace(" Uhr", "") ?? "Kein Fenster"}
            </span>
          </>
        ),
      },
      {
        id: "acquirer",
        label: "Akquise",
        icon: UserRound,
        get: (row) => row.acquirer,
        options: ACQUIRERS.map((name) => ({
          value: name,
          label: name,
          icon: <Avatar name={name} size="xs" />,
        })),
        edit: {
          key: "a",
          apply: (ids, value) => patch(ids, { acquirer: value }),
        },
        chip: (row) => (
          <>
            <Avatar
              label={`Akquise: ${row.acquirer}`}
              name={row.acquirer}
              size="xs"
            />
            <span className="chip-name">{row.acquirer}</span>
          </>
        ),
      },
      {
        id: "source",
        label: "Herkunft",
        icon: Globe,
        get: (row) => row.source,
        options: [
          { value: "Akquise", label: "Akquise" },
          { value: "Öffentlich", label: "Öffentliches Formular" },
        ],
      },
      {
        id: "priority",
        label: "Priorität",
        icon: Flag,
        get: (row) => (row.priority ? "hoch" : "normal"),
        options: [
          { value: "hoch", label: "Hoch" },
          { value: "normal", label: "Normal" },
        ],
        edit: {
          key: "p",
          apply: (ids, value) => patch(ids, { priority: value === "hoch" }),
        },
        groupable: false,
      },
    ],
    [],
  );

  const sorts = useMemo<ListSort<DemoOrder>[]>(
    () => [
      {
        id: "new",
        label: "Neueste zuerst",
        compare: (a, b) =>
          b.createdOn.localeCompare(a.createdOn) ||
          b.number.localeCompare(a.number),
      },
      {
        id: "number",
        label: "Nummer",
        compare: (a, b) => a.number.localeCompare(b.number),
      },
      { id: "amount", label: "Betrag", compare: (a, b) => b.cents - a.cents },
      {
        id: "sponsor",
        label: "Sponsor A–Z",
        compare: (a, b) => a.sponsor.localeCompare(b.sponsor, "de"),
      },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      {
        id: "todo",
        label: "Zu prüfen",
        filters: [{ prop: "status", values: ["Eingegangen", "Prüfbereit"] }],
        groupBy: "status",
        sort: "new",
      },
      { id: "all", label: "Alle", filters: [], groupBy: null, sort: "new" },
      {
        id: "windows",
        label: "Nach Lieferfenster",
        filters: [{ prop: "status", values: ["Bestätigt", "Berechnet"] }],
        groupBy: "window",
        sort: "sponsor",
      },
      {
        id: "public",
        label: "Öffentlich bestellt",
        filters: [{ prop: "source", values: ["Öffentlich"] }],
        groupBy: "status",
        sort: "new",
      },
    ],
    [],
  );

  const columns = useMemo(
    () => ({
      leading: (row: DemoOrder) =>
        row.priority ? (
          <Flag
            aria-label="Hohe Priorität"
            className="flag-high"
            role="img"
            size={14}
          />
        ) : (
          <span aria-hidden="true" className="flag-space" />
        ),
      primary: (row: DemoOrder) => (
        <>
          <span className="mono order-no">{row.number}</span> {row.sponsor}
        </>
      ),
      secondary: (row: DemoOrder) =>
        `${row.boxes} ${row.boxes === 1 ? "Box" : "Boxen"} · ${
          row.source === "Öffentlich" ? "öffentlich" : row.acquirer
        } · ${shortDate(row.createdOn)}`,
      trailing: (row: DemoOrder) => (
        <span className={row.status === "Storniert" ? "is-struck" : undefined}>
          {euro.format(row.cents / 100)}
        </span>
      ),
    }),
    [],
  );

  return (
    <ListView<DemoOrder>
      bulkActions={(ids, clear) => (
        <Button
          onClick={() => {
            patch(ids, { status: "Bestätigt" });
            toast.show({
              title: `${ids.length} Bestellungen bestätigt.`,
              tone: "success",
            });
            clear();
          }}
          size="sm"
          variant="secondary"
        >
          Bestätigen
        </Button>
      )}
      columns={columns}
      createLabel="Bestellung anlegen"
      detailTitle={(row) => `${row.number} · ${row.sponsor}`}
      emptyIcon={ShoppingBasket}
      entityLabel={{ one: "Bestellung", many: "Bestellungen" }}
      getId={(row) => row.id}
      id="ui-catalog-orders"
      onCreate={() =>
        toast.show({
          title: "Neue Bestellung als Entwurf angelegt (Vorschau).",
          tone: "success",
        })
      }
      properties={properties}
      renderDetail={(row) => (
        <>
          {row.status === "Eingegangen" || row.status === "Prüfbereit" ? (
            <div className="next-step">
              <p>
                <strong>Nächster Schritt:</strong> Angaben prüfen und
                bestätigen. Danach kann die Rechnung erstellt werden.
              </p>
              <div className="ui-catalog-cluster">
                <Button
                  onClick={() => {
                    patch([row.id], { status: "Bestätigt" });
                    toast.show({
                      title: "Bestellung bestätigt.",
                      tone: "success",
                    });
                  }}
                >
                  Bestätigen
                </Button>
                <Button variant="secondary">Rückfrage stellen</Button>
              </div>
            </div>
          ) : null}
          <DetailSection title="Bestellung">
            <DetailProps
              items={[
                { label: "Angebot", value: "Krapfenbox (24 Stück)" },
                {
                  label: "Menge",
                  value: <span className="num">{row.boxes} Boxen</span>,
                },
                {
                  label: "Betrag",
                  value: (
                    <span className="num">{euro.format(row.cents / 100)}</span>
                  ),
                },
                {
                  label: "Herkunft",
                  value:
                    row.source === "Öffentlich" ? (
                      <Badge icon={Globe} tone="info">
                        Öffentliches Formular
                      </Badge>
                    ) : (
                      <Badge icon={UserRound} tone="neutral">
                        Akquise: {row.acquirer}
                      </Badge>
                    ),
                },
                { label: "Erfasst", value: shortDate(row.createdOn) },
              ]}
            />
          </DetailSection>
          <DetailSection title="Sponsor und Lieferung">
            <DetailProps
              items={[
                { label: "Sponsor", value: row.sponsor },
                {
                  label: "Lieferadresse",
                  value: (
                    <span className="ui-catalog-cluster">
                      <MapPin aria-hidden="true" size={13} />
                      {row.address}
                    </span>
                  ),
                },
              ]}
            />
          </DetailSection>
          <DetailSection title="Verlauf">
            <DetailTimeline
              items={[
                {
                  id: "created",
                  text: `Erfasst von ${row.source === "Öffentlich" ? "öffentlichem Formular" : row.acquirer}`,
                  time: shortDate(row.createdOn),
                  dateTime: row.createdOn,
                },
              ]}
            />
          </DetailSection>
        </>
      )}
      rows={orders}
      searchText={(row) =>
        `${row.number} ${row.sponsor} ${row.status} ${row.address}`
      }
      sorts={sorts}
      title="Bestellungen"
      useCommands={useContextCommands}
      views={views}
    />
  );
}

/**
 * Full-page list demo (`/admin/system/ui?listview`) in the orders zone. Uses
 * the shell's hotkey registry when there is one, its own otherwise.
 */
export function ListViewDemo() {
  const shellRegistry = useOptionalHotkeyRegistry();
  return (
    <div className="ui-list-demo" data-testid="ui-list-demo" data-zone="orders">
      {shellRegistry ? (
        <DemoList />
      ) : (
        <HotkeyProvider>
          <DemoList />
          <ShortcutHelp />
          <PrefixHint />
        </HotkeyProvider>
      )}
    </div>
  );
}
