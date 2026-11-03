import {
  Activity,
  BookOpen,
  ClipboardList,
  Flag,
  Globe,
  Handshake,
  Inbox,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Megaphone,
  Package,
  ReceiptEuro,
  Scale,
  ServerCog,
  ShoppingBasket,
  Smartphone,
  Truck,
  Users,
} from "lucide-react";

export type NavigationZoneGroup =
  | "Arbeit"
  | "Module"
  | "Verwaltung"
  | "Weitere Oberflächen";

/**
 * One area of the Leitsystem. `navKey` is the server navigation key
 * (`NavigationItem.key`; module items use the module id). The hue comes
 * from CSS via `[data-zone="<navKey>"]`, so it is not part of this map.
 */
export interface NavigationZone {
  readonly navKey: string;
  /** Second key after "g". */
  readonly key: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly group: NavigationZoneGroup;
  /** Short description for the palette and the shortcut help. */
  readonly hint: string;
}

/**
 * The approved "g" map. It only describes zones; whether an entry is shown
 * is decided by the navigation the server returns for the account.
 */
export const navigationZones: readonly NavigationZone[] = [
  {
    navKey: "overview-web",
    key: "d",
    label: "Übersicht",
    icon: LayoutDashboard,
    group: "Arbeit",
    hint: "Kennzahlen und nächste Schritte",
  },
  {
    navKey: "actions",
    key: "a",
    label: "Aktionen",
    icon: Flag,
    group: "Arbeit",
    hint: "Charity-Aktionen, Lieferfenster, Aliase, Vorlagen",
  },
  {
    navKey: "orders",
    key: "b",
    label: "Bestellungen",
    icon: ShoppingBasket,
    group: "Arbeit",
    hint: "Zusagen und Bestellungen",
  },
  {
    navKey: "acquisition-web",
    key: "q",
    label: "Akquise",
    icon: Handshake,
    group: "Arbeit",
    hint: "Sponsoren-Pipeline und Zuordnungen",
  },
  {
    navKey: "delivery",
    key: "l",
    label: "Auslieferung",
    icon: Truck,
    group: "Arbeit",
    hint: "Lieferfenster abarbeiten und abschließen",
  },
  {
    navKey: "invoices",
    key: "r",
    label: "Rechnungen",
    icon: ReceiptEuro,
    group: "Arbeit",
    hint: "Rechnungen, Zahlungen, Stornos, Dokumente",
  },
  {
    navKey: "tasks",
    key: "t",
    label: "Aufgaben",
    icon: ListChecks,
    group: "Module",
    hint: "Listen und persönlicher Plan",
  },
  {
    navKey: "surveys",
    key: "u",
    label: "Umfragen",
    icon: ClipboardList,
    group: "Module",
    hint: "Fragebögen, Antworten, Exporte",
  },
  {
    navKey: "inbox",
    key: "e",
    label: "Eingang",
    icon: Inbox,
    group: "Module",
    hint: "Anfragen aus dem Kontaktformular",
  },
  {
    navKey: "materials",
    key: "x",
    label: "Material",
    icon: Package,
    group: "Module",
    hint: "Dateien mit Versionen",
  },
  {
    navKey: "knowledge",
    key: "w",
    label: "Wissen",
    icon: BookOpen,
    group: "Module",
    hint: "Anleitungen und Notizen",
  },
  {
    navKey: "activities",
    key: "f",
    label: "Aktivität",
    icon: Activity,
    group: "Module",
    hint: "Was zuletzt passiert ist",
  },
  {
    navKey: "members",
    key: "m",
    label: "Mitglieder",
    icon: Users,
    group: "Verwaltung",
    hint: "Personen, Rollen, Einladungen, Sitzungen",
  },
  {
    navKey: "microsite",
    key: "k",
    label: "Kampagnenseiten",
    icon: Megaphone,
    group: "Verwaltung",
    hint: "Öffentliche Seiten der Aktionen bearbeiten",
  },
  {
    navKey: "legal",
    key: "j",
    label: "Rechtliches",
    icon: Scale,
    group: "Verwaltung",
    hint: "Impressum, Datenschutz, Rechnungsprofil mit Vier-Augen-Prinzip",
  },
  {
    navKey: "system",
    key: "s",
    label: "System",
    icon: ServerCog,
    group: "Verwaltung",
    hint: "Betrieb, Aufgaben, Funktionen, Sicherungen",
  },
  {
    navKey: "acquisition-app",
    key: "p",
    label: "Akquise-App",
    icon: Smartphone,
    group: "Weitere Oberflächen",
    hint: "Mobile App für Anna und das Akquiseteam",
  },
  {
    navKey: "public",
    key: "o",
    label: "Bestellseite",
    icon: Globe,
    group: "Weitere Oberflächen",
    hint: "Öffentliche Bestellseite ohne Anmeldung",
  },
];

const zonesByNavKey: ReadonlyMap<string, NavigationZone> = new Map(
  navigationZones.map((zone) => [zone.navKey, zone]),
);

/**
 * The cross-surface link from the admin rail into the acquisition PWA. It is
 * not a server navigation item: the admin shows it when the account has any
 * PWA item, and it never relabels the PWA's own overview.
 */
export const ACQUISITION_APP_KEY = "acquisition-app";
export const ACQUISITION_APP_HREF = "/app/";

export function zoneForNavKey(navKey: string): NavigationZone | undefined {
  return zonesByNavKey.get(navKey);
}
