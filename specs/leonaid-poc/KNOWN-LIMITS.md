# Bekannte Grenzen des PoC

Stand: 2026-11-06 (abgeglichen mit `main` bei `af276b7f`)

Diese Liste trennt bewusst verschobenen Scope von Defekten. Die
Krapfentaxi-Golden-Journey ist technisch vollständig bewiesen; die folgenden
Punkte sind keine stillschweigenden Produktzusagen.

## Produkt und Fachlichkeit

- Krapfentaxi ist der einzige implementierte End-to-End-Use-Case. Lions Open
  und Weihnachtsmarkt haben weder Vorlagen noch Capabilities (Code kennt nur
  die Vorlagen `blank` und `krapfentaxi`).
- Öffentliche Seiten verwenden versionierte Standardformulare. Es gibt
  keinen Form-Builder und keinen freien Workflow-Editor. Die
  Kampagnen-Microsite ist im EmDash-CMS (`apps/campaign-site`) bearbeitbar.
  Im Pilot-Stack läuft sie mit `LEONAID_CMS_ENABLED=true` (Profil `emdash`,
  Release-Image `campaign-site`, Manifest `release-manifest-cms.json`). Die
  einmalige Einrichtung in Produktion (CMS-Datenbankrolle, Medien-Bucket,
  Editor-Setup) hat noch keinen `pilot-*`-Befehl; sie läuft nur über die
  Spike-Operatoren (`infra/emdash-spike/service.test.yml`).
- ERP-light umfasst Bestellungen, Ausgangsrechnungen, Typst-PDFs, Versand und
  manuell erfasste Zahlungseingänge: Teil-, Voll- und Überzahlungen sowie
  begründete Rückbuchungen einzelner Einträge (ADR-0014). Eine Überzahlung
  wird nur angezeigt; die Erstattung läuft außerhalb von LeonAid und wird
  nicht gebucht. Bankabgleich, Buchhaltung, E-Rechnung, Mahnwesen, Payment
  Provider, Spendenzahlungen und Spendenbescheinigungen fehlen.
- Lieferfenster, Fahrerzuweisung und Abhaken im Lieferboard sind gebaut.
  Tourenplanung, Karte und Navigation fehlen. Die Fenster-Kapazität ist keine
  Zahl: es gibt nur das manuelle Kennzeichen „ausgebucht“
  (`src/leonaid/application/delivery.py`), keine Überbuchungswarnung.
- Offline-Erfassung fehlt: die PWA zeigt offline nur bereits geladene Inhalte
  und speichert keine Änderungen (`packages/ui/src/components/mobile-shell.tsx`;
  Spezifikation `specs/pwa-offline-queue/PLAN.md`). Der Core nimmt
  nachgereichte Erfassungen schon an (Stufe 2, PLAN §11): `Idempotency-Key`
  für Kontakte (noch optional), `capturedAt` für Kontakte und Bestellungen
  (höchstens 14 Tage zurück, 5 Minuten voraus), Preisprüfung
  `commitment_price_changed` und Kontakt trotz geänderter Zuordnung
  (`assignmentUpdated: false`). Die Bestelldetails zeigen `capturedAt` noch
  nicht an; das kommt mit der Warteschlange (Stufe 3). Push-Nachrichten,
  Etikettendruck, Druck-/Packliste, Herstellerabrechnung und Materialbestand
  fehlen.
- Dokumentverwaltung umfasst erzeugte und fachlich zugeordnete Belege sowie
  das Material-Modul (Upload mit Versionen). Ein allgemeines DMS mit
  Volltextsuche fehlt.
- listmonk und Canva sind nicht Teil des Core-PoC.
- Core search (`GET /api/v1/search`) finds actions, orders, invoices and
  members. It does not find sponsors: they live only in Twenty, and the
  search does not call the CRM per keystroke. The `sponsor` result type is
  reserved for a later local sponsor index.
- Orders can be cancelled until they are delivered (`cancelCommitment`):
  they leave the delivery board, an open "Nachliefern" task closes and an
  issued, unpaid invoice is cancelled under ADR-0009 (status `cancelled`,
  number, snapshot and PDF unchanged). Not implemented: a separately
  numbered cancellation document (Stornorechnung) with its own PDF; its
  number and link contract is an open decision for Björn (ADR-0004/0009
  defer it). An active (not reversed) payment entry blocks the
  cancellation until it is reversed ("Zurückbuchen" in the invoice pane);
  LeonAid books no refunds. The buyer is not e-mailed about the cancellation, and a
  cancelled order cannot be reopened.

- Impressum (`apps/public/src/pages/impressum.astro`) zeigt nur Name,
  Anschrift und E-Mail des Anbieters. Vertretungsberechtigte, Registereintrag,
  gegebenenfalls USt-ID und ein zweiter Kontaktweg nach § 5 DDG fehlen
  (`src/leonaid/domain/legal_configuration.py` hat keine Felder dafür).
- Es gibt keine eigene Datenschutzseite. Der Datenschutzhinweis steht nur auf
  Aktionsseiten (`apps/public/src/pages/[...path].astro`); Login, Einladung,
  Umfragen und Impressum verlinken nicht darauf.

## Identität und Administration

- Passwortloser Login unterstützt E-Mail-Link und sechsstelligen Code.
  Passkeys, SSO, Social Login und öffentliche Selbstregistrierung fehlen.
- Mitglieder können ihre Login-E-Mail nicht selbst ändern. Ein Admin stößt
  die Änderung an, die neue Adresse muss sie bestätigen
  (`POST /api/v1/identity/members/{user_id}/email-change`).
- Einladungen (Liste, erneut senden, Adresse korrigieren, widerrufen),
  Sitzungsentzug, Sperren/Archivieren, Entzug von Aktions- und globalen
  Rollen, Rollenwechsel und E-Mail-Korrektur sind als Admin-Workflow
  implementiert (`/api/v1/admin/members/*`, UI `/admin/members`). Direkte
  produktive Datenbankänderungen sind kein akzeptierter Ersatz.
- Eine Installation bildet genau einen Club/Träger ab. Mehrere Clubs
  benötigen getrennte Installationen.

## Betrieb und Produktivfreigabe

- Der PoC ist für einen einzelnen Docker-Compose-Host ausgelegt. Es gibt
  keine Hochverfügbarkeit, automatische horizontale Skalierung oder
  unterbrechungsfreie Multi-Region-Wiederherstellung.
- Mailpit ist ausschließlich lokales Testsystem. Der SMTP-Adapter ist
  gebaut; der produktive Relay (Anbieter, SPF/DKIM/DMARC, Bounces) ist noch
  auszuwählen und zu konfigurieren (Entscheidung OPS-001).
- Backups, Restore und Upgrade sind technisch bewiesen. Der konkrete
  Off-VPS-Storage, Secret-Manager, DNS-Betrieb und Alarmkanal bleiben
  Betreiberentscheidungen.
- Rechtliche Aufbewahrungs-/Löschfristen, produktive Trägerdaten,
  Steuerfall und E-Rechnungsbedarf benötigen Datenschutz-, Rechts- und
  Steuerfreigabe.
- Updates laufen über `pilot-release` im Wartungsmodus. Es gibt keinen
  Schutz für laufende Aktionen: offenes Bestellformular oder Liefertag werden
  nicht geprüft, `POST`-Anfragen im Wartungsmodus liefern `503`. Ändert ein
  Club eine von LeonAid verwaltete Twenty-Ansicht, bricht der Provisioner mit
  `SchemaDrift` ab (`specs/release-updates/PLAN.md`, Risiken R3 und R7).
  `./leonaid update` und signierte Releases sind nur spezifiziert.
- Eine Installation bedient einen Host oder einen Verwaltungshost
  (`app.<domain>`) plus einen öffentlichen Host mit Weiterleitungsnamen
  (`specs/multi-domain/PLAN.md`, Stufe 1; `infra/pilot/Caddyfile.split`).
  Eigene Kampagnen-Domains (Stufe 2) sind in Arbeit: System-Admins tragen
  Domains unter **System › Domains** ein und binden Ausgaben
  (`site_host`, `site_binding`, Migration 0055), prüfen sie (Port 80,
  danach TLS über Caddys On-Demand-Zertifikate; höchstens zehn neue pro
  Stunde; tägliche Nachprüfung) und liefern dort die Kampagnenseiten aus
  (Ausgaben unter `/<segment>/`, Archivseite nach dem Ende, `/archive/`,
  eigene `robots.txt`/`sitemap.xml`; alte Pfade und Aliase leiten weiter).
  Eine Domain zeigt nur CMS-Kampagnenseiten. Offen (D8): Eine
  Bestellbestätigung per Mail an Besteller gibt es nicht; der Link dafür ist
  in Core vorbereitet (`edition_link`, die dauerhafte Ausgaben-URL, nie die
  Wurzel). Status-Caches: `ask` 10 s, Host-Freigabe in Campaign-Site,
  Public-App und Core-Origins je 30 s. Die Domain-Verwaltung ist bis zum
  grünen Stack-Nachweis als Vorschau markiert. Die Abnahme mit echtem ACME und einer echten Domain ist
  offen (`tools/site_hosts/acme_probe.py`). Eine
  Installation ohne öffentlichen Host ist nur spezifiziert. `/` auf dem Verwaltungshost ist der
  rollenbasierte Einstieg (`/login/start`: Anmeldung, dann `landingPath`). Weiterleitungsnamen des
  öffentlichen Hosts gibt es im Dev-Stack nicht. Beim Umstellen auf zwei
  Hosts melden sich alle Mitglieder einmal neu an
  (`pilot-revoke-sessions`). Auf dem öffentlichen Host zeigt die Kopfzeile
  einen festen Link „Mitgliederbereich“ statt der persönlichen App-Links (#82): die
  Sitzung gehört zum Verwaltungshost, und die CSP (`connect-src 'self'`)
  erlaubt keine Abfrage dort. Die Live-Abnahme der Aktionsseiten im
  Split-Modus (CMS hinter `Caddyfile.split`) fehlt; der Stack-Beweis
  `test-multi-host` läuft ohne CMS. Die öffentliche Startseite listet aktive
  Aktionen; eine `sitemap.xml` des öffentlichen Hosts gibt es noch nicht
  (Stufe 2).
- Die Hilfe-Doku trägt auf 20 Seiten je Sprache noch den Vermerk „Prüfung
  durch Björn Schotte offen“ (Frontmatter `reviewer:` in `apps/docs`).
- OpenFeature ist integriert; der PoC bietet zwei administrative Flags.
  Ein externes Flag-Backend, Segmentierung und gestaffelte Prozent-Rollouts
  fehlen.
- RustFS ist der PoC-Default. SeaweedFS beweist nur den neutralen S3-Vertrag
  und ist kein zweiter produktiver Cluster.

## Einordnung

Aktuell sind keine bekannten P0-/P1-Defekte in der bewiesenen
Krapfentaxi-Golden-Journey offen. Die genannten Grenzen blockieren je nach
Einsatz eine Produktiv- oder Pilotfreigabe und dürfen nicht durch die
technische PoC-Abnahme übergangen werden. Offene fachliche und rechtliche
Entscheidungen stehen zusätzlich in [`DECISIONS.md`](DECISIONS.md).
