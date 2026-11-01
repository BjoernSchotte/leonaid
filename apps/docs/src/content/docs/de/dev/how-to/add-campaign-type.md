---
title: Einen Aktionstyp ergänzen
description: Eine neue Aktionsvorlage als Daten veröffentlichen, ihr Erscheinungsbild wählen und eine neue Mechanik als Modul anbinden.
docId: DOC-P039
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 3ffbc7ebf669d360fb6ec7352034e4067d7eb8a4
reviewer: Björn Schotte
---

Core verzweigt nie nach einem Aktionsnamen. Das Verhalten folgt den
**Capabilities** einer Aktion (`acquisition`, `offerings`, `ordering`,
`invoicing`, `delivery`), das öffentliche Erscheinungsbild ihrem
**Presentation Theme**. Eine Vorlage sind die Daten, die beides setzen, wenn ein
Charity-Admin eine Aktion anlegt.

## Eine Warenverkaufs-Vorlage ergänzen

Ein Warenverkauf wie ein Christbaumverkauf nutzt Angebote, Bestellungen und
Rechnungen. Er braucht keine Codeänderung.

1. Ergänze eine Alembic-Datenmigration (siehe Migrationsanleitung), die für
   einen neuen Slug-Schlüssel und Version `1` je eine Zeile in die
   Vorlagentabellen schreibt:
   - `action_template_version`: `template_key`, `version`, `display_name`,
     `description` und optional `presentation_theme`.
   - `action_template_capability`: eine Zeile je Capability. Ergänze
     `delivery` nur, wenn die Ware an eine Adresse geliefert wird; sie setzt
     `ordering` voraus.
   - `action_template_offering`: Code, Name, Status, `unit` (`box`, `piece`,
     `package` oder `sponsoring`), `pieces_per_unit` für Boxen, Preis und
     Währung.
   - `action_template_order_form`: Texte und Pflichtfelder. Setze
     `require_delivery_address` nur zusammen mit der Capability `delivery`.
2. Veröffentlichte Versionen sind unveränderlich. Ändere eine Vorlage, indem
   du die nächste Version einfügst; bestehende Aktionen behalten ihren
   Snapshot.
3. Führe `./leonaid test-templates` aus. Sein Vertrag veröffentlicht auf
   demselben Weg einen Abholverkauf und legt über die API eine Aktion daraus an.

Das Backoffice zeigt die neue Vorlage unter **Aktionsvorlage** aus
`GET /api/v1/action-templates` an. Ohne `delivery` bleibt der Lieferbereich
verborgen, und das öffentliche Bestellformular fragt nur die Rechnungsadresse
ab. Dashboards, Aktivitäten und Bestellsummen melden `quantities` je
Angebotseinheit; die Box-Felder bleiben für ältere Clients erhalten und sind
als veraltet markiert.

## Ein öffentliches Erscheinungsbild ergänzen

1. Lege `apps/public/src/themes/<key>/index.ts` an, das ein `PublicTheme`
   exportiert: Body-Klasse, Seitenname, Teilen-Bild, optionaler Aktionskopf,
   Footer-Variante und optionale `Intro`-Komponente.
2. Lege die Styles in `themes/<key>/theme.css` ab, importiere sie im
   Theme-Modul und begrenze jeden Selektor auf die Body-Klasse des Themes.
3. Registriere das Theme in `apps/public/src/themes/index.ts`. Unbekannte
   Schlüssel fallen auf das neutrale LeonAid-Erscheinungsbild zurück.
4. Setze den Schlüssel als `presentation_theme` an der Vorlagenversion.
   Aktionen übernehmen ihn beim Anlegen und bei Vorjahreskopien.

Die CMS-Microsite wählt ihr Theme über das Feld `theme`. Dessen Optionen sind
Teil des versionierten CMS-Schemas in
`apps/campaign-site/src/campaign-schema.mjs`; eine neue Option für Redakteure
braucht daher eine neue CMS-Schemaversion. Die Registry in
`apps/campaign-site/src/themes/index.ts` deckt den generierten Optionstyp
vollständig ab, sodass die Typprüfung fehlschlägt, bis eine neue Option
zugeordnet ist.

## Eine neue Mechanik ergänzen

Eine andere Mechanik, etwa ein Benefizlauf oder eine Tombola, ist ein eigenes
Modul. Orientiere dich am Umfrage-Modul:

- Domänentypen und Regeln in `src/leonaid/domain/<modul>/`,
- Anwendungsdienste mit Ports in `src/leonaid/application/<modul>/`,
- PostgreSQL-Adapter in `src/leonaid/adapters/postgres/<modul>*.py` und
  Tabellen in einer eigenen Migration,
- HTTP-Routen in `src/leonaid/entrypoints/fastapi/<modul>.py`.

Wird die Mechanik je Aktion aktiviert, ergänze einen Capability-Wert in
`ActionCapability` und im API-Schema und mache das Modul von dieser Capability
abhängig. Die CHECK-Constraints der Datenbank reservieren bereits
`event_registration`, `tournament`, `booths` und `volunteer_shifts`; andere
Werte brauchen eine Migration. Vorlagen können die Mechanik dann als Daten
einschalten.
