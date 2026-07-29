# LeonAid Pilot – technischer Implementierungs- und Abnahmeplan

Status: aktiv; Pilot-Infrastruktur vollständig bewiesen, technische
Teilnachweise vorhanden, externe Pilotfreigaben noch offen
Planbasis: Commit `18c324bb5b4947ea182d7a708ed44fff37359a9c` vom
28. Juli 2026  
Vorgänger:
[Krapfentaxi-PoC](../leonaid-poc/PLAN.md) – vollständig bewiesen und
fachlich abgenommen  
Primäre Produktspezifikation:
[Produkt- und Architekturvorschlag](../produkt-und-architekturvorschlag.md)  
Verbindliche Personas und Rollen:
[`PERSONAS.md`](../../PERSONAS.md)

> **Ausführungsregel:** Jeder Task wird einzeln vollständig implementiert,
> mit den darunter genannten realen Nachweisen bewiesen, im zugehörigen
> Proof-Dokument protokolliert und erst dann abgehakt. Erst danach wird
> committed und der Commit direkt auf `main` gepusht. Mehrere nur teilweise
> fertige Tasks dürfen nicht in einem vermeintlichen Abschlusscommit
> zusammengefasst werden.

## 1. Ziel des Pilot-Milestones

Der Milestone überführt den technisch bewiesenen Krapfentaxi-PoC in einen
begrenzten, betreibbaren **Single-Club-Pilot** mit realen Mitgliedern und
echten, rechtmäßig verarbeiteten Daten.

Der Pilot beweist nicht nur, dass der Fachablauf funktioniert, sondern dass
ein benannter Betreiber ihn ohne direkte Datenbankeingriffe sicher
bereitstellen, administrieren, überwachen, sichern und wiederherstellen kann.

### 1.1 Erfolg in einem Satz

Ein Lions-Club kann eine echte Krapfentaxi-Aktion mit einem kleinen
Pilotnutzerkreis durchführen: Kontakte werden kontrolliert importiert,
Mitglieder vollständig administriert, öffentliche und interne Bestellungen
bearbeitet, Rechnungen rechtssicher konfiguriert erzeugt und über einen
produktiven Maildienst versendet; Betrieb, Alarmierung, Backup und Restore
sind mit realen Systemen nachgewiesen.

### 1.2 Pilot-Personas

Der Pilot muss sämtliche im PoC bewiesenen Personas weiter unterstützen:

- **System-Admin:** Installation, globale Rollen, Accounts, Sessions,
  Integrationen, Betrieb und Wiederanlauf;
- **Charity-Admin:** eigene Krapfentaxi-Aktion, Aktionsrollen,
  Bestellungen, Rechnungen und Feed;
- **Akquisiteur:** eigene Sponsoren, Zuordnungen, Aktivitäten und Zusagen;
- **Finanzverantwortlicher:** Rechnungsjournal und Zahlungsstatus gemäß
  zugewiesener Lese- oder Verwaltungsrolle;
- **öffentlicher Besteller/Sponsor:** Aktionsseite und Bestellformular ohne
  Account.

`Ausfahrer` bleibt als technisch vorhandene aktionsbezogene Rolle erhalten,
erhält in diesem Milestone aber noch keinen produktiven Lieferworkflow.

### 1.3 Harte Pilotgrenze

Enthalten:

- genau eine Club-/Trägerinstallation;
- ausschließlich Krapfentaxi als realer End-to-End-Use-Case;
- vollständige Benutzer- und Rollenadministration ohne Datenbankzugriff;
- produktiver Mail-Relay;
- kontrollierter Import der tatsächlich gelieferten Excel-Datei;
- produktive Träger-, Rechnungs-, Datenschutz- und Aufbewahrungskonfiguration;
- Single-Host-Betrieb mit DNS, TLS, externen Secrets, Off-Host-Backup,
  Alarmierung, Release- und Incident-Verfahren;
- begrenzter Pilotnutzerkreis und protokollierte Pilotabnahme.

Nicht enthalten:

- Tourenplanung, Fahrerdisposition, Offline-Sync oder Push-Nachrichten;
- Lions Open oder Weihnachtsmarkt;
- allgemeiner Formular-, Workflow- oder CMS-Builder;
- listmonk-Kampagnenbetrieb;
- allgemeines DMS;
- Banking, automatische Zahlungszuordnung, Mahnwesen, Teilzahlungen,
  Spendenbescheinigungen oder vollständige Buchhaltung;
- Hochverfügbarkeit, Kubernetes, Multi-Region oder mehrere Clubs in einer
  Installation;
- Passkeys, SSO, Social Login oder öffentliche Selbstregistrierung.

Wenn ein rechtliches Ergebnis E-Rechnung, Buchhaltung oder einen anderen hier
ausgeschlossenen Funktionsbereich zwingend vor dem Pilot verlangt, wird der
Pilot gestoppt und ein eigener vorgeschalteter Milestone geplant. Der Scope
wird nicht stillschweigend erweitert.

## 2. Nicht verhandelbare Arbeits- und Beweisregeln

### 2.1 Docker-only

- Produkt-, Migrations-, Test-, Import-, Backup- und Betriebsbefehle laufen
  ausschließlich über digest-gepinnte Docker-Images und Docker Compose.
- Auf dem Host werden außer Docker/OrbStack und Git keine Projekt-Runtimes
  vorausgesetzt.
- `uv`, Bun, Python, Node, Typst, Playwright, Restic und externe
  Systemwerkzeuge werden nicht ungepinnt auf dem Host ausgeführt.
- Der bestehende Einstieg `./leonaid` bleibt die kanonische
  Operator-/Entwicklerschnittstelle.

### 2.2 Keine Mocks

- Unit-Tests verwenden echte Domain-Objekte aus dem synthetischen Golden
  Dataset.
- Integrationstests verwenden reale PostgreSQL-, Twenty-, Redis-, RustFS-,
  SMTP-, Typst-, Proxy- und Backup-Systeme.
- E2E-Tests bedienen die gebauten Anwendungen in realen Browsern.
- Providerverträge werden gegen das ausgewählte reale Produkt oder dessen
  offiziellen Sandbox-/Testmodus geprüft, nicht gegen selbst geschriebene
  Antwortattrappen.
- Ausfälle werden durch Stoppen, Sperren oder Fehlkonfigurieren realer
  Dienste erzeugt.

### 2.3 Daten- und Beweisgrenze

- Personenbezogene Pilotdaten, echte Excel-Dateien, Zugangsdaten,
  Login-Codes, Mailinhalte, Rechnungen und nicht anonymisierte Screenshots
  werden niemals committed oder in öffentliche CI-Artefakte geladen.
- Reale Intake- und Beweisdateien liegen ausschließlich unter
  `.local/pilot/` mit restriktiven Dateirechten oder in einem dokumentierten
  externen, zugriffsgeschützten Evidence Store.
- Automatisierte CI verwendet weiterhin ausschließlich Golden Dataset v1
  oder eine spätere, versionierte synthetische Golden-Version.
- Für reale Daten wird nur ein minimierter, personenbezugsfreier
  Summennachweis committed: Zeitpunkt, Dataset-Fingerprint, Counts,
  Fehlerklassen, freigebender Operator und Proof-ID.
- Sanitizer prüfen Logs, Traces, Screenshots, Reports und ZIP-Artefakte vor
  jeder Veröffentlichung.

### 2.4 UX-/DX-Qualität

- Kein Pilot-Operator benötigt Datenbankwissen, interne UUIDs oder direkte
  Twenty-PostgreSQL-Zugriffe.
- Sensible Aktionen erklären Auswirkung, betroffene Person/Aktion und den
  nächsten Schritt vor der Bestätigung.
- Lade-, Leer-, Erfolg-, Konflikt-, Wiederholungs- und Fehlerzustände sind
  eigenständig gestaltet.
- Alle Pilotoberflächen funktionieren mit Tastatur, Screenreader, 200 %
  Zoom, Smartphone und Desktop sowie in Dark/Light/System Mode.
- E2E-Nachweise werden zusätzlich im In-App-Browser sichtbar ausgeführt,
  damit der Produktverantwortliche den Zustand nachvollziehen kann.
- Neue Operatorbefehle besitzen `--help`, sichere Defaults, Dry Run,
  maschinenlesbare Reports und handlungsorientierte Fehlertexte.

### 2.5 Commit-/Push-Protokoll

Für jeden Task:

1. Task und alle Unterkriterien bleiben zunächst offen.
2. Implementierung und neue Tests werden abgeschlossen.
3. Alle unter „Tests/Nachweise“ genannten Befehle laufen grün.
4. `specs/leonaid-pilot/proofs/PILOT-NNN.md` enthält Commitbasis,
   Testausgaben, Artefakt-IDs und bewusst nicht veröffentlichte Beweise.
5. Erst jetzt werden Task und Unterkriterien abgehakt.
6. `git diff --check`, `./leonaid check` und der task-spezifische Test sind
   grün.
7. Ein Task-Commit im bestehenden Conventional-Commit-Stil wird erstellt und
   sofort auf `main` gepusht.
8. Der zugehörige GitHub-CI-Lauf muss terminal grün sein, bevor der nächste
   abhängige Task beginnt.

## 3. Aktueller technischer Ausgangspunkt

Die folgenden Tatsachen wurden gegen Commit `18c324b` verifiziert und sollen
erweitert, nicht parallel neu implementiert werden:

| Bereich | Bestehender Vertrag | Relevante Pfade |
| --- | --- | --- |
| Account-Zustände | `invited`, `active`, `suspended`, `archived` und erlaubte Übergänge existieren | `src/leonaid/domain/identity.py` |
| Identity-Administration | Status-, globale Rollen- und Membership-Mutationen existieren serverseitig | `src/leonaid/application/identity.py` |
| Sitzungsentzug | serverseitiger Sofortwiderruf und Fresh Login existieren | `src/leonaid/application/sessions.py`, `DELETE /api/v1/admin/users/{user_id}/sessions` |
| Mitglieder-UI | Einladungsformular vorhanden; vollständige Liste und Lebenszyklus fehlen | `packages/features/src/action-admin/member-invitation.tsx` |
| CRM-Import | XLSX/CSV, Mapping, Dry Run, Apply, Konflikte und idempotente Wiederholung vorhanden | `tools/twenty/import_contacts.py`, `infra/twenty/import-mapping.json` |
| Mail | Outbox und echter SMTP-Versand vorhanden, Konfiguration ist noch Mailpit-zentriert | `src/leonaid/adapters/mail/`, `src/leonaid/configuration.py`, `infra/compose/compose.yml` |
| Betrieb | Health, Operations-UI, Dead Letter, Backup/Restore und Upgrade sind gegen Golden Data bewiesen | `src/leonaid/application/operations.py`, `infra/backup/`, `infra/upgrade/` |
| Deployment | eine lokale Compose-Definition mit Loopback-Caddy ist kanonisch | `infra/compose/compose.yml`, `infra/proxy/Caddyfile` |
| Datenschutz | Consent, Export, Suppression und Erasure sind technisch vorhanden; reale Fristen sind offen | `src/leonaid/application/privacy.py`, `specs/leonaid-poc/DECISIONS.md` |

### 3.1 Drift-Prüfung vor der Ausführung

Der erste Executor führt aus:

```sh
git diff --stat 18c324bb5b4947ea182d7a708ed44fff37359a9c..HEAD -- \
  src apps packages infra tools tests specs PERSONAS.md README.md leonaid
```

Bei Änderungen an den oben genannten Ausgangsverträgen werden die betroffenen
Task-Schritte vor Implementierung gegen den Live-Code abgeglichen. Der Plan
darf aktualisiert werden, aber nicht durch stillschweigende Annahmen
„zurechtinterpretiert“ werden.

## 4. Kanonische Befehle

Bestehend:

| Zweck | Befehl | Erwartung |
| --- | --- | --- |
| Bootstrap | `./leonaid bootstrap` | ausschließlich gelockte Docker-Toolchains |
| Diagnose | `./leonaid doctor` | alle Voraussetzungen verständlich bewertet |
| statische Gates | `./leonaid check` | Format, Typen, Unit, Verträge und Policies grün |
| echter Stack | `./leonaid dev` | alle Core-Dienste healthy |
| CRM-Import | `./leonaid import-crm dry-run SOURCE` | kein Schreibzugriff, JSON-Report |
| Integration | `./leonaid test-integration` | frische reale Dienste, keine Mocks |
| Browser | `./leonaid test-e2e` | alle realen Browserstrecken grün |
| Golden Journey | `./leonaid test-golden-journey` | vollständiger Krapfentaxi-Ablauf |
| Recovery | `./leonaid test-backup` | verschlüsselter Restore in frisches Ziel |
| Security | `./leonaid test-security` | dynamische und statische Gates grün |
| Privacy | `./leonaid test-privacy` | Consent, Export und Erasure grün |

Im Pilot einzuführende, ebenfalls Docker-basierte Befehle:

```text
./leonaid pilot-doctor
./leonaid pilot-deploy
./leonaid pilot-release
./leonaid pilot-import <dry-run|apply|verify>
./leonaid pilot-backup
./leonaid pilot-restore
./leonaid test-pilot-contract
./leonaid test-pilot-data-boundary
./leonaid test-user-admin
./leonaid test-mail-relay
./leonaid test-pilot-import
./leonaid test-pilot-deployment
./leonaid test-pilot-backup
./leonaid test-pilot-alerting
./leonaid test-pilot-release
./leonaid test-pilot-legal-config
./leonaid test-pilot-rehearsal
./leonaid test-pilot-readiness
```

Jeder neue Befehl erhält einen positiven Realnachweis und mindestens einen
realen Ablehnungsfall.

## 5. Ausführungsreihenfolge

```text
M0 Pilotvertrag und Entscheidungen
  PILOT-000 → PILOT-001 → PILOT-002

M1 Basis der Benutzeradministration
  PILOT-010 → PILOT-011 → PILOT-012

M2 Produktive E-Mail
  PILOT-020 → PILOT-021

M1 Abschluss nach Mailbasis
  PILOT-012 + PILOT-020 → PILOT-013

M3 Datenanalyse ohne Produktivzugriff
  PILOT-030

M4 Betriebsbasis
  PILOT-040 → PILOT-041 → PILOT-042 → PILOT-043 → PILOT-044

M3 Staging- und Produktionsimport
  PILOT-030 + PILOT-040 + PILOT-041 → PILOT-031
  PILOT-031 + PILOT-043 + PILOT-044 → PILOT-032

M5 Pilotdurchführung und Freigabe
  PILOT-050 → PILOT-051 → PILOT-052 → PILOT-053
```

Die Nummern M1 bis M4 benennen fachliche Arbeitsströme, keine strikt
nacheinander abzuarbeitenden Phasen. M1, M2, die private Strukturanalyse aus
M3 und die technischen Teile von M4 dürfen nach M0 parallel entwickelt
werden. PILOT-013 darf erst auf dem produktionsfähigen Mailpfad aufsetzen;
PILOT-031 erst auf getrenntem Staging und bewiesenem Restore. Reale
Datenübernahme, produktiver Versand und Pilotaktivierung dürfen erst nach den
jeweils genannten Entscheidungs- und Betriebs-Gates erfolgen.

## 6. M0 – Pilotvertrag und bindende Entscheidungen

### [x] PILOT-000 Pilot-Traceability und Proof-Infrastruktur etablieren

Priorität: P1 · Aufwand: S · Risiko: niedrig  
Abhängigkeiten: abgeschlossener PoC

In Scope:

- `specs/leonaid-pilot/`
- `tools/traceability/`
- `tools/ci/`
- `leonaid`
- `.github/workflows/`

Akzeptanzkriterien:

- [x] Jeder Pilot-Task, jedes Akzeptanzkriterium und jeder harte Gate besitzt
      eine stabile ID.
- [x] `specs/leonaid-pilot/proofs/` ist der einzige versionierte Ort für
      personenbezugsfreie Pilotnachweise.
- [x] Private Evidence-Pfade und öffentliche CI-Artefakte sind explizit
      getrennt.
- [x] `./leonaid test-pilot-contract` prüft Planstruktur, Abhängigkeiten,
      offene/geschlossene Kriterien und Proof-Links.
- [x] CI veröffentlicht auch bei Fehlschlag sanitizte, secretsfreie
      Task-Artefakte.
- [x] Das bestehende PoC-Traceability-Gate bleibt unverändert grün.

Tests/Nachweise:

- [x] Positivtest akzeptiert den vollständigen Pilotplan.
- [x] Negative Tests lehnen fehlenden Proof-Link, verwaistes Kriterium,
      unbekannte Abhängigkeit und verfrüht abgehakten Task ab.
- [x] `./leonaid test-pilot-contract` meldet `pilot-contract: OK`.
- [x] `./leonaid check` bleibt grün.

### [ ] PILOT-001 Rechtliche und operative Pilotentscheidungen schließen

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-000

In Scope:

- `specs/leonaid-pilot/DECISIONS.md`
- neue ADRs unter `specs/leonaid-pilot/decisions/`
- referenzierte private Freigaben ohne personenbezogene Inhalte

Mindestens zu entscheiden:

- rechtlicher Träger und Rechnungsaussteller;
- konkrete Steuerbehandlung der Krapfentaxi-Leistung;
- Pflichtangaben und Freigabeverantwortung für Rechnungen;
- E-Rechnungsbedarf für den Pilotzeitraum;
- Aufbewahrungs-, Sperr- und Löschfristen je Fachobjekt;
- Rechtsgrundlage und Informationstext für Kontakte und öffentliche
  Bestellungen;
- produktiver Mail-Relay und verantwortlicher Mail-Domain-Owner;
- DNS-, VPS-, Backup-, Secret-, Monitoring- und Incident-Owner;
- Pilotzeitraum, maximale Nutzerzahl und benannter Go/No-Go-Entscheider.

Akzeptanzkriterien:

- [x] Jede Entscheidung besitzt ID, Owner, Datum, Quelle, Status und
      spätestes Gate.
- [x] Entscheidungen mit rechtlicher Tragweite werden nicht allein von der
      Implementierung getroffen.
- [x] Reale Namen, Verträge, Steuerunterlagen und Zugangsdaten bleiben im
      privaten Evidence Store; das Register enthält nur Ergebnis und
      Referenz-ID.
- [x] `pilot-doctor` blockiert produktive Befehle bei offener
      gate-relevanter Entscheidung.
- [x] Eine erforderliche E-Rechnung oder vollständige Buchhaltung führt zu
      `STOP`, nicht zu einer stillen Erweiterung des ERP-light.

Tests/Nachweise:

- [x] Contract-Test lehnt `open` für jede vor dem Pilot fällige Entscheidung
      ab.
- [x] Negative Tests prüfen fehlenden Owner, fehlende Evidence-ID und
      widersprüchliche Steuer-/Rechnungskonfiguration.
- [ ] Produktverantwortlicher, Betrieb und erforderliche Fachstellen
      bestätigen das Register.

Technischer Teilnachweis und verbleibende Fachfreigabe:
[`proofs/PILOT-001.md`](proofs/PILOT-001.md)

### [ ] PILOT-002 Private Daten- und Evidence-Grenze beweisen

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-000, PILOT-001

In Scope:

- `.gitignore`
- `tools/security/`
- `tools/ci/sanitize_artifacts.py`
- neue Pilot-Evidence-Werkzeuge unter `tools/pilot/`
- `specs/leonaid-pilot/DATA-HANDLING.md`

Akzeptanzkriterien:

- [x] `.local/pilot/` und alle dokumentierten privaten Intake-/Evidence-Pfade
      sind ignoriert und werden mit Modus `0600` beziehungsweise
      Verzeichnismodus `0700` angelegt.
- [x] Ein Pilot-Evidence-Manifest speichert nur SHA-256, Counts,
      Fehlerklassen, Zeitpunkte, Actor-ID und externe Evidence-ID.
- [x] E-Mail, Namen, Adressen, Telefon, Rechnungsdaten, Tokens und
      Dokumentbytes werden aus öffentlichen Artefakten entfernt.
- [x] Der Sanitizer verarbeitet Text, JSON, HTML, Playwright-Traces,
      Screenshots, PDFs und verschachtelte ZIP-Dateien fail-closed.
- [x] Produktive Backups und private Beweise werden nicht in GitHub Actions
      hochgeladen.
- [x] Testlogins bleiben für lokale/staging Golden-Tests erreichbar, werden
      aber niemals als gemeinsame Produktionsaccounts angelegt.

Tests/Nachweise:

- [x] Canary-Test injiziert synthetische PII- und Secret-Signaturen in jede
      unterstützte Artefaktart und beweist deren Ablehnung.
- [x] Git-History-/Index-Test lehnt eine absichtlich gestagte
      Pilot-Intake-Datei ab.
- [x] Reale Dateirechte werden in einem Docker-/Host-Grenztest geprüft.
- [x] `./leonaid test-pilot-data-boundary` ist grün.

Technischer Nachweis:
[`proofs/PILOT-002.md`](proofs/PILOT-002.md)

## 7. M1 – Vollständige Benutzeradministration

### [ ] PILOT-010 Autorisierte Mitgliederübersicht bereitstellen

Priorität: P1 · Aufwand: M · Risiko: mittel  
Abhängigkeiten: PILOT-002

In Scope:

- `src/leonaid/application/identity.py`
- `src/leonaid/adapters/postgres/identity.py`
- `src/leonaid/entrypoints/fastapi/routes.py`
- `src/leonaid/entrypoints/fastapi/schemas.py`
- `packages/api-client/`
- `packages/features/src/action-admin/`
- `apps/web/`
- Identity-Unit-/Integration-/E2E-Tests

Akzeptanzkriterien:

- [x] System-Admin sieht alle Accounts mit Status, Rollen,
      Aktionsmitgliedschaften, letztem Login und aktiven Sitzungszahlen.
- [x] Charity-Admin sieht ausschließlich Mitglieder in selbst verwalteten
      Aktionen und keine globalen Rollen außerhalb seines Scopes.
- [x] Akquisiteur, Finanzen und öffentliche Persona erhalten keinen
      Mitgliederlisten-Zugriff.
- [x] Suche, Statusfilter, Aktionsfilter und cursorbasierte Pagination sind
      serverseitig autorisiert.
- [x] Die Oberfläche verwendet Namen und verständliche Rollen statt
      interner UUIDs.
- [x] Empty, Loading, Fehler, Teilzugriff und leere Suchergebnisse sind
      gestaltet.
- [x] Liste und Detail funktionieren auf Smartphone, Desktop, Tastatur und
      Screenreader.

Tests/Nachweise:

- [x] Unit-Tests prüfen Filter-/Sortiervertrag mit Golden-Domainobjekten.
- [x] Integrationstest vergleicht API-Ergebnis mit echtem PostgreSQL und
      beweist Charity-Admin-Row-Level-Grenzen.
- [x] Negative API-Tests prüfen alle nicht berechtigten Personas.
- [x] E2E bedient Suche, Filter, Pagination und Detail in Chromium sowie
      sichtbar im In-App-Browser.
- [x] Axe besitzt keine kritischen oder ernsten Befunde.

### [ ] PILOT-011 Account sperren, reaktivieren und archivieren

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-010

Bestehende Basis:
`AccountStatus`, `ALLOWED_ACCOUNT_TRANSITIONS` und
`IdentityAdministrationService.change_status` werden erweitert und über API/UI
zugänglich gemacht; keine parallele Zustandsmaschine entsteht.

Akzeptanzkriterien:

- [x] Nur System-Admin mit frischer Anmeldung darf Accountstatus ändern.
- [x] Sperren widerruft atomar alle aktiven Sitzungen und verhindert neue
      Login-Challenges.
- [x] Reaktivieren stellt keine alten Sitzungen wieder her.
- [x] Archivieren erhält historische Zuordnungen, Audit, Rechnungen und
      Dokumentreferenzen unverändert.
- [x] Selbstsperre/-archivierung und Archivierung des letzten aktiven
      System-Admins werden serverseitig verhindert.
- [x] UI zeigt Auswirkung, betroffene Person, Session-Anzahl und erforderliche
      Bestätigung.
- [x] Jede Änderung besitzt erwartete Revision/Idempotency-Key und AuditEvent.

Tests/Nachweise:

- [x] Unit-Tests prüfen alle erlaubten und verbotenen Übergänge.
- [x] Integrationstest sperrt einen Account mit zwei realen Sessions und
      beweist sofortigen Entzug in PostgreSQL und FastAPI.
- [x] E2E beweist Fresh Login, Sperren, abgewiesene alte Browser-Session,
      Reaktivieren und neuen Login.
- [x] Concurrency-Test lässt nur eine von zwei widersprüchlichen
      Statusänderungen gewinnen.

### [ ] PILOT-012 Rollen und Aktionsmitgliedschaften vollständig verwalten

Priorität: P1 · Aufwand: L · Risiko: hoch  
Abhängigkeiten: PILOT-010, PILOT-011

Bestehende Basis:
`IdentityAdministrationService` besitzt bereits Grant/Revoke-Operationen für
globale Rollen und Aktionsmitgliedschaften.

Akzeptanzkriterien:

- [x] System-Admin kann globale Rollen und alle Aktionsrollen hinzufügen und
      entfernen.
- [x] Charity-Admin kann ausschließlich Aktionsrollen in selbst verwalteten
      Aktionen ändern.
- [x] Charity-Admin kann weder System-Admin noch globale Finanzrollen
      vergeben.
- [x] Entfernen des letzten Charity-Admins einer aktiven Aktion wird
      verhindert oder erfordert eine atomare Nachfolgezuweisung.
- [x] Rollenänderungen wirken im nächsten Request auf Navigation, Listen,
      Exporte und Dokumentzugriff.
- [x] Bestehende historische Fachzuordnungen werden durch
      Membership-Entzug nicht gelöscht.
- [x] Änderungen benötigen Fresh Login, erwartete Revision, verständliche
      Konflikte und AuditEvents.
- [x] Rollenmatrix in `PERSONAS.md`, OpenAPI und UI bleibt konsistent.

Tests/Nachweise:

- [x] Unit-Tests prüfen Rollenmatrix und Last-Admin-Invariante.
- [x] Integrationstest mutiert Memberships gegen PostgreSQL und prüft jede
      Row-Level-Grenze ohne neue Anmeldung.
- [x] E2E führt Rollenwechsel und vollständiges Offboarding über UI durch.
- [x] Negative E2E beweist, dass Charity-Admin globale Rollen weder sieht
      noch über direkte API-Aufrufe ändern kann.

### [ ] PILOT-013 Einladungen und E-Mail-Korrektur betreibbar machen

Priorität: P1 · Aufwand: L · Risiko: hoch  
Abhängigkeiten: PILOT-010, PILOT-011, PILOT-012, PILOT-020

Akzeptanzkriterien:

- [x] Mitgliederseite listet offene, angenommene, abgelaufene und widerrufene
      Einladungen im autorisierten Aktionsscope.
- [x] Berechtigte Rolle kann offene Einladung widerrufen und mit begrenzter
      Rate erneut senden.
- [x] Falsche Adresse einer offenen Einladung wird durch Widerruf plus neue
      Einladung korrigiert, nie durch Mutation der Historie.
- [x] Aktive Login-E-Mail kann nur der System-Admin über einen
      Fresh-Login-geschützten Pending-Change-Workflow korrigieren.
- [x] Die neue Adresse muss Link oder Code bestätigen; erst dann wird sie
      atomar aktiv und alle Sessions werden widerrufen.
- [x] Bereits belegte Adresse, abgelaufene Bestätigung und konkurrierende
      Änderung werden verständlich abgewiesen.
- [x] Alte und neue Adresse erhalten angemessene Sicherheitsinformation,
      ohne Tokens oder unnötige Personendaten.
- [x] Mitglieder können ihre E-Mail weiterhin nicht selbst ändern.

Tests/Nachweise:

- [x] Unit-Tests prüfen Einladungslifecycle und Pending-Email-Change.
- [x] Integrationstest verwendet PostgreSQL, Worker und echten SMTP-Server.
- [x] E2E beweist Liste, Resend, Revoke, Korrektur, Bestätigung und
      Sessionentzug.
- [x] Abuse-Test prüft Enumeration, Rate Limits und Token-Replay.

Technischer Nachweis:
[`proofs/PILOT-013.md`](proofs/PILOT-013.md)

## 8. M2 – Produktive E-Mail

### [ ] PILOT-020 Providerneutralen produktiven Mail-Adapter einführen

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-001, PILOT-002

In Scope:

- `src/leonaid/adapters/mail/`
- `src/leonaid/configuration.py`
- `infra/compose/compose.yml`
- neue Produktionskonfiguration unter `infra/pilot/`
- Mail-/Outbox-Tests und Runbooks

Akzeptanzkriterien:

- [x] Produktcode verwendet generische `MAIL_*`-Konfiguration statt
      Mailpit-spezifischer Namen.
- [ ] Unterstützt werden die vom ausgewählten Provider benötigten
      SMTP-Transportmodi, Authentifizierung, Timeouts und Zertifikatsprüfung.
- [x] Mailpit bleibt realer lokaler/CI-SMTP-Server im expliziten
      Entwicklungsprofil.
- [x] API und Worker erhalten nur die jeweils erforderlichen Mail-Secrets.
- [x] Login, Einladung, E-Mail-Korrektur und Rechnungsversand verwenden
      denselben providerneutralen Outbox-Pfad.
- [x] Retry, Message-ID, Idempotenz und unveränderliches Rechnungsdokument
      bleiben erhalten.
- [x] Readiness unterscheidet fachkritischen Core und degradierte
      Mailzustellung.
- [x] Logs und Fehlermeldungen enthalten keine Adressen, Tokens,
      Zugangsdaten oder Mailinhalte.

Tests/Nachweise:

- [x] Bestehende Mailpit-Integrationstests bleiben grün.
- [ ] Providervertrag sendet über den offiziellen Sandbox-/Testmodus des
      ausgewählten realen Relays an ein kontrolliertes Testpostfach.
- [x] Falsches Zertifikat, Authfehler, Timeout und Provider-Limit werden real
      erzeugt und als sichere Outbox-Fehler klassifiziert.
- [x] Erfolgreicher Retry sendet exakt einmal.
- [x] `./leonaid test-mail-relay` ist grün.

### [ ] PILOT-021 Domainzustellung und Mailbetrieb freigeben

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-020

Akzeptanzkriterien:

- [ ] Absenderdomain, Envelope-From, sichtbarer From und Reply-To sind
      fachlich bestätigt.
- [ ] SPF, DKIM und DMARC werden für die Pilotdomain gesetzt und automatisiert
      gegen öffentliche DNS-Antworten geprüft.
- [ ] Login- und Rechnungs-E-Mails besitzen getrennt verständliche Betreffe,
      Texte und Supporthinweise.
- [ ] Bounce-/Complaint-Verhalten des Providers ist dokumentiert; permanente
      Fehler werden nicht endlos wiederholt.
- [ ] Ein benannter Operator kann Zustellfehler erkennen, sicher retryen und
      einen betroffenen Benutzer informieren.
- [ ] Mail-Runbook enthält Rotation, Provider-Ausfall und Rückkehr zu
      normalem Betrieb.

Tests/Nachweise:

- [ ] DNS-Contract prüft SPF, DKIM und DMARC über einen realen Resolver.
- [ ] Kontrolliertes externes Postfach empfängt Magic Link, Code,
      Einladung und Rechnung mit korrektem PDF.
- [ ] MIME, Links, Absender, Reply-To, Message-ID und PDF-SHA werden geprüft.
- [ ] Manueller Zustellbarkeitssmoke dokumentiert mindestens zwei
      unterschiedliche Mailanbieter, ohne Adressen zu committen.

## 9. M3 – Reale Bestandsdaten

### [ ] PILOT-030 Tatsächliche Excel-Datei privat analysieren und abbilden

Priorität: P1 · Aufwand: M–L · Risiko: hoch  
Abhängigkeiten: PILOT-001, PILOT-002

Akzeptanzkriterien:

- [ ] Originaldatei liegt ausschließlich unter `.local/pilot/intake/` oder
      in einem gleichwertig geschützten Intake Store.
- [ ] Vor Verarbeitung werden Quelle, Berechtigung, Zweck, Datum,
      verantwortliche Person und SHA-256 im privaten Manifest dokumentiert.
- [ ] Ein Coding-Agent erzeugt aus den tatsächlichen Headern ein
      versioniertes, personenbezugsfreies Mapping und eine synthetische
      Fixture mit gleicher Struktur.
- [ ] Pflichtfelder, Formate, leere Spalten, Formeln, Mehrfachblätter,
      Zeichensätze und Dubletten werden explizit bewertet.
- [ ] Fehlen stabile Source-IDs, wird eine fachlich stabile,
      wiederholbare Schlüsselstrategie definiert; Zeilennummern oder
      veränderliche Reihenfolge sind verboten.
- [ ] Fuzzy Matches werden nur als Kandidaten gemeldet und niemals
      automatisch zusammengeführt.
- [ ] Dry Run schreibt nicht nach Twenty oder Core.
- [ ] Report enthält pro Zeile Status, stabilen Fehlercode und Kandidaten,
      aber öffentliche Summen enthalten keine Personenwerte.

Tests/Nachweise:

- [ ] Synthetische Strukturfixture prüft jede reale Spalten-/Formatvariante.
- [ ] Absichtlich beschädigte Kopien prüfen fehlende Header, Formeln,
      doppelte IDs, ungültige E-Mail und mehrdeutige Matches.
- [ ] Dry Run gegen einen realen staging-Twenty-Snapshot erzeugt
      reproduzierbare Counts.
- [ ] Zweiter Dry Run mit identischem Fingerprint ist bytegleich bis auf
      zulässige Laufmetadaten.

STOP:

- Quelle oder Rechtsgrundlage unklar;
- Datei enthält Daten, die für den Pilotzweck nicht erforderlich sind und
  nicht vor Import entfernt werden können;
- Mapping würde eine automatische mehrdeutige Zusammenführung erfordern.

### [ ] PILOT-031 Staging-Import und Konfliktauflösung abnehmen

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-030, PILOT-040, PILOT-041

Akzeptanzkriterien:

- [ ] Staging verwendet reale, gepinnte Twenty-/Core-/RustFS-Dienste und eine
      vom Produktionsziel getrennte Installation.
- [ ] Vor Apply existieren Recovery Point, Dry-Run-Fingerprint und
      Vier-Augen-Freigabe.
- [ ] Konflikte werden in einer privaten Resolution-Datei mit Ziel-ID,
      Entscheidung, Entscheider und Zeitstempel aufgelöst.
- [ ] Apply akzeptiert ausschließlich exakt den freigegebenen
      Input-/Mapping-/Resolution-Fingerprint.
- [ ] Abgewiesene Zeilen verändern keine Daten.
- [ ] Wiederholung erzeugt keine Duplikate und keine unnötigen Updates.
- [ ] Twenty-IDs, Core-Referenzen, Firmen-/Personen-Counts und
      Stichprobenfelder werden nach Apply geprüft.
- [ ] Restore auf den Recovery Point ist nach realem Apply erfolgreich.

Tests/Nachweise:

- [ ] `./leonaid test-pilot-import` führt Dry Run, Apply, Wiederholung und
      Restore gegen isolierte reale Dienste aus.
- [ ] Concurrency-Test verhindert paralleles Apply desselben Batches.
- [ ] Manipulierter Fingerprint und unaufgelöster Konflikt werden
      fail-closed abgewiesen.
- [ ] Sanitizter Summenreport wird im Proof verlinkt.

### [ ] PILOT-032 Produktionsimport kontrolliert durchführen

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-031, PILOT-043, PILOT-044

Akzeptanzkriterien:

- [ ] Produktives Ziel, Importbatch, Mapping, Resolution und Recovery Point
      sind eindeutig bestätigt.
- [ ] Import läuft im dokumentierten Wartungsfenster über
      `./leonaid pilot-import apply`, nicht über ad-hoc SQL oder Twenty-UI.
- [ ] Apply prüft vor dem ersten Write den freigegebenen Dry-Run-Fingerprint.
- [ ] Nachlauf verifiziert Counts, referenzielle Integrität, Stichproben und
      idempotenten zweiten Lauf.
- [ ] Fehler führt zu dokumentierter Stop-/Restore-Entscheidung; Teilresultate
      werden nicht manuell „zurechtgebogen“.
- [ ] Personenbezogene Reports bleiben privat; der versionierte Proof enthält
      nur Summen, Hashes und Evidence-IDs.
- [ ] Produktverantwortlicher und Operator zeichnen Ergebnis ab.

Tests/Nachweise:

- [ ] Private Produktions-Checkliste vollständig.
- [ ] Vorher-/Nachher-Snapshot und AuditEvents stimmen.
- [ ] Zweiter `verify`-Lauf meldet null ungeklärte Konflikte und null
      technische Duplikate.
- [ ] Wiederanlauf der Anwendung und alle Pilot-Persona-Smokes sind grün.

## 10. M4 – Produktiver Single-Host-Betrieb

### [ ] PILOT-040 Produktions- und Staging-Topologie härten

Priorität: P1 · Aufwand: L · Risiko: hoch  
Abhängigkeiten: PILOT-001, PILOT-002

In Scope:

- bestehendes `infra/compose/compose.yml` als Basis;
- additive, minimale Produktionskonfiguration unter `infra/pilot/`;
- `infra/proxy/`, `.env.example`, `src/leonaid/configuration.py`;
- `./leonaid pilot-doctor` und Deployment-Runbook.

Akzeptanzkriterien:

- [x] Staging und Produktion besitzen getrennte Domains, Compose-Projekte,
      Volumes, Buckets, Datenbanken, Secrets und Mailkonfigurationen.
- [x] Produktion exponiert ausschließlich Caddy auf 80/443; Datenbanken,
      Redis, RustFS und interne APIs besitzen keine öffentlichen Hostports.
- [ ] Caddy verwendet öffentlich vertrauenswürdiges TLS, sichere Header,
      HSTS nach erfolgreichem Staging und dokumentierte Zertifikatserneuerung.
- [x] `LEONAID_ENV=production` verbietet Mailpit, `.invalid`-Absender,
      lokale Backupziele, Default-Secrets und Loopback-Public-URLs.
- [x] Secrets liegen außerhalb des Repositorys und werden mit
      Least-Privilege in Container injiziert.
- [x] Images und externe Systeme bleiben tag- und digest-gepinnt.
- [x] `pilot-doctor` prüft DNS, TLS, Secrets, Uhrzeit, Speicherplatz,
      Backupalter, Provider und alle Abhängigkeiten ohne Geheimnisse
      auszugeben.
- [x] Produktion wird ausschließlich aus einem freigegebenen Commit/Manifest
      aufgebaut; kein Live-Code-Mount.

Tests/Nachweise:

- [x] Compose-Contract prüft Netzwerk- und Portgrenzen.
- [x] Test mit synthetischen unsicheren Produktionswerten muss fail-closed
      abbrechen.
- [ ] TLS-/Header-Test läuft gegen die echte Stagingdomain.
- [x] `./leonaid test-pilot-deployment` startet eine produktionsähnliche
      isolierte Topologie aus leeren Volumes.

Technischer Nachweis und verbleibende reale Staging-Grenze:
[`proofs/PILOT-040.md`](proofs/PILOT-040.md)

### [ ] PILOT-041 Externes Backup und isolierten Restore betreiben

Priorität: P1 · Aufwand: M · Risiko: hoch  
Abhängigkeiten: PILOT-040

Bestehende Basis:
`infra/backup/` beweist verschlüsselte Cross-System-Backups mit Restic. Der
Pilot ergänzt das reale Off-Host-Ziel und den Betreiberprozess.

Akzeptanzkriterien:

- [ ] Backupziel liegt außerhalb des Pilot-VPS und verwendet getrennte,
      rotierbare Credentials.
- [x] Core PostgreSQL, Twenty-Daten/-Konfiguration, RustFS-Objekte und
      erforderliche Manifeste werden gemeinsam gesichert.
- [x] Zeitplan, Aufbewahrung, Prune, Integritätsprüfung, RPO und RTO sind
      entschieden und überwacht.
- [ ] Backupfehler alarmiert den Operator.
- [x] Restore verweigert Quellprojekt, nicht leeres Ziel und unbestätigte
      Umgebung.
- [x] Ein vollständiger Restore läuft regelmäßig in ein isoliertes Ziel und
      prüft Golden-/Pilot-Summen sowie Dokument-SHAs.
- [x] Private Backupinhalte erscheinen nicht in Logs oder CI-Artefakten.

Tests/Nachweise:

- [x] `./leonaid test-pilot-backup` verwendet das reale externe
      Restic-Testrepository und frische Zielvolumes.
- [x] Falsches Passwort, unvollständiger Snapshot, volles Ziel und
      Netzwerkunterbrechung werden real erzeugt.
- [x] Gemessenes RPO/RTO erfüllt das Register.
- [ ] Operator führt einen dokumentierten Restore ohne Implementiererhilfe
      aus.

Technischer Nachweis und verbleibende Betreibergrenze:
[`proofs/PILOT-041.md`](proofs/PILOT-041.md)

### [ ] PILOT-042 Monitoring und reale Alarmkette aktivieren

Priorität: P1 · Aufwand: M–L · Risiko: mittel  
Abhängigkeiten: PILOT-040, PILOT-041, PILOT-020

Akzeptanzkriterien:

- [x] Metriken decken HTTP-Fehler/Latenz, Abhängigkeiten, Outbox/Dead Letter,
      Loginfehler, Backupalter, Plattenplatz und Zertifikatsablauf ab.
- [x] Logs bleiben strukturiert, korreliert und payloadfrei.
- [x] Ein ausgewähltes reales Monitoring-/Alerting-System ist exakt gepinnt
      oder als externer Dienst vertraglich dokumentiert.
- [x] P0/P1/P2-Regeln besitzen Owner, Schwellwert, Deduplizierung,
      Eskalationskanal und Runbook-Link.
- [x] Alarmkanal ist nicht ausschließlich vom ausgefallenen LeonAid-Mailpfad
      abhängig.
- [x] System-Admin-UI zeigt denselben Zustand verständlich, ohne Rohmetriken
      vorauszusetzen.
- [x] Wartungsmodus unterdrückt erwartete Alarme, aber niemals
      Backup-/Security-Alarme.

Tests/Nachweise:

- [x] `./leonaid test-pilot-alerting` stoppt nacheinander Twenty, RustFS,
      Mail und Worker und prüft echte Alarmzustellung plus Recovery.
- [x] Überfüllter Datenträger und veraltetes Backup werden in isolierter
      Umgebung real simuliert.
- [x] Canary mit synthetischer PII beweist, dass Alarmtexte keine Payload
      enthalten.
- [ ] Operator quittiert einen Alarm und führt das verlinkte Runbook aus.

Technischer Nachweis und verbleibende Betreibergrenze:
[`proofs/PILOT-042.md`](proofs/PILOT-042.md)

### [ ] PILOT-043 Release, Migration, Rollback und Wartungsfenster beweisen

Priorität: P1 · Aufwand: L · Risiko: hoch  
Abhängigkeiten: PILOT-040, PILOT-041, PILOT-042

Akzeptanzkriterien:

- [x] Release-Manifest bindet Git-Commit, Images/Digests,
      Schema-/Templateversionen und erforderliche Migrationen.
- [x] Staging erhält exakt dasselbe Manifest vor Produktion.
- [x] Deployment aktiviert bei inkompatiblen Änderungen Wartungsmodus,
      erstellt Recovery Point und prüft Vorbedingungen.
- [x] Datenbank-, Twenty- und RustFS-Migrationen laufen fail-closed.
- [x] Smoke- und Readiness-Gates entscheiden automatisch über Freigabe.
- [x] Rollbackgrenze und Vorwärtsreparatur sind je Komponente dokumentiert.
- [x] Produktion baut keine Images und löst keine Abhängigkeiten neu auf.
- [ ] Operator kann letzten freigegebenen Releasezustand ohne direkte
      Datenbankarbeit wiederherstellen.

Tests/Nachweise:

- [x] `./leonaid test-pilot-release` promoted zwei reale Versionen durch
      Staging, erzeugt einen absichtlichen Migrationsfehler und rollt sauber
      zurück.
- [x] Golden Journey läuft vor und nach Upgrade/Rollback.
- [x] Audit/Releaseprotokoll enthält keine Secrets.
- [x] Recovery Point und alle Dokument-SHAs stimmen nach Rollback.

Technischer Nachweis und verbleibende Betreibergrenze:
[`proofs/PILOT-043.md`](proofs/PILOT-043.md)

### [ ] PILOT-044 Reale Träger-, Rechnungs- und Datenschutzkonfiguration freigeben

Priorität: P1 · Aufwand: M–L · Risiko: hoch  
Abhängigkeiten: PILOT-001, PILOT-002, PILOT-040, PILOT-043

Akzeptanzkriterien:

- [x] Reale Trägerdaten werden ausschließlich über eine autorisierte,
      auditierte Konfiguration gepflegt und nicht im Repository hinterlegt.
- [ ] Rechnungsaussteller, Nummernkreis, Steuerfall, Pflichttexte,
      Zahlungsziel und Bank-/Kontaktangaben sind fachlich bestätigt.
- [ ] E-Rechnungsentscheidung ist dokumentiert; erforderlicher zusätzlicher
      Scope blockiert den Pilot.
- [x] Aufbewahrungs-/Löschregeln sind konfigurierbar, versioniert und mit
      Rechnungssnapshots vereinbar.
- [ ] Public-Form-Texte und Consent-Versionen entsprechen der bestätigten
      Rechtsgrundlage.
- [ ] Datenschutzexport und Erasure berücksichtigen reale Fristen,
      Sperrgründe und Twenty-/RustFS-Referenzen.
- [x] Preview und Vier-Augen-Freigabe verhindern versehentliche Verwendung
      synthetischer Golden-Trägerdaten in Produktion.

Tests/Nachweise:

- [x] `./leonaid test-pilot-legal-config` lehnt Golden-/`.invalid`-Werte,
      offene Entscheidungen und widersprüchliche Fristen in Produktion ab.
- [ ] Realer Staging-Beleg wird inhaltlich durch verantwortliche Fachperson
      abgenommen; nur dessen SHA/Evidence-ID wird versioniert.
- [x] Privacy-Integration prüft Aufbewahren eines Rechnungs-Snapshots bei
      gleichzeitiger Anonymisierung nicht aufbewahrungspflichtiger Daten.
- [ ] Produktivfreigabe von Träger, Datenschutz und erforderlicher
      Steuerberatung ist protokolliert.

Technischer Nachweis, Bedienrunbook und verbleibende Fach-/Integrationsgrenzen:
[`proofs/PILOT-044.md`](proofs/PILOT-044.md)

## 11. M5 – Pilotdurchführung und Freigabe

### [ ] PILOT-050 Vollständige produktionsnahe Generalprobe durchführen

Priorität: P1 · Aufwand: L · Risiko: hoch  
Abhängigkeiten: PILOT-013, PILOT-021, PILOT-031, PILOT-044

Akzeptanzkriterien:

- [ ] Staging wird aus leeren Volumes mit dem freigegebenen Release-Manifest
      aufgebaut.
- [ ] Reale Provider, externe Backups, DNS/TLS und Alarmkanal sind aktiv.
- [ ] Ein kontrollierter, rechtmäßig verwendbarer Pilotdatensatz wird über
      den freigegebenen Importweg eingespielt.
- [ ] Sämtliche Personas durchlaufen Einladung, Login, Sponsor,
      Mehrfachzuordnung, interne/öffentliche Bestellung, Feed, Rechnung,
      PDF, Mail, Zahlung und Dashboard.
- [ ] Benutzer-Sperre, Rollenwechsel, Sessionentzug und E-Mail-Korrektur
      werden über UI bedient.
- [ ] Mail-, Twenty-, RustFS- und Worker-Ausfall werden erkannt und nach
      Runbook behoben.
- [ ] Backup und Restore stellen exakt denselben Fachstand in einem frischen
      Ziel wieder her.
- [ ] Keine direkte Datenbankarbeit oder Implementierer-Sonderhandlung ist
      erforderlich.

Tests/Nachweise:

- [ ] `./leonaid test-pilot-rehearsal` ist aus leerem Zustand grün.
- [x] `./leonaid test-pilot-rehearsal --synthetic` ist aus leerem Zustand
      auf realen isolierten Diensten grün und erklärt ausdrücklich keine
      Produktionsbereitschaft.
- [x] Automatisierte synthetische Journey läuft in Chromium, Firefox und
      WebKit.
- [x] Kritische Operatorstrecken werden zusätzlich sichtbar im
      In-App-Browser ausgeführt.
- [ ] Private reale Evidence und öffentlicher sanitizter Summenproof sind
      vollständig.
- [ ] P0/P1-Befunde sind geschlossen; P2 besitzt Owner und Pilotentscheid.

Technischer synthetischer Nachweis und verbleibende externe Gates:
[`proofs/PILOT-050.md`](proofs/PILOT-050.md)

### [ ] PILOT-051 Pilotnutzer onboarden und Supportfähigkeit beweisen

Priorität: P1 · Aufwand: M · Risiko: mittel  
Abhängigkeiten: PILOT-050

Akzeptanzkriterien:

- [ ] Pilotkreis, Rollen, Supportweg, Datenschutzinformation und
      Nutzungszeitraum sind bestätigt.
- [ ] Jede reale Person erhält einen individuellen Account; keine geteilten
      Produktions-Testkonten.
- [ ] Charity-Admin und System-Admin führen Einladung, Rollenwechsel,
      Sperre und Sessionentzug anhand des Runbooks selbst aus.
- [ ] Akquisiteur, Charity-Admin und Finanzen erledigen ihre Kernaufgaben
      ohne Datenbankwissen oder interne IDs.
- [x] Hilfetexte, Fehlermeldungen und Supportdiagnose nennen Auswirkung und
      nächsten Schritt.
- [ ] Feedback wird ohne geheime oder unnötige personenbezogene Daten
      erfasst, priorisiert und einem Release zugeordnet.
- [ ] P0/P1-Usability- und Accessibility-Befunde sind vor Aktivierung
      geschlossen.

Tests/Nachweise:

- [ ] Moderierte Sessions mit mindestens einem Nutzer je interner Persona
      sind protokolliert.
- [x] Tastatur-, 200%-Zoom-, automatisierter A11y- und Mobil-Smoke sind
      technisch grün.
- [ ] VoiceOver- oder gleichwertiger echter Screenreader-Smoke ist mit einer
      realen Pilotpersona protokolliert.
- [ ] Ein unbeteiligter Operator führt Onboarding und Offboarding nur anhand
      der Dokumentation aus.
- [x] Technische Supportübung korreliert einen Browserfehler bis zum Backend,
      ohne
      Payloadzugriff.

Technischer Teilnachweis und verbleibende externe Gates:
[`proofs/PILOT-051.md`](proofs/PILOT-051.md)

### [ ] PILOT-052 Begrenzten Live-Pilot sicher durchführen

Priorität: P1 · Aufwand: L · Risiko: hoch  
Abhängigkeiten: PILOT-051, PILOT-032

Akzeptanzkriterien:

- [ ] Go-Live-Zeitpunkt, Pilotdauer, Nutzerzahl, öffentliche URL und
      Abbruchkriterien sind festgelegt.
- [ ] Public Form wird kontrolliert aktiviert; Archiv-/Alias-Vertrag bleibt
      unverändert.
- [ ] Tägliche Betriebsprüfung deckt Backup, Alerts, Outbox, Speicher,
      Zertifikat und Abhängigkeiten ab.
- [x] Der technische Tagesreport führt Backup, Alerts, Outbox, Speicher,
      Zertifikat und alle vier Kernabhängigkeiten serverseitig zusammen,
      bewertet sie mit stabilen Stop-Gründen und besitzt eine kanonische
      SHA-256-Prüfsumme.
- [ ] Reale Bestellungen, Rechnungen und Zahlungen bleiben fachlich
      nachvollziehbar und auditierbar.
- [ ] Support- und Incidentfälle werden nach Runbook bearbeitet.
- [ ] Kein P0/P1 bleibt offen; bei Datenschutz-, Autorisierungs- oder
      Datenverlustverdacht wird der Pilot sofort gestoppt.
- [ ] Pilotdaten werden nach Ende gemäß bestätigter Fristen weitergeführt,
      exportiert, gesperrt oder gelöscht.

Tests/Nachweise:

- [ ] Tägliche sanitizte Betriebsreports besitzen keine PII.
- [x] Der Reportvertrag, der geschützte Download und die Darstellung wurden
      ohne Mocks gegen PostgreSQL, Twenty, RustFS, Mailpit, Worker, API und
      Web sowie mit gezielten Dienstausfällen bewiesen.
- [ ] Mindestens ein realer interner und ein realer öffentlicher
      End-to-End-Vorgang wird fachlich bestätigt.
- [ ] Backup-Restore-Smoke und Alarm-Canary laufen während des Pilotfensters.
- [ ] Abschlussreport enthält Volumen, Fehlerraten, Supportfälle,
      Wiederanläufe und offene P2/P3 ohne Personenbezug.

Technischer Teilnachweis und verbleibende Live-Gates:
[`proofs/PILOT-052.md`](proofs/PILOT-052.md)

### [ ] PILOT-053 Pilot abnehmen und nächsten Produktmilestone entscheiden

Priorität: P1 · Aufwand: M · Risiko: mittel  
Abhängigkeiten: PILOT-052

Akzeptanzkriterien:

- [ ] Alle Tasks PILOT-000 bis PILOT-052 sind vollständig bewiesen.
- [ ] Keine ungeklärten P0/P1-, Security-, Datenschutz- oder
      Datenverlustbefunde sind offen.
- [ ] Produktverantwortlicher, Betrieb und erforderliche Fachrollen nehmen
      den Pilotumfang ausdrücklich ab.
- [ ] Runbooks, Architektur, Datenmodell, API, Personas, bekannte Grenzen und
      Entscheidungsregister entsprechen dem real betriebenen Stand.
- [x] Ein fail-closed Readiness-Dossier bewertet alle Tasks, offenen
      Kriterien, Abhängigkeiten, Proof-Links, 16 Hard-Gates,
      Pilotentscheidungen und den Git-Zustand, ohne externe Abnahmen als
      erfüllt zu simulieren.
- [ ] Finaler Cold-CI-Lauf und produktionsnahe Generalprobe veröffentlichen
      sanitizte Beweisartefakte.
- [ ] Private Pilot-Evidence ist vollständig, zugriffsgeschützt und besitzt
      eine festgelegte Aufbewahrung.
- [ ] Entscheidung für den nächsten Milestone ist dokumentiert:
      Krapfentaxi-Delivery, weiteres Pilothardening oder Lions-Open-Discovery.
- [ ] Der Pilot wird nicht automatisch zur unbefristeten Produktivfreigabe;
      Betriebs- und Verantwortungsübergang sind ausdrücklich entschieden.

Tests/Nachweise:

- [x] `./leonaid test-pilot-readiness` prüft sämtliche harten Gates und
      Proof-Links.
- [ ] Finaler Docker-Cold-Run startet ohne Caches aus leerem Zustand.
- [ ] Abnahmeprotokoll verlinkt Commit, Release-Manifest, Locks,
      Golden-Version, private Evidence-IDs, CI, Restore, Screenshots,
      Beleg-SHAs und Runbooks.
- [ ] Abschlusscommit ist auf `main`, Remote-CI terminal grün und das
      Arbeitsverzeichnis sauber.

Technischer Teilnachweis und verbleibende Abnahme-Gates:
[`proofs/PILOT-053.md`](proofs/PILOT-053.md)

## 12. Harte Pilot-Abnahmematrix

| Gate-ID | Gate | Primäre Tasks |
| --- | --- | --- |
| PILOT-GATE-001 | Keine realen Daten in Git/öffentlicher CI | PILOT-002, PILOT-030, PILOT-053 |
| PILOT-GATE-002 | Keine Benutzerverwaltung per SQL | PILOT-010 bis PILOT-013 |
| PILOT-GATE-003 | Sperre entzieht Sitzungen sofort | PILOT-011 |
| PILOT-GATE-004 | Rollen wirken im nächsten Request | PILOT-012 |
| PILOT-GATE-005 | Charity-Admin bleibt auf eigene Aktionen begrenzt | PILOT-010, PILOT-012 |
| PILOT-GATE-006 | Produktiver Mailweg real bewiesen | PILOT-020, PILOT-021 |
| PILOT-GATE-007 | Import ist Dry-Run-first, konfliktbewusst und idempotent | PILOT-030 bis PILOT-032 |
| PILOT-GATE-008 | Produktion besitzt keine lokalen/Test-Defaults | PILOT-040 |
| PILOT-GATE-009 | Externer Backup-Restore erfüllt RPO/RTO | PILOT-041 |
| PILOT-GATE-010 | Reale Alarmkette und Runbooks funktionieren | PILOT-042 |
| PILOT-GATE-011 | Release/Rollback verwendet exakt gepinnte Artefakte | PILOT-043 |
| PILOT-GATE-012 | Träger-, Steuer- und Datenschutzentscheidungen geschlossen | PILOT-001, PILOT-044 |
| PILOT-GATE-013 | Generalprobe ohne Implementierer-Sonderweg | PILOT-050 |
| PILOT-GATE-014 | Alle Personas sind mit realen Diensten bedienbar | PILOT-050, PILOT-051 |
| PILOT-GATE-015 | Live-Pilot besitzt Stopkriterien und Incidentweg | PILOT-052 |
| PILOT-GATE-016 | World-class UX/DX, A11y und mobile Bedienung | PILOT-010 bis PILOT-013, PILOT-051 |

Kein Matrixeintrag gilt aufgrund eines Screenshots allein, eines manuellen
Datenbankeingriffs, eines Mock-Servers oder einer nicht reproduzierbaren
Operatoraussage als bewiesen.

## 13. STOP-Bedingungen für den gesamten Milestone

Implementierung beziehungsweise Aktivierung stoppen und an den
Produktverantwortlichen berichten, wenn:

- die Live-Codebasis den hier dokumentierten Ausgangsverträgen widerspricht
  und der Task nicht ohne Scopeänderung aktualisiert werden kann;
- eine rechtliche oder steuerliche Pflicht einen ausgeschlossenen
  Funktionsbereich zwingend erforderlich macht;
- reale Daten ohne dokumentierte Quelle, Zweckbindung oder Berechtigung
  bereitgestellt werden;
- ein Import nur durch automatische mehrdeutige Zusammenführung möglich
  wäre;
- der produktive Mailprovider, Backupstore oder Alarmkanal nicht real
  getestet werden kann;
- ein Task direkte produktive Datenbankänderungen erfordern würde;
- ein Test zweimal nach vernünftiger Korrektur fehlschlägt und die Ursache
  nicht innerhalb des Task-Scope liegt;
- ein P0/P1-, Datenschutz-, Autorisierungs- oder Datenverlustbefund offen ist;
- ein produktiver Schritt kein verifiziertes Backup und keinen
  Rückkehrpfad besitzt.

## 14. Grobe Aufwandsorientierung

Diese Werte sind keine Abnahmekriterien und hängen besonders von externen
Freigaben, der Excel-Qualität und Provider-Onboarding ab:

| Abschnitt | Orientierung für zwei Personen |
| --- | --- |
| M0 Vertrag und Entscheidungen | 2–5 Arbeitstage plus externe Freigaben |
| M1 Benutzeradministration | 2–3 Wochen |
| M2 Produktive E-Mail | 3–7 Arbeitstage plus DNS/Provider |
| M3 Bestandsdaten | 3–10 Arbeitstage nach Erhalt der Excel-Datei |
| M4 Produktiver Betrieb | 2–3 Wochen |
| M5 Generalprobe und Pilot | 1–2 Wochen Umsetzung plus Pilotkalender |

Der kritische Pfad verläuft über PILOT-001, PILOT-002, PILOT-040,
PILOT-041, PILOT-044, PILOT-050 und die tatsächliche Pilotdauer.

## 15. Wartungsnotizen

- Der neutrale `CharityAction`-Kern darf nicht wieder zu einem
  Krapfentaxi-Sondermodell werden.
- Der Mail-Adapter bleibt providerneutral; Providerdetails gehören in
  Konfiguration und Adapter, nicht in Domain/Application Services.
- Reale Importsonderfälle werden zuerst als synthetische Regression-Fixture
  abgebildet. Die Originalzeile wird nie committed.
- Benutzeradministration verwendet bestehende Account-/Membership-Domainregeln
  und zentrale Policies; keine UI-only-Rechteprüfung.
- Neue Betriebsdienste werden nur aufgenommen, wenn Version, Digest,
  Backup-/Upgradepfad, Healthcheck und Owner geklärt sind.
- `PERSONAS.md`, OpenAPI, generierter Client, Runbooks und Known Limits werden
  im selben Task wie die zugehörige Rollen-/API-/Betriebsänderung aktualisiert.
- Tourenplanung beginnt frühestens nach PILOT-053 als eigener
  Capability-Milestone.
