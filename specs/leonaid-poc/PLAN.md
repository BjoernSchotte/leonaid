# LeonAid PoC – technischer Implementierungsplan

Status: in Umsetzung; POC-000 bis POC-002, POC-010 bis POC-012, POC-020 bis
POC-023 und POC-030 bis POC-031 vollständig bewiesen
Primäre Spezifikation:
[Produkt- und Architekturvorschlag](../produkt-und-architekturvorschlag.md)

## 1. Ziel und Arbeitsweise

Der PoC beweist einen vollständigen Krapfentaxi-Ablauf:

1. Charity-Admin legt eine Aktion an und lädt einen Akquisiteur ein.
2. Der Akquisiteur übernimmt oder erfasst einen Sponsor in der PWA.
3. Eine Bestellung entsteht intern oder über die öffentliche Aktionsseite.
4. Der Charity-Admin prüft sie, authentifiziert sich frisch und gibt die
   Rechnung frei.
5. LeonAid erzeugt ein unveränderliches PDF, speichert es in RustFS, versendet
   es und verbucht später den Zahlungseingang manuell.
6. Rollen, Historie, Aktivitätsfeed, Zielerreichung, Backup und Restore sind
   praktisch nachgewiesen.

Der fachliche Scope folgt
[Kapitel 10](../produkt-und-architekturvorschlag.md#10-poc--empfohlener-vertikaler-schnitt).
Nicht-Ziele aus Kapitel 10.2 werden nicht nebenbei implementiert.

### 1.1 Verbindliche Ausführungsregeln

- Jeder Task wird erst abgehakt, wenn alle zugehörigen Akzeptanzkriterien und
  Tests ebenfalls abgehakt sind.
- Kein Task gilt allein aufgrund eines Code Reviews oder grüner
  Happy-Path-Tests als fertig.
- Es gibt keine Mock-Server, keine gemockten Repositories, keine In-Memory-
  Ersatzimplementierungen in Abnahmetests und keine Attrappen externer
  Systeme.
- Unit-Tests prüfen reine Domain-Logik mit echten Domain-Objekten aus dem
  versionierten Golden Dataset.
- Integrationstests verwenden reale, gepinnte Instanzen von PostgreSQL,
  Twenty, Twenty-PostgreSQL, Twenty-Redis, RustFS, Mailpit und den realen
  Typst-Renderer.
- E2E-Tests bedienen die tatsächlich gebauten Anwendungen in realen Browsern
  und prüfen anschließend die sichtbaren Ergebnisse in UI, API, Datenbank,
  Mailpit und RustFS.
- Fehlerfälle werden durch reale Zustände erzeugt, beispielsweise Container
  stoppen, Zugang entziehen, Daten konfliktbehaftet anlegen oder Requests
  wiederholen. Ein Fehler-Response wird nicht künstlich vorgetäuscht.
- Alle Tests beginnen aus einem bekannten Golden-Dataset-Snapshot und
  hinterlassen eine nachvollziehbare Testausgabe.
- Produkt- und Testcode verwenden denselben Persistence-, Auth-, CRM-,
  Storage-, PDF- und Mailpfad.
- Abhängigkeiten, Container-Images, Browser und Build-Werkzeuge werden auf
  exakte Versionen und Images zusätzlich auf Digests gepinnt. `latest`,
  ungebundene SemVer-Bereiche und implizite Downloads sind verboten.
- UX, Barrierefreiheit, responsive Bedienung, verständliche Fehlerzustände
  und schnelle Feedbackschleifen sind Definition of Done jedes vertikalen
  Slices, kein späteres Verschönerungsprojekt.

### 1.2 Definition of Done für jeden Produkt-Slice

Jeder Produkt-Slice erfüllt mindestens:

- [ ] Fachregel liegt in einem serverseitigen Application Service oder
      Domain-Modul, nicht ausschließlich in FastAPI, Astro Actions oder
      Browser-Code.
- [ ] Autorisierung wird serverseitig positiv und negativ getestet.
- [ ] OpenAPI-Vertrag und generierter TypeScript-Client sind aktuell.
- [ ] Lade-, Leer-, Erfolg-, Konflikt- und Fehlerzustände sind gestaltet.
- [ ] Bedienung funktioniert mit Tastatur sowie auf Smartphone und Desktop.
- [ ] UI-Texte sind auf Deutsch, konkret und handlungsorientiert.
- [ ] Relevante Mutationen sind idempotent oder besitzen eine dokumentierte
      Konfliktstrategie.
- [ ] Audit- und Observability-Signale enthalten Korrelation, aber keine
      unnötigen personenbezogenen oder geheimen Daten.
- [ ] Unit-, Integrations- und E2E-Tests mit Golden Data sind grün.
- [ ] Reale Artefakte wie E-Mail oder PDF werden inhaltlich und technisch
      geprüft, nicht nur auf Existenz.

## 2. Zielarchitektur und Repository-Schnitt

Die Umsetzung folgt
[Kapitel 6](../produkt-und-architekturvorschlag.md#6-vorgeschlagene-zielarchitektur)
und bleibt ein modularer Monolith.

```text
apps/
  api/                       FastAPI HTTP-Adapter
  worker/                    durable Outbox-/Job-Verarbeitung
  web/                       React-Backoffice und Charity-Admin UI
  pwa/                       React-PWA für operative Rollen
  public/                    Astro-7-Aktionsseiten
packages/
  ui/                        Design Tokens, shadcn/ui, Icons, Patterns
  features/                  host-neutrale fachliche React-Features
  api-client/                aus OpenAPI generierter TypeScript-Client
  testkit/                   Golden-Data-IDs und echte Test-Clients
src/leonaid/
  domain/                    Aggregate, Value Objects, Domain-Regeln
  application/               Use Cases, Policies, Ports, Transaktionen
  adapters/
    postgres/
    twenty/
    storage/
    mail/
    typst/
  entrypoints/
    fastapi/
    worker/
infra/
  compose/
  twenty/
  rustfs/
  proxy/
  backup/
tests/
  unit/
  integration/
  contract/
  e2e/
  fixtures/golden/v1/
```

FastAPI, Worker und ein späterer FastMCP-Adapter rufen dieselben Application
Services auf. Fachlogik wird nicht in HTTP-Routen, Astro Actions,
React-Komponenten oder spätere MCP-Tools dupliziert. Siehe
[Kapitel 6.1](../produkt-und-architekturvorschlag.md#61-leonaid-core-api).

## 3. Verbindliche Test- und Datenstrategie

### 3.1 Golden Dataset v1

Das Golden Dataset ist klein genug, um verstanden zu werden, und reich genug,
um Berechtigungs-, Matching-, Lifecycle- und Rechnungsfälle abzudecken.
Personen und Firmen sind synthetisch; alle E-Mail-Adressen verwenden eine
reservierte Testdomain.

| Bereich | Mindestinhalt |
|---|---|
| Benutzer | 1 System-Admin, 2 Charity-Admins, 3 Akquisiteure, 1 Finanzrolle, 1 gesperrter Benutzer |
| Aktionen | Krapfentaxi aktiv, Krapfentaxi Vorjahr archiviert und zweite fremdverwaltete Krapfentaxi-Testaktion |
| Beneficiaries | mindestens 2 Begünstigte der aktiven Krapfentaxi-Aktion |
| Firmen | eindeutige Firma, normalisierter Namenskonflikt, Firma mit zwei Ansprechpartnern, Firma ohne Zuweisung |
| Personen | eigenständiger Sponsor ohne Firma, gleichnamige Person mit unterscheidenden Zusatzdaten |
| Zuweisungen | exklusiv A, exklusiv B, gemeinsam A+B, unzugeordnet |
| Angebote | Krapfenbox mit Boxen- und Stückumrechnung, inaktives Angebot |
| Bestellungen | Entwurf, prüfbereit, öffentlich eingegangen, bereits fakturiert |
| Rechnungen | offen, bezahlt, storniert sowie unveränderlicher Adress-Snapshot |
| Aktivitäten | interne Akquise, öffentliche Bestellung, Mitzuordnung |
| Public Web | Alias `krapfentaxi`, aktiver Archiv-Slug, historischer Archiv-Slug |

Golden Data besitzt stabile UUIDs, erwartete fachliche Ergebnisse und eine
menschenlesbare Dokumentation. Passwörter oder produktive Secrets gehören
nicht hinein.

### 3.2 Teststufen

| Stufe | Reale Bestandteile | Zweck |
|---|---|---|
| Unit | Domain-Objekte und Golden-Data-Werte | Invarianten, Statusautomaten, Geld-/Mengenrechnung, Policies |
| Integration | echter Prozess plus reale abhängige Container | SQL, Transaktionen, Twenty API, S3, SMTP, Typst, Outbox |
| Contract | produktive Clients gegen echte gepinnte Systeme | verwendete Twenty-, S3-, Mail- und OpenAPI-Teilmenge |
| E2E | Reverse Proxy, alle Core-Dienste, Chromium, Firefox und WebKit | reale Benutzerabläufe und visuelle/responsive Qualität |
| Recovery | frische Volumes/Instanz aus echten Backups | RPO/RTO, Prüfsummen, referenzielle Vollständigkeit |

Unit-Tests dürfen für reine Funktionen direkt konstruierte Golden-Data-
Objekte verwenden. Sobald I/O, Zeitablauf, Identität oder ein Fremdsystem
Teil des Verhaltens sind, wird das reale System beziehungsweise ein realer
Prozess verwendet. Determinismus entsteht durch explizite Eingabedaten,
kontrollierte Ablaufzeitpunkte und frische Datenbanken, nicht durch Mocks.

### 3.3 Verbindliche Qualitätsgates

- Python: Formatter, Linter, statische Typprüfung, Dependency Audit,
  Unit-/Integrationstests und Coverage-Bericht.
- TypeScript: Formatter, Linter, Typecheck, Unit-/Componenttests und
  Produktionsbuild aller Apps.
- API: OpenAPI-Diff, generierter Client ohne Dirty Diff,
  Schema-/Migrationstest.
- Browser: Chromium, Firefox und WebKit; Smartphone- und Desktop-Viewports.
- Accessibility: automatisierter Scan plus manueller Tastatur- und
  Screenreader-Smoke-Test der kritischen Flows.
- Visual: versionierte Screenshots der Golden-Data-Kernseiten bei mindestens
  390 px und 1440 px Breite.
- Performance: definierte Budgets für Startseite, Kernlisten und wichtigste
  Mutationen unter lokal reproduzierbarer Last.
- Security: Dependency-/Image-Scan, Secret-Scan, Autorisierungs-Negativsuite
  und Browser-Sicherheitsheader.
- Operations: Backup/Restore, Upgrade und realer Ausfall mindestens eines
  abhängigen Dienstes.

### 3.4 Messbare UX-/DX-Budgets

„World-class“ wird für den PoC nicht nur als Geschmacksurteil verwendet:

| Dimension | Verbindliches PoC-Budget |
|---|---|
| Accessibility | WCAG 2.2 AA; keine automatisierten `critical`/`serious` Befunde; kritische Flows vollständig per Tastatur |
| Public Performance | LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1 im definierten mobilen Testprofil |
| Interaktionsfeedback | sichtbare Reaktion auf lokale Eingabe ≤ 100 ms; längere Serveraktion zeigt unmittelbar Fortschritt |
| API | p95 der Golden-Data-Kernreads ≤ 500 ms im definierten PoC-Profil; Budgetausnahmen werden begründet |
| Responsive | kein horizontaler Seiten-Scroll bei 320–1440 px; Touch-Ziele mindestens 44 × 44 CSS-Pixel |
| Formulare | kein Verlust valider Eingaben bei behebbaren Server-/Validierungsfehlern |
| Browser | aktuelle gepinnte Chromium-, Firefox- und WebKit-Versionen |
| Bootstrap | frischer Entwickler erreicht mit dokumentierten Befehlen ohne internes Wissen den laufenden Golden-Stack |
| Diagnose | jeder fehlgeschlagene externe Effekt ist über Request-/Job-ID auffindbar und sicher wiederholbar |

Die Performancewerte werden gegen ein dokumentiertes CPU-/RAM-/Netzprofil
gemessen. Eine schnellere Entwicklermaschine darf schlechte Queries oder
unnötig große Browserbundles nicht kaschieren.

## 4. Meilensteine und Tasks

Die IDs sind stabil und sollen in Commits, Issues und Testnamen verwendet
werden. Innerhalb eines Meilensteins darf parallel gearbeitet werden, wenn
die angegebenen Abhängigkeiten erfüllt sind.

---

## M0 – Entscheidungen, Baseline und reproduzierbare Toolchain

### [x] POC-000 Scope-Baseline und Traceability festschreiben

Abhängigkeiten: keine

Akzeptanzkriterien:

- [x] Enthaltene und ausgeschlossene PoC-Funktionen entsprechen Kapitel 10.1
      und 10.2 des Konzepts.
- [x] Jede harte Vorgabe aus Kapitel 10.3 ist mindestens einem Task und Test
      in diesem Plan zugeordnet.
- [x] Offene Rechts-/Rechnungsfragen besitzen Owner, Entscheidungsdatum und
      blockieren keine stillschweigend angenommene Implementierung.
- [x] Architekturentscheidungen werden als kurze ADRs versioniert.

Tests/Nachweise:

- [x] Automatischer Traceability-Check meldet unbekannte oder doppelte
      Requirement-IDs.
- [x] Manueller Scope-Review mit Produktverantwortlichem ist protokolliert.

### [x] POC-001 Abhängigkeiten und Images exakt pinnen

Abhängigkeiten: POC-000

Akzeptanzkriterien:

- [x] Python-Version steht in einer Toolchain-Datei; alle Python-Pakete stehen
      mit exakter Version und Hash im Lockfile.
- [x] Bun/Node-Version und alle Frontend-Pakete sind exakt gelockt.
- [x] Twenty, PostgreSQL, Redis, RustFS, Mailpit, Reverse Proxy und alle
      Hilfscontainer sind mit Version und Image-Digest erfasst.
- [x] Typst-Version, Browser-Versionen und Playwright-Browserartefakte sind
      reproduzierbar gepinnt.
- [x] Eine maschinenlesbare `external-systems.lock` dokumentiert Image,
      Digest, Lizenz, Upstream-Link und geprüftes Upgrade-Datum.
- [x] Renovierungsautomation darf nur explizite Update-PRs erzeugen; kein
      Build lädt stillschweigend eine neue Version.

Tests/Nachweise:

- [x] CI lehnt `latest`, ungebundene Image-Tags und nicht exakt gelockte
      Direktabhängigkeiten ab.
- [x] Zwei frische Checkouts erzeugen dieselben Dependency- und Image-Locks.
- [x] SBOMs für Python, Frontend und Container werden als Artefakte erzeugt.

Nachweis:
[POC-001 – exakte Pins, Reproduzierbarkeit und SBOMs](proofs/POC-001.md).

### [x] POC-002 Monorepo, Befehle und lokale Developer Experience aufsetzen

Abhängigkeiten: POC-001

Akzeptanzkriterien:

- [x] Repository-Schnitt aus Kapitel 2 ist angelegt.
- [x] Ein einziger dokumentierter Bootstrap-Befehl installiert Toolchains,
      ohne globale Projektpakete vorauszusetzen.
- [x] Einheitliche Befehle existieren für `bootstrap`, `dev`, `check`,
      `test-unit`, `test-integration`, `test-e2e`, `seed`, `reset` und
      `doctor`.
- [x] `doctor` erklärt fehlende Voraussetzungen und konkrete Korrekturen.
- [x] Editor-Konfiguration, Typprüfung, Formatierung und Debug-Profile sind
      dokumentiert.
- [x] Lokale Secrets entstehen aus einer Vorlage und werden nie committed.

Tests/Nachweise:

- [x] Frischer Checkout auf einer sauberen Entwicklungsmaschine besteht
      `bootstrap` und `doctor`.
- [x] `check` verändert keine Dateien und endet bei einem Dirty Diff mit
      verständlicher Diagnose.

Nachweis:
[POC-002 – Monorepo und Docker-basierte DX](proofs/POC-002.md).

### [ ] POC-003 CI-Pipeline und Beweisartefakte einrichten

Abhängigkeiten: POC-002

Akzeptanzkriterien:

- [ ] CI besitzt getrennte, nachvollziehbare Jobs für Lint/Types, Unit,
      Integration, Contract, E2E, Security und Build.
- [ ] Dienste werden aus denselben Compose-Definitionen wie lokal gestartet.
- [ ] Fehlgeschlagene Tests veröffentlichen Logs, Browser-Traces,
      Screenshots, Mail- und Storage-Diagnosen ohne Secrets.
- [ ] Migrationen und Golden-Data-Seeding laufen in CI aus einer leeren
      Umgebung.
- [ ] CI verbietet Mock-/Fake-Bibliotheken, HTTP-Fixtures und
      Testimplementierungen produktiver I/O-Ports; begründete reine
      UI-Testhelfer dürfen keine Serverantwort oder Fachentscheidung ersetzen.
- [ ] Branchschutz verlangt alle definierten Gates.

Tests/Nachweise:

- [ ] Ein absichtlich fehlschlagender Probe-Branch beweist die Artefakte und
      wird danach verworfen.
- [ ] Ein kompletter grüner Lauf aus leerem Cache ist dokumentiert.

---

## M1 – Reale lokale Plattform und Golden Dataset

### [x] POC-010 Docker-Compose-Corestack bereitstellen

Abhängigkeiten: POC-001, POC-002

Akzeptanzkriterien:

- [x] Standardstart enthält Reverse Proxy, FastAPI, Worker, Core-PostgreSQL,
      Web, PWA, Public Web, Twenty Server/Worker/PostgreSQL/Redis und RustFS.
- [x] Mailpit läuft nur im lokalen `dev-mail`-Profil.
- [x] Mailing und Observability bleiben optionale Profile.
- [x] Nur der Reverse Proxy ist regulär öffentlich erreichbar.
- [x] Alle Dienste besitzen aussagekräftige Health- und Readiness-Checks.
- [x] Volumes, Netzwerke, Rollen und Datenbanken sind fachlich getrennt.

Tests/Nachweise:

- [x] Integrationstest startet den Stack aus leeren Volumes und wartet auf
      echte Readiness statt auf feste Sleeps.
- [x] Netzwerkprüfung beweist, dass Datenbanken, RustFS-Admin und interne APIs
      nicht am öffentlichen Interface lauschen.
- [x] Neustart aller Container erhält persistente Golden Data.

Nachweis:
[POC-010 – Docker-Compose-Corestack](proofs/POC-010.md).

### [x] POC-011 Golden Dataset v1 spezifizieren und versionieren

Abhängigkeiten: POC-000

Akzeptanzkriterien:

- [x] Alle Entitäten aus Kapitel 3.1 besitzen stabile IDs und synthetische
      Inhalte.
- [x] Erwartete Sichtbarkeit, Summen, Status, Matches und Feed-Einträge sind
      maschinenlesbar hinterlegt.
- [x] Eine README erklärt jede Persona und jeden Konfliktfall.
- [x] Golden Data enthält keine realen Mitglieder-, Firmen- oder
      Kontaktdaten.
- [x] Dataset-Version und Schema-Version werden gemeinsam geprüft.

Tests/Nachweise:

- [x] Schema- und Referenzintegrität des Datasets werden ohne laufende App
      validiert.
- [x] Erwartete Rechnungsbeträge, Boxen-/Stückzahlen und Zuweisungsmengen
      werden aus den Daten reproduzierbar berechnet.

Nachweis:
[POC-011 – Golden Dataset v1](proofs/POC-011.md).

### [x] POC-012 Reset-, Seed- und Snapshot-Werkzeuge bauen

Abhängigkeiten: POC-010, POC-011

Akzeptanzkriterien:

- [x] Ein Befehl setzt Core-PostgreSQL, Twenty, RustFS und Mailpit auf Golden
      Data v1 zurück.
- [x] Twenty-Daten werden über unterstützte Metadata-/Data-APIs aufgebaut,
      nicht durch Änderungen an internen Twenty-Tabellen.
- [x] RustFS enthält reale Golden-PDFs mit gespeicherten SHA-256-Prüfsummen.
- [x] Seed-Vorgang ist wiederholbar und erzeugt keine Duplikate.
- [x] Reset verweigert sich außerhalb eindeutig markierter Testumgebungen.

Tests/Nachweise:

- [x] Zwei aufeinanderfolgende Seeds liefern identische fachliche Counts und
      IDs.
- [x] Nach absichtlicher Datenveränderung stellt Reset exakt den erwarteten
      Snapshot wieder her.
- [x] Sicherheitsprüfung beweist, dass ein Produktions-DSN abgewiesen wird.

Nachweis:
[POC-012 – Reset, Seed und Snapshot](proofs/POC-012.md).

### [ ] POC-013 Testkit für echte Systeme bereitstellen

Abhängigkeiten: POC-010, POC-012

Akzeptanzkriterien:

- [ ] Testkit besitzt echte Clients für LeonAid API, Twenty, RustFS und
      Mailpit sowie read-only SQL-Prüfhelfer.
- [ ] Persona-Sitzungen werden über den echten Login erzeugt.
- [ ] Polling verwendet fachliche Readiness-/Jobzustände mit Deadline statt
      pauschaler Sleeps.
- [ ] Fehlerausgaben nennen Request-ID, Persona, Aktion und betroffenen
      Golden-Datensatz.

Tests/Nachweise:

- [ ] Smoke-Test liest denselben Golden-Sponsor über UI/API und verifiziert
      dessen Twenty-ID.
- [ ] Smoke-Test versendet eine reale Mail an Mailpit und liest sie über
      dessen API zurück.
- [ ] Smoke-Test schreibt und liest ein echtes RustFS-Objekt mit Hashprüfung.

---

## M2 – Python/FastAPI-Kern, Datenbank und Verträge

### [x] POC-020 Python-Anwendung und Schichtengrenzen aufsetzen

Abhängigkeiten: POC-002

Akzeptanzkriterien:

- [x] FastAPI ist ausschließlich HTTP-Adapter vor Application Services.
- [x] Domain und Application Layer importieren weder FastAPI noch konkrete
      PostgreSQL-, Twenty-, RustFS- oder SMTP-Clients.
- [x] Konfiguration ist typisiert, secretsicher und beim Start validiert.
- [x] Einheitliches Fehlerformat enthält stabilen Fehlercode und Request-ID.
- [x] `/health/live`, `/health/ready` und versionierte API-Basis existieren.

Tests/Nachweise:

- [x] Architekturtest verhindert unerlaubte Import-Richtungen.
- [x] Unit-Tests prüfen Konfigurations- und Domain-Invarianten mit echten
      Objekten.
- [x] Integrationstest startet den realen ASGI-Server gegen PostgreSQL.

Nachweis:
[POC-020 – Python-Core und Schichtengrenzen](proofs/POC-020.md).

### [x] POC-021 Relationales Core-Schema und Migrationen implementieren

Abhängigkeiten: POC-020, POC-011

Akzeptanzkriterien:

- [x] Tabellen decken das Kernmodell aus
      [Kapitel 4.2](../produkt-und-architekturvorschlag.md#42-empfohlenes-kernmodell)
      für den PoC ab.
- [x] Geldwerte verwenden exakte Dezimal-/Minor-Unit-Semantik; Zeitpunkte
      sind timezone-aware.
- [x] Fremdschlüssel, Unique Constraints und Check Constraints sichern
      zentrale Invarianten.
- [x] Migrationen sind vorwärts ausführbar; destruktive Änderungen benötigen
      explizite Datenmigration und Backup.
- [x] Audit- und Outbox-Daten sind transaktional mit Fachänderungen.

Tests/Nachweise:

- [x] Migrationstest baut eine leere Datenbank bis Head auf.
- [x] Upgrade-Test migriert den vorherigen Schema-Snapshot mit Daten.
- [x] Integrationstests beweisen Constraints durch reale fehlgeschlagene
      Inserts/Transitions.

Nachweis:
[POC-021 – Core-Schema und Migrationen](proofs/POC-021.md).

### [x] POC-022 Unit-of-Work, Repositories und transaktionale Outbox bauen

Abhängigkeiten: POC-021

Akzeptanzkriterien:

- [x] Application Service führt Fachänderung, AuditEvent und OutboxEvent in
      einer Transaktion aus.
- [x] Worker beanspruchen Jobs konkurrierend sicher.
- [x] Retry, Backoff, Dead-Letter-Zustand und manueller Wiederanlauf sind
      sichtbar.
- [x] Jeder externe Effekt besitzt einen stabilen Idempotenzschlüssel.

Tests/Nachweise:

- [x] Echter PostgreSQL-Test beendet den Prozess zwischen Commit und Versand
      und beweist spätere genau-einmalige fachliche Wirkung.
- [x] Zwei reale Worker verarbeiten denselben Job nicht doppelt.
- [x] Wiederholter Job erzeugt weder doppelte Bestellung noch Rechnung oder
      Mail.

Nachweis:
[POC-022 – Unit of Work und transaktionale Outbox](proofs/POC-022.md).

### [x] POC-023 OpenAPI- und TypeScript-Client-Pipeline etablieren

Abhängigkeiten: POC-020

Akzeptanzkriterien:

- [x] API-Operationen besitzen stabile IDs, Schemas, Fehlercodes und
      Beispiele aus Golden Data.
- [x] TypeScript-Client wird deterministisch aus dem OpenAPI-Dokument erzeugt.
- [x] Frontends importieren Transporttypen ausschließlich aus `api-client`.
- [x] Breaking Changes werden in CI sichtbar und benötigen eine bewusste
      Freigabe.

Tests/Nachweise:

- [x] Regeneration hinterlässt bei unverändertem API-Vertrag keinen Diff.
- [x] Contracttest führt den generierten Client gegen den realen FastAPI-
      Prozess aus.
- [x] Fehlerantworten werden im Client typisiert und UI-tauglich abgebildet.

Nachweis:
[POC-023 – OpenAPI und TypeScript-Client](proofs/POC-023.md).

---

## M3 – Twenty-Integration und CRM-Vertrag

### [x] POC-030 Twenty-Schema reproduzierbar provisionieren

Abhängigkeiten: POC-010, POC-012

Akzeptanzkriterien:

- [x] Benötigte Custom Objects, Fields, Relations, Views und Rollen sind
      deklarativ beschrieben.
- [x] Provisionierung nutzt die gepinnte Twenty Metadata API.
- [x] Integrations-Key besitzt nur benötigte Objekt-, Feld- und Aktionsrechte.
- [x] Schemaänderungen sind idempotent und liefern verständliche Drifts.
- [x] Verwendete Twenty-Capabilities und Limits sind dokumentiert.

Tests/Nachweise:

- [x] Contracttest provisioniert eine leere Twenty-Instanz zweimal ohne
      Duplikate.
- [x] Drift-Test verändert ein Feld real und erkennt die Abweichung.
- [x] Negativtest beweist, dass der Integrations-Key administrative und
      fachfremde Objekte nicht nutzen kann.

Nachweis:
[POC-030 – deklaratives Twenty-Schema und Least Privilege](proofs/POC-030.md).

### [x] POC-031 Twenty Gateway und fachliche CRM-Ports implementieren

Abhängigkeiten: POC-023, POC-030

Akzeptanzkriterien:

- [x] Gateway kapselt Suche, Lesen, Anlegen und kontrolliertes Aktualisieren
      von Company/Person.
- [x] Kein UI- oder Domain-Modul kennt Twenty-Feld-IDs.
- [x] Timeouts, Rate Limits, Pagination, Batches und Fehler werden explizit
      behandelt.
- [x] LeonAid-/Twenty-IDs und Sync-Status sind nachvollziehbar.
- [x] Requests besitzen Korrelation und geben keine Secrets aus.

Tests/Nachweise:

- [x] Contracttests laufen gegen die echte gepinnte Twenty-Instanz.
- [x] Paginationstest legt mehr Datensätze als eine Seite real an und findet
      alle genau einmal.
- [x] Reales Stoppen von Twenty erzeugt einen sichtbaren, wiederholbaren
      Fehler statt Datenverlust.

Nachweis:
[POC-031 – Twenty Gateway und CRM-Port](proofs/POC-031.md).

### [ ] POC-032 Matching für Company und Person implementieren

Abhängigkeiten: POC-031

Akzeptanzkriterien:

- [ ] Firma wird primär über normalisierten Firmennamen gematcht.
- [ ] Ohne Firma wird über normalisierten Vor- und Nachnamen gematcht.
- [ ] Ergebnis unterscheidet `no_match`, `single_match` und
      `ambiguous_match`.
- [ ] Zusatzdaten werden angezeigt, überschreiben aber nicht stillschweigend
      den PoC-Matchschlüssel.
- [ ] Neuanlage und Wiederverwendung werden auditiert.

Tests/Nachweise:

- [ ] Unit-Tests decken Unicode, Whitespace, Groß-/Kleinschreibung und
      Golden-Konflikte ab.
- [ ] Integrationstest sucht und erzeugt reale Twenty-Companies/People.
- [ ] E2E zeigt vor Mitzuordnung die Namen vorhandener Akquisiteure und
      verlangt explizite Bestätigung.

### [ ] POC-033 Einmaligen Excel-/CSV-Importpfad nachweisen

Abhängigkeiten: POC-030, POC-031

Akzeptanzkriterien:

- [ ] Mappingvorlage, Pflichtfelder, Normalisierung und Fehlerreport sind
      dokumentiert.
- [ ] Import kann durch Coding-Agent/Script reproduzierbar vorbereitet und
      über unterstützte Twenty-Import- oder API-Wege ausgeführt werden.
- [ ] Dry Run zeigt neue, aktualisierte, konfliktbehaftete und verworfene
      Zeilen.
- [ ] Wiederholung erzeugt keine Duplikate.

Tests/Nachweise:

- [ ] Golden-Arbeitsmappe wird real importiert.
- [ ] Zweiter Import aktualisiert einen vorgesehenen Datensatz und dupliziert
      keinen anderen.
- [ ] Fehlerhafte Zeilen erzeugen einen verständlichen, zeilenbezogenen
      Bericht.

---

## M4 – Identität, Einladungen, Sitzungen und Autorisierung

### [ ] POC-040 UserAccount, Rollen und ActionMembership implementieren

Abhängigkeiten: POC-021

Akzeptanzkriterien:

- [ ] Globale Rollen und aktionsbezogene Rollen sind getrennt.
- [ ] Ein Account kann in mehreren Aktionen unterschiedliche Rollen besitzen.
- [ ] Statuswechsel `invited`, `active`, `suspended`, `archived` sind
      serverseitig validiert.
- [ ] Benutzer kann seine Login-E-Mail im PoC nicht selbst ändern.
- [ ] Rollen-/Statusänderungen erzeugen AuditEvents.

Tests/Nachweise:

- [ ] Unit-Tests prüfen erlaubte und verbotene Statuswechsel.
- [ ] Integrationstest entzieht einer realen Sitzung nach Suspendierung
      unmittelbar den Zugriff.
- [ ] E2E zeigt nur für die Persona erlaubte Navigation und Aktionen.

### [ ] POC-041 Einladung mit Magic Link und sechsstelligen Code bauen

Abhängigkeiten: POC-040, POC-022

Akzeptanzkriterien:

- [ ] Charity-Admin kann ausschließlich in selbst verwaltete Aktionen
      einladen; System-Admin entsprechend globaler Rechte.
- [ ] Einladung enthält unveränderlichen Snapshot von E-Mail, Aktion, Rolle
      und Einladendem.
- [ ] Annahme aktiviert Account und vorgesehene ActionMembership atomar.
- [ ] Link und Code sind kurzlebig, einmal verwendbar und gespeichert nur in
      geeigneter gehashter Form.
- [ ] Anfrage verrät nicht, ob ein Account existiert.
- [ ] E-Mail wird über Outbox und realen SMTP-Pfad versendet.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Codeformat, Ablaufregeln und Einladungstransitionen.
- [ ] Integrationstest liest die echte Einladung aus Mailpit und nimmt sie
      über Link sowie in einem zweiten Fall über Code an.
- [ ] Wiederverwendung, Ablauf und widerrufene Einladung werden real
      abgewiesen.
- [ ] E2E beweist, dass fremdverwaltete Aktionen nicht auswählbar und direkte
      Requests verboten sind.

### [ ] POC-042 90-Tage-Sitzung, Widerruf und Fresh Login umsetzen

Abhängigkeiten: POC-041

Akzeptanzkriterien:

- [ ] Serverseitige, widerrufbare Sitzung besitzt absolutes Ablaufdatum,
      letzten Zugriff und Zeitpunkt frischer Anmeldung.
- [ ] Browser erhält ausschließlich sichere `HttpOnly`-/`Secure`-Cookies mit
      passender SameSite-Strategie.
- [ ] Normale Akquise funktioniert innerhalb der 90-Tage-Sitzung.
- [ ] Admin-, Rechnungsfreigabe- und andere sensible Aktionen verlangen eine
      konfiguriert frische Anmeldung.
- [ ] Logout und administrativer Widerruf wirken sofort.

Tests/Nachweise:

- [ ] Integrationstests verwenden reale Sitzungsdatensätze mit expliziten
      Ablaufzeitpunkten.
- [ ] E2E durchläuft Login, normalen Zugriff, Fresh-Login-Challenge und
      erfolgreiche Rechnungsfreigabe.
- [ ] Gestohlener alter Cookie-Wert ist nach Widerruf wirkungslos.

### [ ] POC-043 Zentralen Policy Layer und Row-Level-Regeln umsetzen

Abhängigkeiten: POC-040, POC-031

Akzeptanzkriterien:

- [ ] Jede lesende und schreibende Operation prüft globale Rolle,
      ActionMembership und gegebenenfalls AcquisitionAssignment.
- [ ] Akquisiteure erhalten keinen direkten Twenty-Login oder API-Key.
- [ ] Listen, Suche, Counts, Exporte, Aktivitäten und Dokumente verwenden
      dieselben Policies.
- [ ] Clientseitige User-, Rollen- oder Assignee-IDs erweitern niemals
      Rechte.
- [ ] Verborgene Datensätze werden nicht durch Fehlertexte oder Counts
      offengelegt.

Tests/Nachweise:

- [ ] Vollständige Negativsuite aus
      [Kapitel 15.5](../produkt-und-architekturvorschlag.md#155-poc-nachweise)
      läuft gegen PostgreSQL und Twenty.
- [ ] A sieht exklusive Daten von B weder per ID noch Suche, Liste,
      Aktivität oder Export.
- [ ] Gemeinsame Zuweisung ist für A und B sichtbar.
- [ ] Entfernen einer Membership/Assignment entzieht Zugriff ohne
      Neuanmeldung.

---

## M5 – Charity-Aktionskern und Admin-Arbeitsplatz

### [ ] POC-050 CharityAction-Lifecycle, Capabilities und Beneficiaries bauen

Abhängigkeiten: POC-021, POC-043

Akzeptanzkriterien:

- [ ] Lifecycle `draft → scheduled → active → completed → archived` ist
      serverseitig abgesichert.
- [ ] Aktionskern enthält keine Krapfentaxi-spezifischen Felder.
- [ ] PoC-Capabilities `acquisition`, `offerings`, `ordering`, `invoicing`
      sind typisiert aktivierbar.
- [ ] Eine Aktion besitzt ein bis viele Beneficiaries.
- [ ] Zielwert, Ist-Wert und Einheit können manuell gepflegt werden.
- [ ] Änderungen werden auditiert.

Tests/Nachweise:

- [ ] Unit-Tests prüfen alle erlaubten/verbotenen Transitionen und
      Capability-Invarianten.
- [ ] Integrationstest persistiert mehrere Beneficiaries und Zielwerte.
- [ ] E2E erstellt eine Aktion vollständig ohne Datenbankzugriff.

### [ ] POC-051 Versionierte Aktionstemplates implementieren

Abhängigkeiten: POC-050

Akzeptanzkriterien:

- [ ] Templates für Krapfentaxi und eine technisch neutrale leere Aktion
      existieren.
- [ ] Krapfentaxi setzt PoC-Capabilities, Angebote und Formularkonfiguration.
- [ ] Aktion erhält einen Snapshot; spätere Templateänderung verändert sie
      nicht rückwirkend.
- [ ] Vorjahreskopie übernimmt Konfiguration, aber keine operativen
      Bestellungen, Teilnehmer, Rechnungen oder Nummern.
- [ ] Lions-Open- und Weihnachtsmarkt-Templates bleiben ausdrücklich
      nachgelagert und erzeugen keine spekulativen PoC-Felder oder Module.

Tests/Nachweise:

- [ ] Unit-Test prüft Snapshot- und Kopierregeln.
- [ ] Integrationstest ändert eine Template-Version und beweist unveränderte
      historische Aktionen.
- [ ] Architekturtest stellt sicher, dass Krapfentaxi-spezifische Daten in
      typisierten Capability-Modulen und nicht in `CharityAction` liegen.

### [ ] POC-052 Charity-Admin-Aktionsverwaltung als hochwertige UI bauen

Abhängigkeiten: POC-050, POC-051, POC-023

Akzeptanzkriterien:

- [ ] Admin kann Aktion, Zeitraum, Ziel, Begünstigte, Verantwortliche,
      Publikationsdaten und Capabilities bedienen.
- [ ] Formular ist in verständliche Schritte gegliedert und bewahrt Eingaben
      bei behebbaren Fehlern.
- [ ] Konflikte und irreversible Übergänge werden vor Bestätigung erklärt.
- [ ] Lade-, Leer-, Fehler- und Erfolgsmeldungen sind barrierearm.
- [ ] Responsive Sidebar und mobile Navigation entsprechen Kapitel 6.6.

Tests/Nachweise:

- [ ] Componenttests verwenden den real generierten API-Client gegen den
      laufenden Core, keinen Request-Mock.
- [ ] E2E erstellt, plant, aktiviert und archiviert eine Golden-Aktion.
- [ ] Accessibility-Scan und manueller Tastaturpfad sind ohne kritische
      Befunde.

---

## M6 – Akquise und PWA

### [ ] POC-060 AcquisitionAssignment und Historie implementieren

Abhängigkeiten: POC-032, POC-043, POC-050

Akzeptanzkriterien:

- [ ] Eindeutigkeit gilt für Aktion + CRM-Partei + Akquisiteur.
- [ ] Mehrere Akquisiteure dürfen derselben Partei zugeordnet sein.
- [ ] Zuweisung, Übergabe, Status, Priorität, nächste Aktion und Fälligkeit
      sind historisiert.
- [ ] Proaktive Admin-Zuweisung ist möglich, aber nicht Voraussetzung für
      Neuanlage durch Akquisiteur.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Mehrfachzuordnung und Historienregeln.
- [ ] Integrationstest erzeugt konkurrierend dieselbe Zuweisung und erhält
      genau einen Datensatz.
- [ ] E2E zeigt gemeinsame Zuordnung samt Namen und verhindert keine
      bestätigte Mitzuordnung.

### [ ] POC-061 AcquisitionActivity und Wiedervorlage implementieren

Abhängigkeiten: POC-060

Akzeptanzkriterien:

- [ ] Akquisiteur erfasst Kanal, Ergebnis, Notiz und nächste Aktion.
- [ ] Historie wird ergänzt und nicht frei überschrieben.
- [ ] Überfällige und heutige Wiedervorlagen sind verständlich priorisiert.
- [ ] Datenschutzgerechte Längen- und Inhaltsgrenzen sind definiert.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Status-/Fälligkeitsableitung mit Golden-Zeitpunkten.
- [ ] Integrationstest persistiert Aktivität und AuditEvent atomar.
- [ ] E2E erfasst eine Aktivität und findet sie nach Reload in richtiger
      Reihenfolge.

### [ ] POC-062 PWA-Shell, Aktionen und Sponsorlisten umsetzen

Abhängigkeiten: POC-023, POC-043, POC-060

Akzeptanzkriterien:

- [ ] Installierbare PWA besitzt Manifest, Icons, Offline-Hinweisseite und
      Update-Hinweis; Offline-Schreibsync bleibt ausgeschlossen.
- [ ] Nutzer sieht eigene aktive Aktionen und je Aktion erlaubte Sponsoren.
- [ ] Sponsorzeile zeigt Status, nächste Aktion, Kontaktmöglichkeiten und
      Mitzuordnung ohne visuelle Überladung.
- [ ] Touch-Ziele, Fokus, Kontrast und Textskalierung erfüllen die
      festgelegten Qualitätsbudgets.
- [ ] `tel:` und E-Mail-Aktion funktionieren auf geeigneten Geräten.

Tests/Nachweise:

- [ ] E2E läuft bei 390 px, 768 px und 1440 px sowie in drei Browser-Engines.
- [ ] PWA-Audit prüft Manifest und Installierbarkeit.
- [ ] Golden-Persona A sieht nicht die exklusiven Datensätze von B.
- [ ] Visuelle Regression deckt Liste, Leerzustand, Fehler und geteilte
      Zuordnung ab.

### [ ] POC-063 Sponsor-Neuanlage und Konflikt-UX bauen

Abhängigkeiten: POC-032, POC-060, POC-062

Akzeptanzkriterien:

- [ ] Formular verlangt nur minimale Firmen-/Kontaktdaten.
- [ ] Während der Eingabe oder vor Submit erfolgt serverseitiges Matching.
- [ ] Treffer zeigt unterscheidbare Firmendaten und vorhandene Akquisiteure.
- [ ] Nutzer kann abbrechen oder explizit „Trotzdem ebenfalls zuordnen“.
- [ ] Kein Treffer erzeugt Company/Person in Twenty und eigene Assignment in
      einer nachvollziehbaren Operation.
- [ ] Doppelklick oder Retry erzeugt keine Duplikate.

Tests/Nachweise:

- [ ] E2E deckt No-Match, Single-Match, Ambiguous-Match, Abbruch und
      bestätigte Mitzuordnung ab.
- [ ] Integrationstest wiederholt dieselbe idempotente Mutation real.
- [ ] Twenty wird anschließend direkt geprüft: exakt erwartete Company,
      Person und Relationen existieren.

---

## M7 – Public Web, Alias und öffentliche Bestellung

### [ ] POC-070 PublicActionAlias und Archivregeln implementieren

Abhängigkeiten: POC-050

Akzeptanzkriterien:

- [ ] Alias ist installationsweit eindeutig und verweist auf höchstens eine
      veröffentlichte Aktion.
- [ ] Aliaswechsel ist atomar.
- [ ] Archiv-Slug ist unveränderlich und wird nie wiederverwendet.
- [ ] Ohne aktive Aktion liefert der Alias eine hilfreiche neutrale Seite.
- [ ] Archivierte Aktion ist lesbar, aber nicht beschreibbar.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Alias-/Slug-Invarianten.
- [ ] Integrationstest schaltet `/krapfentaxi` atomar auf einen Folgejahrgang.
- [ ] E2E beweist unveränderte Archiv-URL und deaktivierte Formulare.
- [ ] Direkter API-Request gegen Archiv-Aktion wird abgewiesen.

### [ ] POC-071 Astro-Aktionsseite mit hochwertiger Public UX bauen

Abhängigkeiten: POC-023, POC-070

Akzeptanzkriterien:

- [ ] Seite zeigt Zweck, Zeitraum, Begünstigte, Ziel, Angebote und
      Datenschutzinformation.
- [ ] Inhalt funktioniert ohne unnötiges Client-JavaScript.
- [ ] Astro Actions übernehmen nur Transportvalidierung, Spam-Schutz und
      Core-Weiterleitung; keine Fachlogik.
- [ ] Metadaten, Canonical URL, Social Preview, Fehler- und Archivzustand
      sind gepflegt.
- [ ] Mobile Performance und Barrierefreiheit erfüllen die Budgets.

Tests/Nachweise:

- [ ] Unit-Test der Domain-Regeln läuft unabhängig von Astro.
- [ ] Integrationstest ruft Core einmal direkt und einmal über Astro auf und
      erhält dieselbe fachliche Entscheidung.
- [ ] E2E prüft aktive, inaktive und archivierte Golden-Seite in drei
      Browser-Engines.
- [ ] Accessibility- und Performance-Bericht werden archiviert.

### [ ] POC-072 Öffentliches Bestellformular implementieren

Abhängigkeiten: POC-032, POC-071, POC-080

Akzeptanzkriterien:

- [ ] Formular erhebt minimale Firmen-/Kontaktdaten, Liefer-/Rechnungsdaten,
      Positionen, Mengen und erforderliche Einwilligungen.
- [ ] Core prüft Publikations-/Bestellfenster, Angebot, Preis,
      Verfügbarkeit, Idempotenz und Spam-/Rate-Limit-Signale erneut.
- [ ] Bestehende CRM-Partei wird wiederverwendet; sonst kontrolliert angelegt.
- [ ] Vorhandene Assignments bleiben unverändert.
- [ ] Erfolg zeigt eindeutige Bestellreferenz und weiteres Vorgehen.
- [ ] Validierungsfehler erhalten Eingaben und fokussieren das erste Problem.

Tests/Nachweise:

- [ ] E2E bestellt als neue Firma, bestehende Firma und Person ohne Firma.
- [ ] Doppelter Submit erzeugt genau ein Commitment.
- [ ] Manipulierter Preis, inaktives Angebot und archivierte Aktion werden
      serverseitig abgewiesen.
- [ ] Zugeordnete Akquisiteure erhalten reale ActivityEvents.

---

## M8 – Angebote, Bestellungen und Aktivitätsfeed

### [ ] POC-080 Offering, Mengen und Commitment-Aggregat implementieren

Abhängigkeiten: POC-021, POC-050

Akzeptanzkriterien:

- [ ] Offering besitzt Name, Zeitraum, Preis, Währung, Status und erlaubte
      Mengeneinheiten.
- [ ] Krapfenbox kann nachvollziehbar in Boxen und Stück ausgedrückt werden.
- [ ] Commitment unterscheidet Quellen `acquisition`, `public_form`, `admin`.
- [ ] Besteller, Rechnungsempfänger und Positionen werden fachlich getrennt.
- [ ] Preise werden serverseitig aus dem aktiven Offering übernommen.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Geld, Rundung, Box-/Stückumrechnung und Statusregeln.
- [ ] Integrationstest persistiert alle Golden-Bestellquellen.
- [ ] Manipulierte Clientbeträge verändern den berechneten Gesamtbetrag nicht.

### [ ] POC-081 Interne Bestell-/Zusagenerfassung bauen

Abhängigkeiten: POC-062, POC-080

Akzeptanzkriterien:

- [ ] Akquisiteur kann aus dem Sponsor-Kontext eine Bestellung/Zusage
      erfassen.
- [ ] Formular zeigt Angebot, Einheit, Menge, Preis und Rechnungsempfänger
      verständlich.
- [ ] Entwurf und prüfbereite Bestellung sind visuell unterscheidbar.
- [ ] Wiederholung und konkurrierender Submit sind idempotent.

Tests/Nachweise:

- [ ] E2E erfasst eine Bestellung als Akquisiteur und prüft sie als Admin.
- [ ] Integrationstest erzeugt bei parallelem Submit genau ein Commitment.
- [ ] Golden-Gesamtsummen stimmen in API, UI und Datenbank überein.

### [ ] POC-082 ActivityEvent und „Neues/Aktivitäten“ umsetzen

Abhängigkeiten: POC-060, POC-072, POC-081

Akzeptanzkriterien:

- [ ] Öffentliche Bestellung erzeugt Ereignis für alle bereits zugeordneten
      Akquisiteure.
- [ ] Unzugeordnete Bestellung erscheint für Charity-Admins.
- [ ] Feed unterstützt gelesen/ungelesen ohne Ereignisse zu löschen.
- [ ] Ereignisse referenzieren Aktion und CRM-Partei und erklären die
      nächste sinnvolle Aktion.

Tests/Nachweise:

- [ ] Integrationstest erzeugt Events für exklusiv, gemeinsam und
      unzugeordnet.
- [ ] E2E prüft Feed für beide Akquisiteure und Charity-Admin.
- [ ] Row-Level-Negativtest verhindert fremde Feed-Einträge.

---

## M9 – ERP-light, Dokumente, Versand und Zahlung

### [ ] POC-090 Rechnungsmodell, Nummernkreis und Freigabe implementieren

Abhängigkeiten: POC-042, POC-080

Akzeptanzkriterien:

- [ ] Rechtlicher Träger, Pflichtangaben, Steuerfall und Nummernkreis sind als
      ADR/Fachentscheidung dokumentiert.
- [ ] Rechnung entsteht nur aus prüfbereitem Commitment nach Fresh Login.
- [ ] Nummer wird transaktional eindeutig und lücken nachvollziehbar
      vergeben.
- [ ] Empfänger, Positionen, Preise und rechtliche Texte werden als
      unveränderlicher Snapshot gespeichert.
- [ ] Storno/Korrektur ersetzt kein ausgestelltes Dokument.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Statusautomat, Beträge, Fälligkeit und Snapshot.
- [ ] Integrationstest gibt konkurrierend frei und erzeugt genau eine
      Rechnung/Nummer.
- [ ] Änderung der Twenty-Adresse lässt die ausgestellte Rechnung
      unverändert.
- [ ] E2E verlangt vor Freigabe eine reale frische Anmeldung.

### [ ] POC-091 Typst-Rechnungsvorlage und realen Renderer bauen

Abhängigkeiten: POC-090, POC-001

Akzeptanzkriterien:

- [ ] Versionierte Typst-Vorlage rendert alle Golden-Rechnungsfälle.
- [ ] Rendering ist deterministisch bei identischen Snapshots und
      Render-Versionen.
- [ ] Layout behandelt lange Namen, Adressen, mehrere Positionen und
      Seitenumbrüche.
- [ ] PDF enthält korrekte Metadaten, eingebettete Schriften und keine
      externen Laufzeitressourcen.

Tests/Nachweise:

- [ ] Integrationstest startet den realen gepinnten Typst-Renderer.
- [ ] Textinhalt und Beträge werden aus dem PDF extrahiert und verglichen.
- [ ] Gerenderte Seiten werden visuell gegen freigegebene Golden-Bilder
      geprüft.
- [ ] PDFs öffnen in mindestens zwei realen Viewern/Engines.

### [ ] POC-092 S3-Storage-Port und RustFS-Adapter implementieren

Abhängigkeiten: POC-010, POC-022, POC-091

Akzeptanzkriterien:

- [ ] Providerneutraler Port kapselt Put, Head, geschützten Get/Download,
      Version und kontrollierte Löschung.
- [ ] `GeneratedDocument` speichert Bucket, Object Key, Version-ID, Größe,
      SHA-256, Render-Version und Fachreferenzen.
- [ ] RustFS-spezifische APIs gelangen nicht in Domain oder UI.
- [ ] Bucket ist privat; Downloads folgen Core-Autorisierung.
- [ ] Versandtes PDF wird nie überschrieben.

Tests/Nachweise:

- [ ] Contractsuite läuft gegen echtes RustFS und einen zweiten realen
      S3-kompatiblen Test-Endpunkt.
- [ ] Upload/Download bewahrt Bytes und SHA-256.
- [ ] Unberechtigte Persona erhält weder Objekt noch signierte URL.
- [ ] Reales Stoppen von RustFS verhindert Erfolgsstatus und lässt Job
      wiederholbar.

### [ ] POC-093 Dokumentabruf in allen Fachkontexten umsetzen

Abhängigkeiten: POC-043, POC-092

Akzeptanzkriterien:

- [ ] Dokument ist über Aktion, Commitment, Rechnung und CRM-Partei
      auffindbar.
- [ ] Charity-Admin und Finanzrolle sehen erlaubte Dokumente.
- [ ] Assignment allein gewährt Akquisiteur keinen Zugriff auf
      Finanzdokumente.
- [ ] Downloadname, Dateityp, Größe, Version und Erzeugungszeit sind sichtbar.
- [ ] Fehlende Storage-Datei erzeugt einen diagnostizierbaren Fehler und
      keinen leeren Download.

Tests/Nachweise:

- [ ] Integrationstest prüft jede Referenzrichtung gegen PostgreSQL/RustFS.
- [ ] E2E lädt als erlaubte Rolle ein byteidentisches PDF herunter.
- [ ] Negative E2E/API-Tests decken Akquisiteur und fremde Aktion ab.

### [ ] POC-094 Rechnungsversand und Versandprotokoll implementieren

Abhängigkeiten: POC-022, POC-092

Akzeptanzkriterien:

- [ ] Versand erfolgt über Outbox und realen SMTP-Relay-Vertrag.
- [ ] Mail besitzt verständlichen Betreff/Text und das richtige PDF.
- [ ] Versandstatus, Message-ID, Versuchszahl und Fehler sind sichtbar.
- [ ] Retry sendet nicht doppelt, wenn Erfolg bereits bestätigt wurde.
- [ ] Erneuter bewusster Versand erzeugt kein neues Rechnungsdokument.

Tests/Nachweise:

- [ ] Integrationstest sendet an echtes Mailpit und prüft MIME, Empfänger,
      Text, Attachment und PDF-Hash.
- [ ] Reales Stoppen von Mailpit erzeugt Retry und sichtbaren Fehler.
- [ ] Wiederanlauf nach Mailpit-Start führt zu genau einer erfolgreichen
      fachlichen Zustellung.
- [ ] E2E zeigt Versandstatus und administrativen Wiederanlauf.

### [ ] POC-095 Manuellen Zahlungseingang und Storno/Korrektur bauen

Abhängigkeiten: POC-090

Akzeptanzkriterien:

- [ ] Berechtigte Rolle kann Zahlung mit Datum, Betrag und Referenz erfassen.
- [ ] Im PoC unterstützte Vollzahlung ist klar von nicht unterstützten
      Teil-/Überzahlungen abgegrenzt.
- [ ] Zahlung und Storno erzeugen AuditEvents.
- [ ] Historische Rechnung und Dokumentversion bleiben unverändert.

Tests/Nachweise:

- [ ] Unit-Tests prüfen erlaubte Zahlungs-/Stornoübergänge.
- [ ] Integrationstest persistiert Zahlung und aktualisiert offenen Betrag.
- [ ] E2E zeigt offenen und bezahlten Golden-Fall verständlich.

---

## M10 – Dashboard, UX-System und Produktqualität

### [ ] POC-100 Gemeinsames UI-System und App Shell produktionsnah bauen

Abhängigkeiten: POC-002

Akzeptanzkriterien:

- [ ] shadcn/ui, Design Tokens und freie Hugeicons sind zentral gekapselt.
- [ ] Sidebar ist auf Desktop einklappbar; mobile Navigation ist
      aufgabenzentriert.
- [ ] Rolle und aktuelle Charity-Aktion sind stets verständlich sichtbar.
- [ ] Fokus, Dialoge, Toasts, Formfehler, Tabellen und Empty States folgen
      dokumentierten Patterns.
- [ ] Dark Mode wird nur aufgenommen, wenn vollständig; kein halbfertiges
      Theme.
- [ ] Lizenzhinweise für Icons und UI-Abhängigkeiten sind dokumentiert.

Tests/Nachweise:

- [ ] Story-/Komponentenkatalog zeigt alle Zustände mit Golden Data und
      realem Backend.
- [ ] Accessibility-Scan aller Basiskomponenten ist ohne kritische Befunde.
- [ ] Visuelle Regression prüft Shell bei mobilen und Desktop-Breiten.

### [ ] POC-101 Rollenbezogene Dashboards und Zielvisualisierung umsetzen

Abhängigkeiten: POC-050, POC-082, POC-095, POC-100

Akzeptanzkriterien:

- [ ] Akquisiteur sieht eigene Pipeline, Wiedervorlagen, Aktivitäten und
      Aktionsfortschritt.
- [ ] Charity-Admin sieht aktionsweite Pipeline, Bestellungen, fakturierten
      Betrag und offene Posten.
- [ ] Zielvisualisierung nennt Wert und Einheit zusätzlich zur Grafik.
- [ ] Kennzahlen besitzen eindeutige Definition und leiten auf gefilterte
      Detailansichten.
- [ ] Leere und teilweise konfigurierte Aktionen bleiben verständlich.

Tests/Nachweise:

- [ ] Unit-Tests prüfen Kennzahlableitung aus Golden Data.
- [ ] Integrationstest vergleicht API-Aggregate mit realen SQL-Ergebnissen.
- [ ] E2E prüft rollenverschiedene Dashboards und Drilldowns.
- [ ] Screenreader liest Zielstand und Status ohne visuelle Information.

### [ ] POC-102 Durchgängige UX-, Accessibility- und Content-Abnahme

Abhängigkeiten: POC-052, POC-062, POC-063, POC-071, POC-072, POC-081,
POC-082, POC-093, POC-094, POC-095, POC-101

Akzeptanzkriterien:

- [ ] Kritische Flows wurden mit mindestens einem Charity-Admin und einem
      Akquisiteur auf Smartphone und Desktop beobachtet.
- [ ] Keine Persona benötigt Datenbankwissen, interne IDs oder Twenty-
      Terminologie für den Kernablauf.
- [ ] Fehlermeldungen erklären Problem, Auswirkung und nächsten Schritt.
- [ ] Fokusreihenfolge, Zoom, Kontrast, Labels, Statusmeldungen und
      Tastaturbedienung sind geprüft.
- [ ] Jede Kernseite erfüllt vereinbarte Performancebudgets.
- [ ] P0/P1-Usability- und Accessibility-Befunde sind geschlossen.

Tests/Nachweise:

- [ ] Moderiertes Golden-Scenario-Protokoll und priorisierte Befundliste
      liegen vor.
- [ ] Automatisierte Accessibility-Suite ist grün.
- [ ] Manuelle Tastatur- und Screenreader-Smoke-Tests sind protokolliert.
- [ ] Browser-Traces belegen Performancebudgets unter reproduzierbarer Last.

---

## M11 – Sicherheit, Datenschutz und Betrieb

### [ ] POC-110 Security Baseline und sichere Defaults umsetzen

Abhängigkeiten: POC-010, POC-020, POC-042, POC-043

Akzeptanzkriterien:

- [ ] TLS, Security Header, CORS, CSRF, Cookie- und Proxy-Vertrauen sind
      explizit konfiguriert.
- [ ] Rate Limits schützen Login, Einladung und Public Forms.
- [ ] Secrets stammen aus externer Konfiguration und erscheinen nicht in
      Logs, Images oder Browserbundles.
- [ ] Upload-/Downloadpfade prüfen Typ, Größe, Hash und Autorisierung.
- [ ] Logs minimieren personenbezogene Daten und besitzen Löschregeln.
- [ ] Dependency-, Container- und Secret-Scans blockieren kritische Befunde.

Tests/Nachweise:

- [ ] Dynamische Tests prüfen CSRF, CORS, Session Fixation, horizontale
      Rechteausweitung und Rate Limits gegen den realen Stack.
- [ ] Secret-Canary gelangt weder in Logs noch Fehlerantworten.
- [ ] Security-Header werden über den echten Reverse Proxy geprüft.

### [ ] POC-111 Datenschutz-, Consent-, Suppression- und Löschgrundlagen bauen

Abhängigkeiten: POC-021, POC-072

Akzeptanzkriterien:

- [ ] Public Form speichert Textversion, Zweck, Quelle und Zeitpunkt
      erforderlicher Consent-Nachweise.
- [ ] Kontaktsperre verhindert unzulässige weitere Kontaktaufnahme.
- [ ] Export-/Auskunftspfad bündelt relevante LeonAid-Referenzen.
- [ ] Lösch-/Anonymisierungsprozess respektiert Rechnungsaufbewahrung und
      dokumentiert verbleibende Rechtsgrundlage.
- [ ] Offene rechtliche Entscheidungen sind sichtbar und nicht durch Code
      erfunden.

Tests/Nachweise:

- [ ] Integrationstest legt Consent an, widerruft ihn und prüft Suppression.
- [ ] Golden-Export enthält erwartete Daten und keine fremden Datensätze.
- [ ] Löschtest bewahrt erforderlichen Rechnungssnapshot, entfernt aber
      löschbare operative Daten.

### [ ] POC-112 Backup, Restore und Disaster-Recovery automatisieren

Abhängigkeiten: POC-010, POC-030, POC-092

Akzeptanzkriterien:

- [ ] Backup umfasst Core-PostgreSQL, Twenty-Datenbank/-Konfiguration und
      RustFS-Objekte konsistent dokumentiert.
- [ ] Backups sind verschlüsselt und liegen außerhalb desselben VPS.
- [ ] Aufbewahrung, Rotation, Integritätsprüfung, RPO und RTO sind definiert.
- [ ] Restore-Script verweigert unklare Zielumgebungen.
- [ ] Runbook beschreibt vollständigen Wiederanlauf inklusive Secrets,
      DNS/Proxy und Verifikation.

Tests/Nachweise:

- [ ] Recovery-Test beginnt mit frischen Volumes und stellt Golden Data
      vollständig wieder her.
- [ ] Jede Rechnung stimmt nach Restore mit gespeicherter SHA-256 überein.
- [ ] LeonAid-/Twenty-Referenzen, Sessions, Audit und Outbox sind konsistent.
- [ ] Gemessenes RPO/RTO wird protokolliert und erfüllt das festgelegte Ziel.

### [ ] POC-113 Upgrade- und Rollback-Prozess beweisen

Abhängigkeiten: POC-001, POC-112

Akzeptanzkriterien:

- [ ] Updateprozess prüft Release Notes, Migrationen, Backup und
      Kompatibilitätsmatrix.
- [ ] Twenty- und RustFS-Upgrades laufen zuerst gegen einen Golden-Data-Klon.
- [ ] Rollbackgrenze ist pro Komponente dokumentiert; Datenmigrationen haben
      eine Wiederherstellungsstrategie.
- [ ] Wartungsmodus verhindert Schreibvorgänge während inkompatibler Phasen.

Tests/Nachweise:

- [ ] Upgrade von der zuvor gepinnten auf die vorgesehene neue Testversion
      wird real durchgeführt.
- [ ] Contract- und E2E-Suite laufen vor und nach dem Upgrade.
- [ ] Ein absichtlich gescheitertes Upgrade wird aus Backup sauber
      zurückgesetzt.

### [ ] POC-114 Observability und operatives Admin-Debugging ergänzen

Abhängigkeiten: POC-022, POC-031, POC-094

Akzeptanzkriterien:

- [ ] Strukturierte Logs tragen Request-, Job-, Action- und relevante
      Fachobjekt-ID.
- [ ] Metriken decken API-Latenz/Fehler, Outbox, Twenty, RustFS, Mail und
      Login ab.
- [ ] Admin sieht fehlgeschlagene Jobs und darf sichere Wiederholung
      auslösen.
- [ ] Healthchecks unterscheiden Prozessverfügbarkeit und Abhängigkeiten.
- [ ] Personenbezogene Inhalte, Tokens und Dokumentbytes werden nicht
      protokolliert.

Tests/Nachweise:

- [ ] Ein E2E-Request lässt sich vom Browser bis Twenty/RustFS/Mail
      korrelieren.
- [ ] Reale Ausfälle von Twenty, RustFS und Mailpit erzeugen jeweils
      unterscheidbare Signale.
- [ ] Retry über Admin-UI verarbeitet den echten fehlgeschlagenen Job.

---

## M12 – Krapfentaxi-Abnahme und Übergabe

### [ ] POC-122 Vollständige Krapfentaxi-Golden-Journey abnehmen

Abhängigkeiten: alle Tasks POC-000 bis POC-114

Akzeptanzkriterien:

- [ ] Journey umfasst Einladung, Login, Sponsor, Assignment, Aktivität,
      interne und öffentliche Bestellung, Feed, Fresh Login, Rechnung, PDF,
      Versand, Zahlung und Dashboard.
- [ ] Journey benötigt keine direkte Datenbankarbeit.
- [ ] Alle Rollen- und Row-Level-Grenzen bleiben aktiv.
- [ ] Reale Twenty-, PostgreSQL-, RustFS-, Mail- und Browserartefakte werden
      gesammelt.
- [ ] Wiederholung aus Golden Reset ist deterministisch.

Tests/Nachweise:

- [ ] E2E-Journey läuft in Chromium, Firefox und WebKit.
- [ ] PDF-Bytes/-Inhalt, Mail-MIME, Twenty-Daten, DB-Summen und RustFS-Hash
      werden geprüft.
- [ ] Zweiter Lauf erzeugt erwartete neue Fachvorgänge, aber keine technischen
      Duplikate.
- [ ] Sämtliche Gates aus Kapitel 10.3 besitzen einen grünen Nachweislink.

### [ ] POC-123 PoC-Abnahme, Runbooks und DX-Übergabe abschließen

Abhängigkeiten: POC-102, POC-112, POC-113, POC-114, POC-122

Akzeptanzkriterien:

- [ ] README führt neue Entwickler in höchstens 30 Minuten zu laufendem Stack
      und Golden Journey.
- [ ] Betriebs-, Backup-, Restore-, Upgrade-, Incident- und
      Benutzerverwaltungs-Runbooks sind vollständig.
- [ ] Architektur-, Datenmodell-, API- und Sicherheitsentscheidungen sind
      aktuell.
- [ ] Bekannte Grenzen und bewusst verschobene Funktionen sind sichtbar.
- [ ] Keine P0/P1-Defekte und keine ungeklärten kritischen
      Sicherheits-/Datenverlustbefunde bleiben offen.
- [ ] Produktverantwortlicher nimmt den PoC anhand der Golden Journey ab.

Tests/Nachweise:

- [ ] Unbeteiligte technische Person führt Bootstrap, Reset, Kernjourney und
      Restore nur anhand der Dokumentation aus.
- [ ] Finaler CI-Lauf startet ohne Cache und veröffentlicht alle
      Beweisartefakte.
- [ ] Abnahmeprotokoll verlinkt Commit, Locks, Dataset-Version,
      Testberichte, Screenshots, PDFs und Runbooks.

## 5. Empfohlene Ausführungsreihenfolge

```text
M0 Baseline/Toolchain
  → M1 echter Stack + Golden Data
  → M2 FastAPI/PostgreSQL/OpenAPI
  → M3 Twenty
  → M4 Auth/Policies
  → M5 Action/Admin
  → M6 Akquise/PWA
  → M8 Offerings/Commitments
  → M7 Public Web
  → M9 Rechnung/Dokument/Mail
  → M10 Dashboard/UX
  → M11 Security/Betrieb
  → M12 Validierung/Abnahme
```

Der erste demonstrierbare Walking Skeleton soll bereits nach M4 einen realen
Login über UI → FastAPI → PostgreSQL und einen berechtigten Twenty-Lesezugriff
zeigen. Danach liefert jeder Meilenstein eine sichtbar bessere, weiterhin
vollständig lauffähige Golden Journey.

## 6. Nicht verhandelbare PoC-Abnahmematrix

| Gate | Primäre Tasks |
|---|---|
| Fremde CRM-Datensätze bleiben unsichtbar | POC-043, POC-062 |
| Einladungs- und Aktionsgrenzen | POC-041, POC-042 |
| Mehrfachzuordnung mit Warnung | POC-032, POC-060, POC-063 |
| Adminablauf ohne DB-Arbeit | POC-052, POC-122 |
| Reproduzierbares Twenty-Schema | POC-030 |
| Genau eine Rechnung je Freigabe | POC-090 |
| Unveränderlicher Rechnungssnapshot | POC-090, POC-091 |
| Geschützter Dokumentzugriff | POC-092, POC-093 |
| RustFS-Ausfall und Restore | POC-092, POC-112 |
| Providerneutraler S3-Vertrag | POC-092 |
| Idempotente Formulare/Jobs | POC-022, POC-072, POC-081, POC-094 |
| Öffentliche Bestellung im Feed | POC-072, POC-082 |
| Alias und unveränderliches Archiv | POC-070, POC-071 |
| Reales, portables PDF | POC-091 |
| Sichtbarer Versandstatus | POC-094, POC-114 |
| Vollständiger Backup/Restore | POC-112 |
| World-class UX/DX | POC-002, POC-100, POC-102, POC-123 |

Der PoC ist nicht abgeschlossen, solange ein Eintrag dieser Matrix nur durch
eine Annahme, einen Mock, einen Screenshot ohne überprüften Zustand oder einen
manuellen Datenbankeingriff „belegt“ ist.

Lions Open und Weihnachtsmarkt beginnen erst nach erfolgreicher
Krapfentaxi-Abnahme mit jeweils eigener Discovery, Golden Data und einem
separaten Implementierungsplan. Sie sind keine versteckten Abhängigkeiten
dieses Plans.
