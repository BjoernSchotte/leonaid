import {
  Alert02Icon,
  ArrowLeft01Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
  Notification03Icon,
  PackageOpenIcon,
  PaintBoardIcon,
  TableIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useState } from "react";

import type { CurrentIdentityResponse } from "@leonaid/api-client";
import {
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  FormField,
  StatusMessage,
  useToast,
} from "@leonaid/ui";

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

export function UiSystemCatalogPage({ identity }: UiSystemCatalogPageProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
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
        <a className="ui-button ui-button--secondary" href="/admin/system">
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
        <a href="#feedback">Feedback</a>
        <a href="#forms">Formulare</a>
        <a href="#data">Daten</a>
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
            <p>Prüfe das markierte Feld und versuche es erneut.</p>
          </StatusMessage>
        </div>
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
            error="Gib einen Alias wie „krapfentaxi“ ein."
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
        </div>
      </section>

      <section aria-labelledby="data" className="ui-catalog-section">
        <PatternHeading
          description="Echte Golden-Data-Zuordnungen aus der laufenden API; auf kleinen Breiten horizontal fokussierbar."
          id="data"
        >
          Tabelle und Leerzustand
        </PatternHeading>
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
        <EmptyState
          action={<Button variant="secondary">Filter zurücksetzen</Button>}
          description="Passe die Filter an oder erfasse einen neuen Eintrag."
          icon={
            <HugeiconsIcon icon={PackageOpenIcon} size={24} strokeWidth={1.7} />
          }
          title="Keine passenden Bestellungen"
        />
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
