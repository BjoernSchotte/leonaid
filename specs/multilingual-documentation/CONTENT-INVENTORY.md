# LeonAid documentation content inventory

Stand: 14.09.2026<br>
Produktbasis: `2043b72b7c5453b37978f2a58436243dbc378a00`<br>
Publikationskanal: ausdrücklich gekennzeichneter Entwicklungs-/Pilotstand des
Default-Branches<br>
Repository-Modell: `apps/docs` im LeonAid-Monorepo<br>
Locales: explizite Präfixe `/de/` und `/en/`, Deutsch als redaktionelle
Ausgangssprache

## Verantwortung

Bis ein gesondertes Docs-Team benannt wird, trägt Repository-Inhaber
**Björn Schotte (`BjoernSchotte`)** die Freigabeverantwortung und die
Site-Maintainer-Rolle. Für jede Seite sind zwei Prüfungen sichtbar:

- **Fachreview:** Produktverhalten, Berechtigungen, Betriebs- oder
  Entwicklungsvertrag stimmen mit dem referenzierten LeonAid-Stand überein.
- **Sprachreview:** Deutsch und Englisch sind verständlich, inhaltlich
  gleichwertig und folgen dem Glossar.

Dieselbe Person darf im ersten Umfang beide Reviews durchführen. Eine Seite
gilt trotzdem erst als freigegeben, wenn beide Zustände im Inventar auf
`freigegeben` stehen.

## Verbindlicher erster Seitenumfang

Jede Tabellenzeile bezeichnet ein DE/EN-Paar. Relative Pfade unterhalb von
`apps/docs/src/content/docs/{de,en}/` und die Routen sind absichtlich
sprachsymmetrisch. Der implementierte Code ist immer die Wahrheitsquelle.
`Quelle` benennt die zuerst zu prüfenden Code-, Test- und ergänzenden
Kontextpfade. Specs, READMEs und ältere Proofs helfen bei der Suche und
Einordnung, können aktuelles Verhalten aber nicht beweisen oder überstimmen.

| ID       | CONTENT | Bereich      | Diátaxis  | Relativer Pfad / Route                                                                                              | Quelle                                                                  | DE/EN-Status            | Review                                                                     | Abnahme           |
| -------- | ------- | ------------ | --------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ----------------------- | -------------------------------------------------------------------------- | ----------------- |
| DOC-P001 | 01      | Orientierung | Erklärung | `index.mdx` · `/{locale}/`                                                                                          | `README.md`, `PERSONAS.md`, dieses Inventar                             | freigegeben/freigegeben | Björn Schotte: alle Einstiege, Sprachpaar und Build geprüft                | DOC-040 + DOC-050 |
| DOC-P002 | 01      | Orientierung | Referenz  | `glossary.md` · `/{locale}/glossary/`                                                                               | `PERSONAS.md`, Domain- und UI-Begriffe                                  | freigegeben/freigegeben | Björn Schotte: Anwender- und Technikbegriffe in beiden Sprachen geprüft    | DOC-040 + DOC-050 |
| DOC-P003 | 01      | Orientierung | Referenz  | `known-limits.md` · `/{locale}/known-limits/`                                                                       | `specs/leonaid-poc/KNOWN-LIMITS.md`, aktuelle Specs und Implementierung | freigegeben/freigegeben | Björn Schotte: Anwender- und Betriebsgrenzen gegen Code geprüft            | DOC-040 + DOC-050 |
| DOC-P010 | 01      | Anwendung    | Erklärung | `user/index.mdx` · `/{locale}/user/`                                                                                | `PERSONAS.md`, `packages/features`, `apps/public`                       | freigegeben/freigegeben | Björn Schotte: Codepfade, Sprachpaar und Build geprüft                     | DOC-040           |
| DOC-P011 | 02      | Anwendung    | Tutorial  | `user/tutorials/first-customer-order.md` · `/{locale}/user/tutorials/first-customer-order/`                         | `packages/features/src/commitments`, `tests/e2e`, Golden Dataset        | freigegeben/freigegeben | Björn Schotte: Codepfade, Sprachpaar und Journey geprüft                   | DOC-040           |
| DOC-P012 | 03      | Anwendung    | How-to    | `user/how-to/manage-delivery-windows.md` · `/{locale}/user/how-to/manage-delivery-windows/`                         | `packages/features/src/action-admin`, Lieferplan/-proofs                | freigegeben/freigegeben | Björn Schotte: UI-Tokens, Core-Vertrag und Sprachpaar geprüft              | DOC-040           |
| DOC-P013 | 03      | Anwendung    | How-to    | `user/how-to/place-public-order.md` · `/{locale}/user/how-to/place-public-order/`                                   | `apps/public`, `apps/campaign-site`, Public-Order-Tests                 | freigegeben/freigegeben | Björn Schotte: UI-Tokens, Browser-Journey und Sprachpaar geprüft           | DOC-040           |
| DOC-P014 | 03      | Anwendung    | How-to    | `user/how-to/record-invoice-payment.md` · `/{locale}/user/how-to/record-invoice-payment/`                           | `packages/features/src/action-admin`, Invoice-Tests, `PERSONAS.md`      | freigegeben/freigegeben | Björn Schotte: UI-/Rollenvertrag, isolierte Journey und Sprachpaar geprüft | DOC-040           |
| DOC-P015 | 03      | Anwendung    | How-to    | `user/how-to/regain-access.md` · `/{locale}/user/how-to/regain-access/`                                             | Auth-Komponenten, Session-/Invitation-Tests, Runbook                    | freigegeben/freigegeben | Björn Schotte: UI-Tokens, Session-Journey und Sprachpaar geprüft           | DOC-040           |
| DOC-P016 | 04      | Anwendung    | Referenz  | `user/reference/roles.md` · `/{locale}/user/reference/roles/`                                                       | `PERSONAS.md`, Identity-Domain und API                                  | freigegeben/freigegeben | Björn Schotte: Rollenvertrag und Sprachpaar geprüft                        | DOC-040           |
| DOC-P017 | 04      | Anwendung    | Referenz  | `user/reference/statuses-and-fields.md` · `/{locale}/user/reference/statuses-and-fields/`                           | Domain-Enums, API-Vertrag und UI-Labels                                 | freigegeben/freigegeben | Björn Schotte: generierte Typen und Sprachpaar geprüft                     | DOC-040           |
| DOC-P018 | 04      | Anwendung    | Erklärung | `user/explanation/actions-contacts-orders.md` · `/{locale}/user/explanation/actions-contacts-orders/`               | Produktarchitektur, Core/CRM-Adapter                                    | freigegeben/freigegeben | Björn Schotte: Domain-/Adaptercode und Sprachpaar geprüft                  | DOC-040           |
| DOC-P019 | 04      | Anwendung    | Erklärung | `user/explanation/action-permissions.md` · `/{locale}/user/explanation/action-permissions/`                         | `PERSONAS.md`, Policy- und Identity-Nachweise                           | freigegeben/freigegeben | Björn Schotte: Policy-/Identity-Code und Sprachpaar geprüft                | DOC-040           |
| DOC-P020 | 01      | Betrieb      | Erklärung | `ops/index.mdx` · `/{locale}/ops/`                                                                                  | Compose-, Pilot-, Backup- und Upgrade-README                            | freigegeben/freigegeben | Björn Schotte: Betriebsquellen, Sprachpaar und Build geprüft               | DOC-050           |
| DOC-P021 | 05      | Betrieb      | Tutorial  | `ops/tutorials/local-demo.md` · `/{locale}/ops/tutorials/local-demo/`                                               | `README.md`, `infra/compose/README.md`, `test-handoff`                  | freigegeben/freigegeben | Björn Schotte: Fresh-Checkout-Vertrag und Sprachpaar geprüft               | DOC-050           |
| DOC-P022 | 05      | Betrieb      | How-to    | `ops/how-to/deploy-pilot.md` · `/{locale}/ops/how-to/deploy-pilot/`                                                 | `infra/pilot/README.md`, Release-Runbook                                | freigegeben/freigegeben | Björn Schotte: Pilot-Gates und Sprachpaar geprüft                          | DOC-050           |
| DOC-P023 | 05      | Betrieb      | How-to    | `ops/how-to/backup-and-restore.md` · `/{locale}/ops/how-to/backup-and-restore/`                                     | `infra/backup/README.md`, Pilot-Runbook                                 | freigegeben/freigegeben | Björn Schotte: isolierter Recovery-Vertrag und Sprachpaar geprüft          | DOC-050           |
| DOC-P024 | 05      | Betrieb      | How-to    | `ops/how-to/upgrade-and-rollback.md` · `/{locale}/ops/how-to/upgrade-and-rollback/`                                 | `infra/upgrade/README.md`, Pilot-Release-Runbook                        | freigegeben/freigegeben | Björn Schotte: isolierter Upgrade-/Rollback-Vertrag und Sprachpaar geprüft | DOC-050           |
| DOC-P025 | 05      | Betrieb      | How-to    | `ops/how-to/troubleshoot.md` · `/{locale}/ops/how-to/troubleshoot/`                                                 | Compose-/Pilot-Diagnose, Auth-/Mail-/TLS-Nachweise                      | freigegeben/freigegeben | Björn Schotte: Diagnosecode und Sprachpaar geprüft                         | DOC-050           |
| DOC-P026 | 06      | Betrieb      | Referenz  | `ops/reference/requirements-and-configuration.md` · `/{locale}/ops/reference/requirements-and-configuration/`       | `./leonaid doctor`, `.env.example`, Pilot-Konfiguration                 | freigegeben/freigegeben | Björn Schotte: Konfigurationsverträge und Sprachpaar geprüft               | DOC-050           |
| DOC-P027 | 06      | Betrieb      | Referenz  | `ops/reference/services-ports-and-commands.md` · `/{locale}/ops/reference/services-ports-and-commands/`             | `infra/compose/compose.yml`, `./leonaid help`                           | freigegeben/freigegeben | Björn Schotte: Compose und CLI gegen Code geprüft                          | DOC-050           |
| DOC-P028 | 06      | Betrieb      | Erklärung | `ops/explanation/system-boundaries.md` · `/{locale}/ops/explanation/system-boundaries/`                             | Architektur, Compose und Datenhoheit                                    | freigegeben/freigegeben | Björn Schotte: Domain-/Persistenzcode und Sprachpaar geprüft               | DOC-050           |
| DOC-P029 | 06      | Betrieb      | Erklärung | `ops/explanation/operations-model.md` · `/{locale}/ops/explanation/operations-model/`                               | Pilot-, Backup-, Upgrade- und Incident-Verträge                         | freigegeben/freigegeben | Björn Schotte: Betriebsverträge und Sprachpaar geprüft                     | DOC-050           |
| DOC-P030 | 01      | Entwicklung  | Erklärung | `dev/index.mdx` · `/{locale}/dev/`                                                                                  | Development Guide, Workspace und Architektur                            | freigegeben/freigegeben | Björn Schotte: Entwicklerpfade, Sprachpaar und Build geprüft               | DOC-050           |
| DOC-P031 | 07      | Entwicklung  | Tutorial  | `dev/tutorials/first-change.md` · `/{locale}/dev/tutorials/first-change/`                                           | `specs/leonaid-poc/DEVELOPMENT.md`, `test-handoff`                      | freigegeben/freigegeben | Björn Schotte: Fresh-Checkout-Vertrag und Sprachpaar geprüft               | DOC-050           |
| DOC-P032 | 07      | Entwicklung  | How-to    | `dev/how-to/update-api-contract.md` · `/{locale}/dev/how-to/update-api-contract/`                                   | `tools/openapi`, API-Workflow, `generate-api-client`                    | freigegeben/freigegeben | Björn Schotte: API-Generator und Sprachpaar geprüft                        | DOC-050           |
| DOC-P033 | 07      | Entwicklung  | How-to    | `dev/how-to/debug.md` · `/{locale}/dev/how-to/debug/`                                                               | Development Guide, `./leonaid doctor`, Compose                          | freigegeben/freigegeben | Björn Schotte: Wrapper-/Compose-Code und Sprachpaar geprüft                | DOC-050           |
| DOC-P034 | 07      | Entwicklung  | How-to    | `dev/how-to/add-migration.md` · `/{locale}/dev/how-to/add-migration/`                                               | `migrations/README.md`, migration tests                                 | freigegeben/freigegeben | Björn Schotte: Alembic-Vertrag und Sprachpaar geprüft                      | DOC-050           |
| DOC-P035 | 08      | Entwicklung  | Referenz  | `dev/reference/api.mdx` · `/{locale}/dev/reference/api/`                                                            | `packages/api-client/openapi.json` via freigegebenem Generator          | freigegeben/freigegeben | Björn Schotte: deterministische Referenz und Sprachpaar geprüft            | DOC-050           |
| DOC-P036 | 08      | Entwicklung  | Referenz  | `dev/reference/repository-and-commands.md` · `/{locale}/dev/reference/repository-and-commands/`                     | Root-Workspace, App-/Package-READMEs, `./leonaid help`                  | freigegeben/freigegeben | Björn Schotte: Workspace-/CLI-Code und Sprachpaar geprüft                  | DOC-050           |
| DOC-P037 | 08      | Entwicklung  | Erklärung | `dev/explanation/architecture-and-data-ownership.md` · `/{locale}/dev/explanation/architecture-and-data-ownership/` | Architektur, Produktvorschlag und Adapter                               | freigegeben/freigegeben | Björn Schotte: Domain-/Adaptercode und Sprachpaar geprüft                  | DOC-050           |

## Nachvollzogene Abweichungen und Entscheidungen

| ID       | Ältere/uneindeutige Aussage                                                                  | Aktueller Befund                                                                                                                          | Dokumentationsentscheidung                                                                                      |
| -------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| DRIFT-01 | Root-README nennt HTTP-Einstiege; Compose-README nennt HTTPS als Mitgliederzugang.           | Caddy veröffentlicht den regulären lokalen HTTPS-Zugang auf `https://localhost:8443`; `http://localhost:8080` bleibt Diagnosezugang.      | Tutorial verwendet HTTPS und kennzeichnet HTTP ausschließlich als Diagnosepfad.                                 |
| DRIFT-02 | `specs/leonaid-poc/KNOWN-LIMITS.md` sagt, ein CMS fehle.                                     | `apps/campaign-site` enthält Astro 7 und EmDash; der jüngere EmDash-Slice ist implementiert.                                              | Grenzen beschreiben den aktuellen CMS-Schnitt: redaktionelle Darstellung in EmDash, Fachdaten im Core.          |
| DRIFT-03 | Ältere PoC-Texte beschreiben unvollständige Benutzeradministration.                          | `PERSONAS.md` und aktuelle Identity-/Session-Verträge führen Einladungen, Rollen, Sitzungsentzug und kontrollierten E-Mail-Wechsel.       | Rollen-/Zugangsseiten folgen dem aktuellen Vertrag und markieren verbleibende Grenzen explizit.                 |
| DRIFT-04 | Ausgangsdokumente enthalten keine durchgängige Lieferfenster-/Lieferkontaktstrecke.          | `specs/krapfentaxi-lieferplanung/PROGRESS.md` dokumentiert vollständige Core-, UI-, Browser- und Integrationsnachweise.                   | Der Anwenderumfang enthält Lieferfenster und getrennten optionalen Lieferkontakt.                               |
| DRIFT-05 | Technische Pilotdokumente können wie eine Produktionsfreigabe wirken.                        | `infra/pilot/README.md` nennt noch offene reale DNS-/TLS- und Betreiber-Nachweise; der Plan trennt technische Tests von externer Abnahme. | Jede Pilotseite trägt den Entwicklungs-/Pilotstatus und nennt externe Entscheidungen als Voraussetzungen.       |
| DRIFT-06 | `finance_manager` ist fachlich vorgesehen, aber nicht als dauerhafter Golden-Login gepflegt. | `PERSONAS.md` weist Finn Finanzen als `finance_reader` aus; Charity-Admins dürfen in eigenen Aktionen buchen.                             | Zahlungstutorial nutzt den Charity-Admin der Demo und erklärt den globalen Finance-Manager nur in der Referenz. |
| DRIFT-07 | Das Root-README ist zugleich Projektseite und ausführliches Handbuch.                        | Verteilte Detailanleitungen sollen in die zweisprachige Site migrieren.                                                                   | README wird nach DOC-040/050 kurz, englisch und verlinkt die real vorhandenen Rohquellen.                       |

## Bewusste Zurückstellungen

- SurveyJS-Redaktions-, Analyse- und Exporthandbücher sind technisch vorhanden,
  gehören aber nicht zu CONTENT-01 bis CONTENT-08. Ein Folgeinventar kann sie
  aufnehmen; die Startseite behauptet keine vollständige Produktabdeckung.
- Vollständige EmDash-Redaktionsschulung, CRM-Import, Datenschutz-Workflows,
  Mitgliederverwaltung und Feature-Flag-Betrieb bleiben nach dem ersten
  Umfang eigene Dokumentations-Slices.
- PDF-Handbücher, Versionsumschalter, In-App-Hilfe und weitere Locales bleiben
  gemäß Plan außerhalb des ersten Umfangs.

## Pflege des Inventars

DOC-040 und DOC-050 ersetzen `geplant` durch `freigegeben` nur nach fachlichem
und sprachlichem Review. Änderungen am Seitenumfang aktualisieren ID, Quelle,
Review und Abnahme gemeinsam. Entfernte Seiten behalten ihre ID im
`PROGRESS.md`, damit Links und Entscheidungen nachvollziehbar bleiben.
Jede Freigabe nennt den geprüften Codepfad und einen passenden ausführbaren
Nachweis; ein historisches Dokument allein reicht dafür nicht aus.
