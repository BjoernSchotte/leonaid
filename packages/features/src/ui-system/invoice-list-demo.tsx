import { Ban, CircleDot, Mail, ReceiptEuro, Wallet } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Badge,
  Button,
  DetailProps,
  DetailSection,
  ListView,
  StatusIcon,
  StatusLabel,
  statusShape,
  useToast,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";

/*
 * Catalog demo of an invoice-shaped list (fixture rows), mirroring the
 * prototype's invoices list: the status is read-only (no inline edit) and
 * changes only through explicit commands in the pane.
 */

const STATUSES = [
  "Entwurf",
  "Offen",
  "Überfällig",
  "Bezahlt",
  "Storniert",
] as const;
type InvoiceStatus = (typeof STATUSES)[number];

const SENT = [
  "Versendet",
  "Versand fehlgeschlagen",
  "Nicht versendet",
] as const;
type Sent = (typeof SENT)[number];

const RECIPIENTS = [
  "Bäckerei Kern",
  "Autohaus Nord",
  "Café Mitte",
  "Druckerei Süd",
  "Steuerbüro Weiß",
  "Physio am Park",
  "Elektro Huber",
  "Apotheke am Tor",
  "Gärtnerei Lindner",
  "Optik Sommer",
] as const;

interface DemoInvoice {
  readonly id: string;
  readonly number: string;
  readonly recipient: string;
  readonly status: InvoiceStatus;
  readonly sent: Sent;
  readonly cents: number;
  /** ISO day or null for drafts. */
  readonly dueOn: string | null;
  readonly paidOn: string | null;
  readonly cancelReason: string | null;
}

/** Deterministic fixture rows (a fixed LCG, so screenshots stay stable). */
function fixtureInvoices(): DemoInvoice[] {
  let seed = 11;
  const next = () => {
    seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648;
    return seed / 2_147_483_648;
  };
  const pick = <V,>(list: readonly V[]): V =>
    list[Math.floor(next() * list.length)]!;
  const flow: InvoiceStatus[] = [
    "Entwurf",
    "Offen",
    "Offen",
    "Offen",
    "Überfällig",
    "Bezahlt",
    "Bezahlt",
    "Storniert",
  ];
  return Array.from({ length: 20 }, (_unused, index) => {
    const status = index < 4 ? "Offen" : pick(flow);
    const day = 1 + Math.floor(next() * 28);
    const iso = `2026-11-${String(day).padStart(2, "0")}`;
    return {
      id: `r${index + 1}`,
      number:
        status === "Entwurf"
          ? "Entwurf"
          : `R-26-${String(index + 1).padStart(4, "0")}`,
      recipient: RECIPIENTS[index % RECIPIENTS.length]!,
      status,
      sent:
        status === "Entwurf"
          ? "Nicht versendet"
          : next() > 0.85
            ? "Versand fehlgeschlagen"
            : "Versendet",
      cents: pick([1, 2, 3, 4, 6, 10]) * 3600,
      dueOn: status === "Entwurf" ? null : iso,
      paidOn: status === "Bezahlt" ? iso : null,
      cancelReason: status === "Storniert" ? "Doppelt erfasst" : null,
    };
  });
}

const euro = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
});
const shortDate = (iso: string | null) =>
  iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.` : "–";

export function InvoiceDemoList() {
  const toast = useToast();
  const [invoices, setInvoices] = useState(fixtureInvoices);
  const setStatus = (id: string, status: InvoiceStatus) =>
    setInvoices((current) =>
      current.map((invoice) =>
        invoice.id === id
          ? {
              ...invoice,
              status,
              paidOn: status === "Bezahlt" ? "2026-11-03" : invoice.paidOn,
              cancelReason:
                status === "Storniert" ? "Auf Wunsch des Sponsors" : null,
            }
          : invoice,
      ),
    );

  // Status is read-only here: no `edit`, so no letter key and no chip menu.
  const properties = useMemo<ListProperty<DemoInvoice>[]>(
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
        chip: (row) => <StatusLabel status={row.status} />,
      },
      {
        id: "sent",
        label: "Versand",
        icon: Mail,
        get: (row) => row.sent,
        options: SENT.map((value) => ({ value, label: value })),
        chip: (row) =>
          row.sent === "Versand fehlgeschlagen" ? (
            <Badge icon={Mail} tone="danger">
              Versand fehlgeschlagen
            </Badge>
          ) : null,
      },
    ],
    [],
  );

  const sorts = useMemo<ListSort<DemoInvoice>[]>(
    () => [
      {
        id: "due",
        label: "Fälligkeit",
        compare: (a, b) => (a.dueOn ?? "9999").localeCompare(b.dueOn ?? "9999"),
      },
      {
        id: "number",
        label: "Nummer",
        compare: (a, b) => b.number.localeCompare(a.number),
      },
      { id: "amount", label: "Betrag", compare: (a, b) => b.cents - a.cents },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      {
        id: "open",
        label: "Offen",
        filters: [{ prop: "status", values: ["Offen", "Überfällig"] }],
        groupBy: "status",
        sort: "due",
      },
      {
        id: "overdue",
        label: "Überfällig",
        filters: [{ prop: "status", values: ["Überfällig"] }],
        groupBy: null,
        sort: "due",
      },
      {
        id: "paid",
        label: "Bezahlt",
        filters: [{ prop: "status", values: ["Bezahlt"] }],
        groupBy: null,
        sort: "number",
      },
      {
        id: "drafts",
        label: "Entwürfe",
        filters: [{ prop: "status", values: ["Entwurf"] }],
        groupBy: null,
        sort: "amount",
      },
      {
        id: "all",
        label: "Alle",
        filters: [],
        groupBy: "status",
        sort: "number",
      },
    ],
    [],
  );

  const columns = useMemo<ListColumns<DemoInvoice>>(
    () => ({
      primary: (row) => (
        <>
          <span className="mono order-no">{row.number}</span> {row.recipient}
        </>
      ),
      secondary: (row) =>
        row.status === "Bezahlt"
          ? `bezahlt ${shortDate(row.paidOn)}`
          : row.status === "Storniert"
            ? `storniert · ${row.cancelReason ?? ""}`
            : row.dueOn
              ? `fällig ${shortDate(row.dueOn)}`
              : "noch nicht ausgestellt",
      trailing: (row) => (
        <span className={row.status === "Storniert" ? "is-struck" : undefined}>
          {euro.format(row.cents / 100)}
        </span>
      ),
    }),
    [],
  );

  const openTotal = invoices
    .filter((row) => row.status === "Offen" || row.status === "Überfällig")
    .reduce((sum, row) => sum + row.cents, 0);

  return (
    <ListView<DemoInvoice>
      className="inv-list"
      columns={columns}
      detailTitle={(row) =>
        row.number === "Entwurf"
          ? `Rechnungsentwurf · ${row.recipient}`
          : `${row.number} · ${row.recipient}`
      }
      emptyIcon={ReceiptEuro}
      entityLabel={{ one: "Rechnung", many: "Rechnungen" }}
      getId={(row) => row.id}
      headerExtra={
        <span className="inv-open num">
          Offen: {euro.format(openTotal / 100)}
        </span>
      }
      id="ui-catalog-invoices"
      properties={properties}
      renderDetail={(row) => (
        <>
          {row.status === "Offen" || row.status === "Überfällig" ? (
            <div className="next-step">
              <p>
                <strong>
                  {row.status === "Überfällig"
                    ? `Seit ${shortDate(row.dueOn)} überfällig.`
                    : `Fällig ${shortDate(row.dueOn)}.`}
                </strong>{" "}
                Erfassen Sie den Zahlungseingang, sobald der volle Betrag da
                ist.
              </p>
              <div className="ui-catalog-cluster">
                <Button
                  icon={Wallet}
                  onClick={() => {
                    setStatus(row.id, "Bezahlt");
                    toast.show({
                      title: `Zahlung für ${row.number} erfasst (Vorschau).`,
                      tone: "success",
                    });
                  }}
                >
                  Zahlung erfassen
                </Button>
                <Button
                  icon={Ban}
                  onClick={() => {
                    setStatus(row.id, "Storniert");
                    toast.show({
                      title: `${row.number} storniert (Vorschau).`,
                      tone: "success",
                    });
                  }}
                  variant="ghost"
                >
                  Stornieren
                </Button>
              </div>
            </div>
          ) : null}
          <DetailSection title="Rechnung">
            <DetailProps
              items={[
                {
                  label: "Nummer",
                  value: <span className="mono">{row.number}</span>,
                },
                { label: "Status", value: <StatusLabel status={row.status} /> },
                {
                  label: "Betrag",
                  value: (
                    <span className="num">{euro.format(row.cents / 100)}</span>
                  ),
                },
                { label: "Steuer", value: "Keine USt. (§ 19 UStG)" },
                { label: "Fällig", value: shortDate(row.dueOn) },
                { label: "Versand", value: row.sent },
              ]}
            />
          </DetailSection>
          <DetailSection title="Empfänger">
            <DetailProps items={[{ label: "Name", value: row.recipient }]} />
          </DetailSection>
        </>
      )}
      rows={invoices}
      searchText={(row) => `${row.number} ${row.recipient} ${row.status}`}
      sorts={sorts}
      title="Rechnungen"
      useCommands={useContextCommands}
      views={views}
    />
  );
}
