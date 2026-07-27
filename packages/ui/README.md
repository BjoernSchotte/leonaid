# `@leonaid/ui`

Gemeinsame, host-neutrale Open-Code-Komponenten für Web und PWA. Die
shadcn/ui-Konfiguration ist auf Base UI und ausschließlich freie
Hugeicons-Pakete festgelegt.

`src/styles/tokens.css` trennt zwei Ebenen:

- unveränderte Lions-International-Markenprimitiven aus den offiziellen
  [Brand Guidelines](https://www.lionsclubs.org/en/resources-for-members/brand-guidelines),
  darunter Blue `#00338D`, Yellow `#EBB700`, Purple `#7A2582` und Navy
  `#0D2240`;
- semantische LeonAid-Tokens wie `--background`, `--surface`, `--primary`,
  `--focus`, `--success` und `--sidebar`.

Komponenten verwenden ausschließlich die semantische Ebene. Light und Dark
Mode können dadurch weiterentwickelt werden, ohne Fachkomponenten oder
Markenprimitiven umzuschreiben. Der Umschalter unterstützt `system`, `light`
und `dark`, speichert nur diese Präferenz lokal und folgt im Systemmodus
laufenden Änderungen des Betriebssystems.

## Verbindliche Patterns

Neue Oberflächen nutzen die exportierten Komponenten aus `@leonaid/ui` und
keine lokal nachgebauten Varianten:

| Situation                    | Komponente/Pattern           | Vertrag                                                                                                         |
| ---------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Haupt- und Nebenaktionen     | `Button`                     | pro Seite höchstens eine dominante primäre Aktion; Gefahr immer als Text und Farbe                              |
| Feld mit Erklärung           | `FormField`                  | sichtbares Label, knappe Beschreibung, Fehler direkt am Feld und via `aria-describedby`                         |
| nicht-blockierendes Ergebnis | `ToastProvider` / `useToast` | Erfolg, Hinweis oder Fehler; Fehler werden dringlich angekündigt, Toast ersetzt keine persistente Fehlermeldung |
| blockierende Bestätigung     | `ConfirmDialog`              | konkrete Auswirkung im Text, Fokusfalle und Rückgabe des Fokus durch Base UI                                    |
| fachlicher Status            | `StatusMessage`              | Symbol und Text zusätzlich zur Farbe                                                                            |
| keine Ergebnisse             | `EmptyState`                 | erklärt Zustand und einen sinnvollen nächsten Schritt                                                           |
| tabellarische Daten          | `DataTable`                  | native Tabelle mit Caption; fokussierbarer horizontaler Scrollbereich auf kleinen Displays                      |
| angemeldete Anwendung        | `AppShell`                   | Rolle und aktueller Arbeitskontext sichtbar; Desktop-Sidebar, mobiler Drawer beziehungsweise PWA-Tabbar         |

Alle interaktiven Ziele sind mindestens `44px` hoch. Der globale
`:focus-visible`-Ring bleibt erhalten. Seiten beginnen mit einer eindeutigen
`h1`; Dialoge besitzen Titel und Beschreibung. Status darf nie ausschließlich
über Farbe oder Position vermittelt werden.

## Komponenten-Katalog

System-Admins erreichen unter `/admin/system/ui` den produktionsnahen Katalog.
Er läuft innerhalb der echten App Shell, zeigt reale Identitäts- und
Zuordnungsdaten der laufenden API und enthält die Zustände für Aktionen,
Feedback, Formularfelder, Tabelle und Leerzustand. Damit ist er zugleich die
stabile Oberfläche für Accessibility- und visuelle Regressionstests.

## Abhängigkeiten und Lizenzgrenze

Die konkreten Versionen bleiben in `package.json` und `bun.lock` gepinnt.
Lizenz- und Herkunftshinweise stehen in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). In Produktcode dürfen nur
Icons aus `@hugeicons/core-free-icons` verwendet werden. Hugeicons Pro,
kopierte Web-SVGs oder andere Asset-Pakete benötigen vor der Aufnahme eine
eigene Lizenzentscheidung.
