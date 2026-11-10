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
  Editor-Setup, Aktionsschema) läuft mit `./leonaid pilot-cms-provision` auf
  einer laufenden Installation; `pilot-install` richtet das CMS nicht mit ein.
  Die erste LeonAid-Systemadministration legt `./leonaid
  pilot-create-system-admin` an (Anmeldemail, kein Passwort).
  Die erste EmDash-Einrichtung braucht eine LeonAid-Systemadministration im
  Browser (15-Minuten-Freigabe). Eine unterbrochene Einrichtung gibt
  `--reset-setup` nur frei, solange das CMS unbenutzt ist. Backups enthalten
  das CMS erst ab abgeschlossener Einrichtung. `pilot-release` migriert neue
  EmDash-Migrationen unter geschlossenem CMS-Verkehr; ein Anheben der
  redaktionellen Schemaversion (`upgrade-v<N>` unter dem vorherigen Image)
  gehört noch nicht dazu, und ein Rollback ist ein Restore aus dem
  Release-Backup.
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
- Offline-Erfassung (`specs/pwa-offline-queue/PLAN.md`, Hilfe DOC-P050) ist
  vollständig gebaut, aber hinter dem Feature-Flag `pwa.offline_queue`
  (Standard aus); ohne Flag zeigt die PWA offline nur bereits geladene
  Inhalte und speichert nichts (`packages/ui/src/components/mobile-shell.tsx`).
  Mit Flag startet die PWA offline, zeigt die eigene Sponsorenliste und die
  Bestellangaben aus einer verschlüsselten Kopie auf dem Gerät (7 Tage
  anzeigen, 14 Tage behalten, auch offline; gelöscht bei Abmelden und
  Kontowechsel in Akquise-App und Verwaltungsbereich) und legt Kontakte, Wiedervorlagen,
  Bestellungen und Sponsor-Entwürfe in eine Warteschlange, die mit
  `Idempotency-Key` und `capturedAt` sendet. Konflikte entscheidet der
  Akquisiteur in der Warteschlange (PLAN §10). Grenzen:
  - Die Prüfung auf einem echten iPhone (PLAN §13, Speicher einer
    Home-Screen-App) steht aus; bewiesen ist WebKit in Playwright.
  - Startseite (Aktionsstand), Module und Lieferboard bleiben offline
    gesperrt; Bestellabschlüsse von Entwürfen (`completeCommitment`) gehen
    nicht über die Warteschlange.
  - „Meine Wiedervorlage übernehmen“ setzt die Fälligkeit auf 09:00 Uhr der
    Gerätezeitzone, nicht der Club-Zeitzone.
  - Schaltet die System-Administration das Flag aus, sendet die App noch
    wartende Einträge und löscht danach die Daten auf dem Gerät; neue
    Erfassungen gehen dann wieder nur online.
  - Der Core verlangt den `Idempotency-Key` für Kontakte noch nicht (PLAN
    §11.1, eine Version Übergang).
  - Eine serverseitig widerrufene Sitzung sieht ein Gerät erst online.
  - Abmelden fragt in Akquise-App und Verwaltungsbereich, solange Einträge
    warten; „Trotzdem abmelden“ löscht sie vom Gerät.
  - Die Straße, die jemand bei der CRM-Prüfung eines Sponsor-Entwurfs
    ergänzt, bleibt verschlüsselt auf dem Gerät, bis die Prüfung abgeschlossen
    oder der Entwurf verworfen ist, längstens 14 Tage (E-017): eine
    wiederholte Prüfung muss genau dieselbe Anfrage senden.
  - Im Ausschalt-Modus halten Einträge mit Entscheidung oder Fehler das Gerät
    bis zu 16 Tage (Ablauf plus Warnfrist); „Nicht mehr möglich“ (keine
    Berechtigung mehr) hält es, bis die Person den Eintrag verwirft.
  - Die Bestelldetails im Backoffice zeigen „Erfasst offline“, wenn eine
    Erfassung mehr als 5 Minuten nach `capturedAt` ankam.
  - Das Flag darf erst eingeschaltet werden, wenn ein Mitglieder-
    Datenschutzhinweis mit dem Abschnitt zur Speicherung auf dem Gerät aktiv
    ist; LeonAid prüft das nicht selbst.
- Push-Nachrichten, Etikettendruck, Druck-/Packliste, Herstellerabrechnung
  und Materialbestand fehlen.
- Dokumentverwaltung umfasst erzeugte und fachlich zugeordnete Belege sowie
  das Material-Modul (Upload mit Versionen). Ein allgemeines DMS mit
  Volltextsuche fehlt.
- listmonk und Canva sind nicht Teil des Core-PoC.
- Core search (`GET /api/v1/search`) finds actions, orders, invoices,
  sponsors and members. Sponsors come from a local index
  (`sponsor_search_entry`: name and city only), not from a CRM call per
  keystroke. Limits of the sponsor search:
  - Only parties with an acquisition assignment are found, one hit per
    assignment the account may see (managers: every assignment of their
    actions; acquirers: their own that are not handed over). E-mail, phone
    and street are not in the index and cannot be searched.
  - The index follows Twenty by polling (no webhook): a name or city changed
    in Twenty arrives within about 15 minutes; a party deleted in Twenty
    leaves the index with the nightly full pass (after 03:00 local time).
    Until then the hit still appears, and its target does not open: the
    acquisition board refuses an action that has an assignment to a party
    Twenty no longer has.
  - The worker loop `sponsor_search_sync` spends at most 30 CRM requests per
    run and stops on the first 429. The gateway counts its 100 requests a
    minute per process, so API and worker together can still exceed Twenty's
    limit. A full pass reads 50 parties per request; a large stock is read
    over several runs, one minute apart.
  - After a privacy erasure the entry keeps no name or city, only a marker
    that stops the sync from copying the name back. Deleting the party in
    Twenty stays a manual step (see the erasure limits).
  - The acquisition PWA has no search. An acquirer's hit in the web admin
    opens the sponsor in the PWA.
- Orders can be cancelled until they are delivered (`cancelCommitment`):
  they leave the delivery board, an open "Nachliefern" task closes and an
  issued, unpaid invoice is cancelled under ADR-0009 (status `cancelled`,
  number, snapshot and PDF unchanged). Not implemented: a separately
  numbered cancellation document (Stornorechnung) with its own PDF; its
  number and link contract is an open decision for Björn (ADR-0004/0009
  defer it). An active (not reversed) payment entry blocks the
  cancellation until it is reversed ("Zurückbuchen" in the invoice pane);
  LeonAid books no refunds. A cancelled order cannot be reopened.
- Buyer mails (`application/order_mails.py`): a public-form order sends one
  plain-text order confirmation, and its cancellation one cancellation
  notice, through the outbox (`order.confirmation.mail.v1`,
  `order.cancellation.mail.v1`; one job and one SMTP ledger row per order
  and kind). The job holds ids and links only; the worker reads the order
  and the active legal configuration when it sends, so an erased buyer gets
  nothing. Delivery is at least once: a crash between the SMTP server
  accepting a mail and the ledger write sends it again on the retry. A
  confirmation whose order is already cancelled is skipped. At most 10 order
  mails go to one mailbox per hour (`+tag` variants and Gmail dot variants
  count as one mailbox; an advisory lock per mailbox keeps parallel workers
  under the limit); a job over that limit is dead-lettered
  (`order_mail_recipient_limit`, operations view, manual retry). Other
  providers' aliases are not recognised. Public order fields refuse line
  breaks, tabs, control, format, surrogate, private-use and unassigned
  characters and visually blank letters (U+3164, U+2800 and similar);
  recipient name, street and city also refuse `://`, `www.` and `@`. The
  mail strips such characters from older data.
  The mail repeats the full delivery and billing address so the buyer can
  check it. Not covered: orders entered by members or acquirers (no mail,
  also no cancellation notice), an HTML version, a club sender address (the
  configured `MAIL_FROM` sends), a resend button, and mails for later order
  changes (delivery window moved, invoice issued). Fulfilment mails ignore
  the marketing/acquisition suppression list. The campaign link is the
  permanent edition URL on the campaign host (decision D8), else the public
  host page (`edition_link`).

- Impressum (`/impressum`) und Datenschutzerklärung (`/datenschutz`) kommen
  aus der aktiven rechtlichen Konfiguration (Vier-Augen-Freigabe, Migration
  0054). Im Produktivbetrieb blockieren fehlende Vertretungsberechtigte,
  fehlendes Telefon, eine nicht gewählte Rechtsform, ein fehlender
  Registereintrag bei einer Rechtsform mit Register (e. V., GmbH, gGmbH, eG),
  eine fehlende USt-ID, wenn die Steuerkennung eine ist, fehlende
  Datenschutztexte und offene `[[ … ]]`-Platzhalter die Aktivierung. LeonAid
  prüft nur das Vorhandensein, nicht die rechtliche Richtigkeit der Texte. Die
  Rechtsformen sind eine feste Liste; weitere Formen fallen unter „Sonstige“
  ohne Registerpflicht.
- Nach dem Update auf 0054 ist eine schon aktive Version unvollständig;
  `/admin/legal` warnt, bis eine neue Version aktiviert ist. Der
  Readiness-Endpunkt (`/api/health/ready`) prüft die rechtlichen Angaben
  nicht.
- Die Vorlagen für Datenschutzerklärung und Mitgliederhinweis
  (`packages/features/src/system-admin/legal-templates.ts`), einschließlich des
  Abschnitts zur Gerätespeicherung der Akquise-App (PWA-Offline-Queue, D8),
  sind noch nicht von Björn Schotte geprüft. Der Gerätespeicher-Abschnitt
  beschreibt die Offline-Erfassung; die Akquise-App speichert diese Daten nur
  mit eingeschaltetem Flag `pwa.offline_queue`. Er nennt auch die Kurzform der
  eigenen Anmeldung (Name, Aktionen, Rollen) für den Offline-Start und die
  Rechnungsadresse einer noch nicht gesendeten Bestellung; Claude Code hat
  diesen Text vorgeschlagen, die Prüfung durch Björn Schotte und die
  Freigabe im Vier-Augen-Ablauf stehen aus. Ein `[[ … ]]`-Hinweis im Abschnitt blockiert
  die produktive Aktivierung, bis der Club ihn bewusst behält oder löscht.
- Es gibt ein Impressum und eine Datenschutzerklärung je Installation, auf
  allen Hosts unter denselben Pfaden (Multi-Domain D4). Eigene Inhalte je Host
  sind nicht vorgesehen; die Darstellung je Host folgt mit Multi-Domain
  Stufe 2 (§7.5) und nutzt dieselben Komponenten.
- Die Datenschutzseite ist offline nicht erreichbar; die Akquise-App verlinkt
  sie, speichert sie aber nicht.

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
  (`site_host`, `site_binding`, Migration 0056), prüfen sie (Port 80,
  danach TLS über Caddys On-Demand-Zertifikate; höchstens zehn neue pro
  Stunde; tägliche Nachprüfung) und liefern dort die Kampagnenseiten aus
  (Ausgaben unter `/<segment>/`, Archivseite nach dem Ende, `/archive/`,
  eigene `robots.txt`/`sitemap.xml`; alte Pfade und Aliase leiten weiter).
  Eine Domain zeigt nur CMS-Kampagnenseiten. Bestellmails an
  Besteller verlinken die dauerhafte Ausgaben-URL (D8, `edition_link`, nie die
  Wurzel). Status-Caches: `ask` 10 s, Host-Freigabe in Campaign-Site,
  Public-App und Core-Origins je 30 s. Die Domain-Verwaltung ist bis zum
  grünen Stack-Nachweis als Vorschau markiert. Die Abnahme mit echtem ACME und einer echten Domain ist
  offen (`tools/site_hosts/acme_probe.py`). Eine
  Installation ohne öffentlichen Host (`pilot-secrets --no-public-host`,
  `Caddyfile.admin-only`) ist im Deployment-Vertrag abgedeckt und mit
  echten Diensten nachgewiesen (EmDash `campaign-hosts`, zweite Runde). `/` auf dem Verwaltungshost ist der
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
- Die Hilfe-Doku trägt auf 21 Seiten je Sprache noch den Vermerk „Prüfung
  durch Björn Schotte offen“ (Frontmatter `reviewer:` in `apps/docs`).
- OpenFeature ist integriert; der PoC bietet zwei administrative Flags.
  Ein externes Flag-Backend, Segmentierung und gestaffelte Prozent-Rollouts
  fehlen.
- RustFS ist der PoC-Default. SeaweedFS beweist nur den neutralen S3-Vertrag
  und ist kein zweiter produktiver Cluster.
- Der Restore nur des CMS (`LEONAID_RESTORE_SCOPE=cms` in
  `tools/backup/restore-body.sh`) läuft in keinem Stack-Test mehr; nur seine
  Eingangsprüfung (`tools/backup/restore_scope_test.py`) läuft in
  `./leonaid check`. Der nightly Pilot-Install-Drill stellt mit `full` wieder
  her (E-028).

## Einordnung

Aktuell sind keine bekannten P0-/P1-Defekte in der bewiesenen
Krapfentaxi-Golden-Journey offen. Die genannten Grenzen blockieren je nach
Einsatz eine Produktiv- oder Pilotfreigabe und dürfen nicht durch die
technische PoC-Abnahme übergangen werden. Offene fachliche und rechtliche
Entscheidungen stehen zusätzlich in [`DECISIONS.md`](DECISIONS.md).
