# Modulare LeonAid-Plattform: Implementierungsspec

Stand: 13.09.2026. Status: in Umsetzung; geprüfte Slices siehe [PROGRESS.md](PROGRESS.md).
Gelesener Ausgangsstand: `2043b72` (Krapfentaxi-Lieferfenster und Lieferkontakte).

## 1. Ziel und Umfang

LeonAid wird schrittweise als modularer Monolith organisiert. Fachmodule besitzen ihre Daten, bieten typisierte Aufrufe an und registrieren ihre Oberflächen und Hintergrundaufgaben explizit. Neue Funktionen sollen vorhandene Fachobjekte wiederverwenden, ohne weitere Dienste oder parallele Datenbestände vorauszusetzen.

Diese Spec definiert die technische Grundlage und drei aufeinander aufbauende Nachweise: Surveys als bestehendes Modul, Tasks mit Wissensseiten und Materialien als zusammengesetzter Ablauf sowie Inbox mit dauerhafter CRM-Synchronisation. Jede Etappe wird separat implementiert und abgenommen. Die Umsetzung von M0 bis M3 erfolgt auf dem bestehenden Draft-PR; nach jedem abgeschlossenen Slice wird der geprüfte Stand gepusht.

Verbindliche Leitlinien:

- Ein API-Prozess, ein vorhandener Worker-Dienst und die vorhandene Core-PostgreSQL-Datenbank bleiben das Betriebsmodell. Modulanzahl erhöht nicht die Containeranzahl.
- Fachzustände haben genau einen Eigentümer. Ansichten, Einbettungen und Verknüpfungen referenzieren diesen Zustand.
- Direkte Python-Aufrufe innerhalb des Core; HTTP für externe Clients. Kein internes HTTP zwischen Modulen.
- FastAPI bleibt das HTTP-Framework des Python-Backends. Ein späterer FastMCP-Adapter kann dieselben autorisierten Fachoperationen verwenden; FastMCP wird in M0–M3 noch nicht eingebaut.
- Vorhandene Rechte-, Audit-, Idempotenz-, S3-, CRM- und Outbox-Funktionen wiederverwenden.
- Explizite Registrierung zur Build-/Startzeit; keine dynamische Plugininstallation.
- Abstraktionen erst für einen konkreten zweiten Bedarf erweitern. Keine Universalobjekte, generischen Workflow-Designer oder Command-Bus-Infrastruktur.
- Kein vollständiger Datei- oder Tabellenumbau vor der ersten nutzbaren Etappe.

Nicht Bestandteil: Microservices, Module Federation, ein eigener Dienst pro Modul, ein allgemeines Plugin-SDK als veröffentlichtes Paket, MCP-Server, Temporal, Redis als neue LeonAid-Queue, semantische Suche, OCR, Echtzeit-Coediting oder frei konfigurierbare Dashboards. Bestehende Infrastruktur anderer Produkte bleibt unabhängig davon erhalten.

## 2. Verifizierter Ausgangspunkt

| Einstieg                                                               | Befund und Konsequenz                                                                                                              |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| [Domain/Application](../../src/leonaid/application/action_progress.py) | Application-Service mit Unit of Work, Audit, Command Receipt und transaktionaler Outbox vorhanden. Muster gezielt wiederverwenden. |
| [Identität/Navigation](../../src/leonaid/application/identity.py)      | `navigation_for` setzt Navigation zentral zusammen. Server bleibt maßgeblich für erlaubte Einstiege.                               |
| [Web](../../apps/web/src/app.tsx), [PWA](../../apps/pwa/src/app.tsx)   | App-Einstiege und Seitenauswahl sind zentral verdrahtet. Gemeinsam genutzte Features existieren bereits.                           |
| [FastAPI](../../src/leonaid/entrypoints/fastapi/platform.py)           | Zentrale Komposition; Surveys besitzen bereits einen separaten Router. Migration kann dort beginnen.                               |
| [Outbox-Modell](../../src/leonaid/domain/outbox.py)                    | Retry mit begrenztem exponentiellem Backoff; `PendingOutboxEvent` enthält noch keinen expliziten Einplanungszeitpunkt.             |
| [PostgreSQL-Queue](../../src/leonaid/adapters/postgres/outbox.py)      | `available_at`, `SKIP LOCKED`, Lease und Claim-Token, Dead Letters und manueller Retry vorhanden.                                  |
| [Worker](../../src/leonaid/entrypoints/worker/outbox.py)               | Explizite Handler-Zuordnung vorhanden. Ein Ereignistyp wird einem Handler zugeordnet.                                              |
| [Worker-Prozess](../../src/leonaid/entrypoints/worker/platform.py)     | Serielle Verarbeitung; eigener Survey-Sweep für Fristen und Aufbewahrung. Keine allgemeine Scheduler-Verwaltung.                   |
| [Architekturtest](../../tests/unit/test_architecture_boundaries.py)    | Schichtentests vorhanden; ein Teil scannt nur unmittelbare Python-Dateien. Rekursive Modulprüfung ergänzen.                        |
| [Compose](../../infra/compose/compose.yml)                             | API, Worker und Core-Datenbank vorhanden. Diese Spec benötigt keine zusätzliche Infrastruktur.                                     |

Vor Beginn einer Umsetzung den dann aktuellen Hauptbranch gegen diese Befunde abgleichen. Insbesondere bestehende Survey-, Rechte- und Recovery-Pfade nicht anhand dieser Momentaufnahme ersetzen.

## 3. Modulzuschnitt und Datenverantwortung

| Modul                   | Eigentum                                                                               | Öffentliche Zusammenarbeit                                                             |
| ----------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Aktionen                | Aktionsidentität, Lebenszyklus und aktionsbezogene Zuordnungen                         | Kontext und erlaubte Aktionsoperationen                                                |
| Tasks                   | Listen, Epics, Tasks, persönliche Zuständigkeit, Fälligkeit, Zurückstellung            | Erstellen, lesen, zuweisen, erledigen und zurückstellen                                |
| Wissen                  | Seiten, Revisionen, Vorlagen und Objektverweise                                        | Seiten lesen/speichern; Fachobjekte referenzieren                                      |
| Materialien             | Metadaten, Dateiversionen und Verknüpfungen                                            | Upload-/Download-Autorisierung und Versionsreferenzen; Bytes im bestehenden S3-Backend |
| Inbox                   | Fall, Eingangsnachricht, Zuständigkeit, Bearbeitungsstatus und Kontaktzuordnungsstatus | Fallbearbeitung; Task-/Materialverweise; Twenty über vorhandenen Adapter               |
| Surveys                 | Bestehende Survey-Definitionen, Antworten und Prozesse                                 | Bestehende Use Cases erhalten und als Modul exponieren                                 |
| Bestehende Fachbereiche | Akquise, Bestellungen, Rechnungen, Lieferung behalten ihre Zustände                    | Nur benötigte Anwendungsoperationen veröffentlichen                                    |

Gemeinsame Identitätsverträge, Berechtigungsmechanismen, Audit-Infrastruktur, Datenbankverbindung und technische Adapter gehören zur Plattform. Fachliche Berechtigungsregeln und Audit-Anlässe bleiben beim jeweiligen Modul. Twenty bleibt Quelle für Personen/Organisationen. Öffentliche Darstellung erhält ausdrücklich veröffentlichbare Core-Daten; redaktionelle Inhalte bleiben im bestehenden CMS-Pfad. „LeonAid Core“ bezeichnet weiterhin das gesamte Backend, nicht einen neuen Sammelordner für Fachlogik.

Suche, „Für mich“, Aktionsübersicht und öffentliche Clubübersicht sind Projektionen bzw. zusammengesetzte Abfragen. Sie schreiben keine fremden Fachzustände. Ein Album referenziert Materialien. Ein Task im Text ist ein Task des Tasks-Moduls. Ein erledigter Task verändert keine Rechnung, Bestellung oder Lieferung.

### 3.1 Gemeinsamer Python-Namespace und Zuständigkeiten

Das Backend bleibt unter dem gemeinsamen Python-Namespace `leonaid`. Fachliche Module benötigen zunächst weder separate installierbare Pakete noch eigene `pyproject.toml`-Dateien. Zielstruktur:

```text
src/leonaid/
  platform/       # gemeinsame technische Dienste und Verträge
  modules/        # Fachobjekte, Regeln und öffentliche Fachoperationen
    actions/
    tasks/
    knowledge/
    materials/
    inbox/
    surveys/
    invoicing/
    delivery/
  bootstrap/      # konkrete Verdrahtung und statische Modulregistrierung
  entrypoints/    # API- und Worker-Prozessstart
```

Die Modulnamen illustrieren das Zielbild und sind keine Pflicht, leere Verzeichnisse vorab anzulegen. `platform/`, `modules/` und `bootstrap/` trennen technische Grundlage, Fachlogik und Zusammenstellung der Anwendung. `platform/` enthält insbesondere keine Aktions-, Aufgaben- oder Rechnungsregeln und wird nicht zum allgemeinen `utils`-Sammelbereich. Die technische Queue gehört zur Plattform, ihre fachlichen Handler zu den Modulen.

Verbindliche Abhängigkeitsrichtung:

```text
entrypoints -> bootstrap -> modules -> platform
                      \-------------> platform
```

`bootstrap/` kennt konkrete Modulimplementierungen und Plattformadapter und injiziert die benötigten Abhängigkeiten. Module importieren weder `bootstrap/` noch Prozess-Entrypoints. `platform/` importiert weder Fachmodule noch deren Registrierung. Module dürfen gezielt öffentliche APIs anderer Module verwenden, sofern keine Zyklen entstehen. Domain-/Service-Code verwendet dabei Verträge statt konkreter Infrastrukturadapter; die Schichtengrenze gilt auch innerhalb der Plattform.

Die bestehenden Schichtverzeichnisse werden pro bearbeitetem Bereich migriert. Geeignete vorhandene Plattformfunktionen zunächst weiterverwenden und erst bei der jeweiligen Migration verschieben; keine zweite Implementierung derselben Dienste. Vorhandene Startbefehle und Modulpfade der Prozesse bleiben kompatibel. Die benannten Abhängigkeitsregeln gelten für den migrierten Code sofort; unvermeidbare Alt-Kanten werden einzeln mit Entfernungsetappe dokumentiert.

### 3.2 Struktur eines Fachmoduls und Importregeln

Neue Module beginnen unter `src/leonaid/modules/<name>/`. Beispiel, keine Pflichtdateiliste:

```text
modules/tasks/
  api.py          # öffentliche Typen und aufrufbare Anwendungsoperationen
  service.py      # Regeln und Abläufe, sofern api.py sonst zu groß wird
  repository.py   # konkreter PostgreSQL-Zugriff
  routes.py       # HTTP-Adapter, falls benötigt
  jobs.py         # Handler, falls benötigt
```

`api.py` ist ein Importvertrag, kein Service Locator. Konkrete Instanzen und Abhängigkeiten verdrahtet der Composition Root unter `bootstrap/`. Öffentliche Signaturen enthalten keine FastAPI-Requests, Datenbankverbindungen, Queue-Zeilen oder ORM-Objekte. Domain-/Service-Code importiert keine konkreten Infrastrukturadapter; vorhandene Ports bleiben nutzbar. Keine zusätzlichen Interfaces allein zur Spiegelung jeder Funktion.

Andere Module dürfen nur die öffentliche API importieren. Kein Zugriff auf fremde Repositories oder schreibendes SQL auf fremde Tabellen. Schema und Migrationen bleiben gemeinsam. Für globale Leseansichten zunächst öffentliche Abfragen bündeln und paginieren; materialisierte Projektionen oder direkte modulübergreifende SQL-Leseabfragen erst bei belegtem Bedarf und dokumentierter Eigentümerschaft.

Abhängigkeiten bilden einen gerichteten azyklischen Graphen. Zusammengesetzte Abläufe liegen beim aufrufenden Feature oder in einer konkret benannten Application-Funktion. Beispiel: Wissen verwendet Tasks; Tasks muss dafür Wissen nicht importieren. Bestehende Querabhängigkeiten werden pro migriertem Bereich explizit erfasst; keine globale Ausnahme für alle Altimporte. Übergangs-Reexports haben eine benannte Entfernungsetappe.

### 3.3 Monorepo: ein Fachmodul über mehrere Sprachbereiche

Ein Fachmodul kann Backend, React-Oberfläche und Clientverträge umfassen. Seine gemeinsame Identität erfordert keinen gemeinsamen physischen Ordner für Python und TypeScript. Die vorhandene Workspace- und Buildstruktur bleibt erhalten:

```text
src/leonaid/modules/tasks/       # Python-Fachoperationen und HTTP-Adapter
packages/features/src/tasks/    # gemeinsame React-Seiten und UI-Beiträge
packages/api-client/            # bestehender TypeScript-Client und Verträge
apps/web/                      # Web-Shell setzt UI-Beiträge zusammen
apps/pwa/                      # PWA-Shell setzt UI-Beiträge zusammen
```

Backend und Frontend verwenden dieselben stabilen Modul-IDs und verständlich korrespondierende Bereichsnamen. Fachbezogene Clientoperationen bleiben im bestehenden API-Client; keine zweite API-Client-Implementierung pro Modul. Öffentliche Astro-/Campaign-Surfaces nutzen ihre vorhandenen Integrationspfade. Jede Änderung muss alle betroffenen Sprachbereiche und Surfaces benennen und prüfen.

Separate Workspace-Pakete werden erst bei konkretem Bedarf erwogen: Wiederverwendung durch mehrere Backend-Anwendungen, unabhängig benötigte optionale Abhängigkeiten oder separate Auslieferung. Dann wäre ein Workspace mit eigenen Paketmetadaten und Python-Importnamen wie `leonaid_tasks` möglich. Die bloße Aufteilung in `src/leonaid-core/` und `src/modules/` bringt keine stärkere Importkontrolle; ein Bindestrich ist zudem kein geeigneter Name für ein normal importiertes Python-Paket. Für M0–M3 bleibt es bei einem gemeinsamen Backend-Projekt und geprüften Modulgrenzen.

## 4. Registrierung und App-Shell

### 4.1 Backend

Eine statische Liste unter `bootstrap/` registriert installierte Module im Composition Root. Ein Eintrag enthält zunächst nur stabile Modul-ID, Router und vorhandene Navigationsbeiträge. Worker-Handler werden ebenfalls unter `bootstrap/` aus expliziten Modulbeiträgen zusammengeführt. Prozess-Entrypoints starten diese Zusammensetzung; weder Plattform noch Fachmodule entdecken oder laden selbst andere Module. API und Worker importieren keine Frontend-Metadaten.

Startvalidierung lehnt doppelte Modul-IDs, doppelte Handler-Typen und kollidierende Routen ab. Benötigte Modulabhängigkeiten werden explizit geprüft. Dies ist eine Startprüfung, kein dynamischer Dependency-Injection-Container.

Die bestehende Identity-Antwort und `navigation` bleiben während der Migration kompatibel. Navigationsbeiträge werden weiterhin serverseitig anhand der aktuellen Identität und Aktionszugehörigkeit gefiltert. Erforderliche zusätzliche Felder sind additiv; existierende Schlüssel und URLs bleiben erhalten.

### 4.2 Web und PWA

Module exportieren statisch importierte UI-Beiträge aus dem bestehenden Features-Paket. Beispielvertrag:

```ts
{
  id: "tasks",
  area: "work",
  surfaces: ["web", "pwa"],
  routes: taskRoutes,
  navigation: taskNavigation,
}
```

Der Implementierungsschnitt definiert konkrete TypeScript-Typen passend zum vorhandenen Routing. Kein Routerwechsel allein für die Registrierung. Modul-ID verknüpft Backend-Berechtigung und Frontend-Beitrag; `area` gruppiert Navigation und hat keine eigene fachliche oder sicherheitsrelevante Bedeutung.

Die Shell besitzt Sitzung, Aktionsauswahl, Layout, Lade-/Fehlerzustände und Navigation. Module besitzen Seiten und Interaktionen. Web und PWA dürfen unterschiedliche Routen und Darstellungen anbieten; gemeinsame Fachkomponenten bleiben gemeinsam. Seiten werden bei Bedarf lazy geladen. Unbekannte Pfade zeigen einen verständlichen Nicht-gefunden-Zustand; direkte Links auf gesperrte Funktionen bleiben serverseitig gesperrt.

Nicht verwechseln: registriert, für einen Kontext verfügbar und für einen Benutzer erlaubt. Feature Flags sind keine Rechteprüfung. Ein Menüeintrag allein gewährt keinen Zugriff. Modulaktivierung pro Club wird nicht als neue Konfigurationsfunktion gebaut. Ein bereits verwendetes Modul wird nicht zur Laufzeit entladen; ausstehende Jobs müssen weiter abgearbeitet werden können.

### 4.3 Suche, Schnellerfassung und Objektverweise

Erst in Etappe M2 kommen die konkret benötigten Suchbeiträge hinzu: begrenzte autorisierte Ergebnisse mit Typ, stabiler ID, Titel, Kontext und Ziel. Die Shell kann dieselben Navigationsbeiträge für die Befehlspalette verwenden. Suchvorschauen und Trefferzahlen dürfen keine unberechtigten Objekte offenlegen. Kein zusätzlicher Suchdienst.

Objektverweise verwenden stabile IDs und eine geschlossene Liste unterstützter Typen. Ein Verweis gewährt keine Rechte; das Ziel prüft Zugriff erneut. Umbenennen und Verschieben ändern keine Identität. Für die ersten unterstützten Kontexte explizite Beziehungen/Constraints verwenden; kein universeller EAV-Datenbestand. Neue Objekttypen benötigen einen konkreten Rechte- und Löschvertrag.

## 5. Öffentliche Fachoperationen

Beispiel einer internen Operation, keine fertige Bibliothek:

```python
task = await tasks.create_task(
    actor=actor,
    list_id=list_id,
    title="Vorbereitung bestätigen",
    assignee_id=assignee_id,
    idempotency_key=request_key,
)
```

Für jeden implementierten Schreib-Use-Case gelten:

1. Aktuelle Identität und Objektberechtigung am Anwendungseinstieg prüfen, auch bei direktem Python-Aufruf. Transportvalidierung bleibt zusätzlich bestehen.
2. Typisierte Eingaben/Ergebnisse und stabile Fachfehler; HTTP übersetzt diese in passende Statuscodes. Keine privaten Werte in Fehlern.
3. Wiederholbare Schreiboperationen verwenden vorhandene Command Receipts: Schlüssel wird mit Akteur, Operation und Kontext begrenzt; gleicher Schlüssel mit anderem normalisiertem Input ergibt Konflikt. Vor einem Replay Zugriff erneut prüfen.
4. Fachänderung, Audit und erforderliche Outbox-Einträge werden in derselben PostgreSQL-Transaktion gespeichert. Netzwerkaufrufe nicht in neue langlaufende Datenbanktransaktionen verlagern.
5. Revisionen bzw. atomare Zustandsbedingungen verhindern verlorene Updates. Keine implizite Last-write-wins-Regel bei gemeinsamen Seiten oder Bearbeitungszuständen.

### 5.1 Zusammengesetzte Transaktionen

Für „Task aus Seite anlegen“ besitzt eine konkrete Application-Funktion die Transaktion. Sie verwendet intern transaktionsgebundene Moduloperationen und committet einmal. Die Operationen behalten ihre Rechteprüfung und schreiben ausschließlich die eigenen Daten. Der gemeinsame Transaktionsmechanismus bleibt intern; er erscheint nicht im späteren HTTP-/MCP-Vertrag. Keine eigenständig committenden Unteroperationen innerhalb dieses Ablaufs.

Seitenrevision, Task-Erstellung, Task-Referenz und Idempotenzbeleg müssen gemeinsam erfolgreich sein oder zurückrollen. Ein Revisionkonflikt hinterlässt keinen unbeabsichtigten Task. Das Entfernen einer Einbettung löscht den Task nicht. Kopieren einer Seite erzeugt ohne ausdrückliche Kopieroperation keine neuen Tasks.

### 5.2 Späterer MCP-Anschluss

Keine MCP-Implementierung in M0–M3. Ein späterer Adapter ruft dieselben autorisierten Fachoperationen auf. Tools werden explizit ausgewählt; keine automatische Exposition aller Methoden, SQL-Zugriffe oder Queue-Handler. Agent-Identität, delegierte Rechte, Audit und Wiederholungsverhalten sind dann Bestandteil der separaten Umsetzung. Ein Worker verwendet eine explizit begrenzte Systemoperation; gespeicherte Benutzer-IDs sind keine dauerhafte Vollmacht.

## 6. Dauerhafte Jobs und Zeitsteuerung

### 6.1 Bestehende Outbox als Grundlage

Vorhandene Tabellen, Zustände, Handler und Operations-Anzeige weiterverwenden. Kein paralleles Queue-System. Eine Zeile bezeichnet eine konkrete abzuarbeitende Folgeaktion; unabhängige Empfänger erhalten getrennte Aufträge mit eigenen Idempotenzschlüsseln. Die aktuelle Ein-Handler-Zuordnung wird nicht zu einem impliziten Broadcast umgedeututet.

`PendingOutboxEvent` und dessen Persistenz erhalten bei Bedarf einen optionalen timezone-aware Ausführungszeitpunkt. Ohne Angabe bleibt das heutige Verhalten erhalten. `available_at` wird beim Einfügen atomar gesetzt. Alle betroffenen Producer, Replay-Pfade und Migrationen sind vor einer Änderung zu inventarisieren. Bestehende Payloads und versionierte Handler-Namen bleiben ausführbar.

Jobs liefern mindestens At-least-once-Verarbeitung. Claim-Fencing schützt den Queue-Zustand, nicht externe Effekte. Handler brauchen fachliche Idempotenz. Ein Timeout nach einem erfolgreichen externen Aufruf ist ein unklarer Ausgang und darf nicht blind erneut einen Datensatz oder Versand erzeugen. Vorhandene Recovery-/Ledger-Verfahren erhalten.

### 6.2 Nur Nebenwirkungen einplanen

| Bedarf                                   | Umsetzung                                                           |
| ---------------------------------------- | ------------------------------------------------------------------- |
| Task wieder sichtbar nach Zurückstellung | Abfrage mit Serverzeit; Fälligkeit bleibt unabhängig                |
| Pin läuft ab                             | Abfrage mit Ablaufzeit; Inhalt bleibt gespeichert                   |
| Gezielte Erinnerung                      | Dauerhafter Job, vor Ausführung aktuellen Zustand prüfen            |
| Twenty-Zuordnung                         | Dauerhafter Auftrag mit Wiederholung und sichtbarem Fehlerstatus    |
| Rendering                                | Auftrag bei relevanter Änderung, über Objekt/Revision dedupliziert  |
| Fristen/Aufbewahrung                     | Bestehenden fachlichen Sweep erhalten, später explizit registrieren |

Erinnerungen zu inzwischen erledigten/geänderten Objekten enden ohne Nebenwirkung. Es braucht dafür zunächst keinen generischen Cancel-Workflow. UTC für gespeicherte Zeitpunkte; lokale Tages-/Uhrzeitregeln werden vor Speicherung anhand einer expliziten IANA-Zeitzone aufgelöst.

### 6.3 Wiederkehrende Sweeps

In M1 den vorhandenen Survey-Sweep als expliziten Beitrag registrieren, seine fachliche Nachholsemantik erhalten. Erst mit einem zweiten echten periodischen Bedarf einen kleinen gemeinsamen Scheduler ergänzen. Anfangs nur feste Intervalle oder konkrete fachliche Fälligkeiten, kein Cron-Parser und keine konfigurierbare Kalender-Engine.

Für neue periodische Aufträge: eine kleine persistente Schedule-Zeile mit stabiler ID und nächster UTC-Fälligkeit; Scheduler sperrt fällige Zeilen, schreibt Auftrag mit eindeutigem Schlüssel `(schedule_id, scheduled_for)` und verschiebt die nächste Fälligkeit in derselben Transaktion. Unique Constraint verhindert doppelte Ausführungen bei mehreren Scheduler-Prozessen. Abgebrochene Transaktion lässt den Termin fällig. Scheduler läuft im vorhandenen Worker und führt keine Facharbeit während der Planungstransaktion aus.

Standard bei verpassten Intervallen: einen zusammengefassten Nachholauftrag erzeugen, nächste Fälligkeit in die Zukunft setzen. Abweichende Regeln wie Überspringen werden pro tatsächlich implementierter Aufgabe dokumentiert. Fachlich vollständiges Nachholen arbeitet begrenzte Batches ab. Kein unbeschränktes Aufholen tausender Zeitpunkte nach einem Ausfall. Der fachliche Survey-Sweep wird nicht unbesehen in einen anderen Takt überführt.

### 6.4 Laufzeit, Wiederholung und Betrieb

- Vor Erweiterung Joblaufzeiten mit repräsentativen synthetischen Export-/Renderdaten messen. Serielle Verarbeitung und Standard-Lease von 300 Sekunden als aktuelle Grenze dokumentieren.
- Jeder neue Handler erhält eine begrenzte Laufzeit unterhalb seiner Lease. Bei blockierenden Subprozessen Timeout bis zum Subprozess durchsetzen. Lease-Verlängerung nur für nachweislich erforderliche längere Jobs implementieren.
- Erst bei belegter Blockierung eine kleine begrenzte Parallelität ergänzen; Jobreihenfolge bei fachlichen Abhängigkeiten nicht voraussetzen. Kein Worker pro Modul.
- Backoff bleibt begrenzt; Jitter kann injizierbar ergänzt werden. Permanente Validierungs-/Berechtigungsfehler werden nicht mehrfach versucht. Wiederholungsbudget und manueller Retry werden explizit getestet.
- Operations zeigt bestehende Queue-Zustände weiterhin, ergänzt benötigte Angaben wie nächsten Versuch, Alter des ältesten fälligen Jobs und letzte erfolgreiche Scheduler-Aktivität. Datenbank-Erreichbarkeit allein ist kein Nachweis funktionierender Jobverarbeitung.
- Logs enthalten Job-ID, Typ, Versuch, Dauer und sicheren Fehlercode; keine Kontaktangaben, Mailinhalte oder Zugangsdaten. Sichere Shutdowns unterbrechen keine Transaktion halb; verlorene Claims bleiben wiederherstellbar.
- Retention bestehender Queue-/Audit-Daten nicht stillschweigend ändern. Neue Zeitplantabellen in Migration und Backup aufnehmen.

### 6.5 Entscheidungspunkt für eine Bibliothek

Procrastinate wird erst evaluiert, wenn konkret benötigte Prioritäten, konkurrierende Jobklassen, komplexere Zeitpläne oder Lease-Verwaltung den kleinen eigenen Pfad deutlich vergrößern. Der Vergleich muss gemeinsame Transaktion mit den derzeitigen Datenbankadaptern, Schema-Migration, Crash-Recovery, Operations und Entfernung des alten Queue-Codes nachweisen. Dokumentation allein belegt keine kompatible Integration.

pg-boss erfordert eine passende Node.js-Integration und ist deshalb nicht die erste Wahl für den Python-Core. Temporal ist ohne konkreten langlebigen Workflow-Bedarf nicht vorgesehen. Referenzen: [Procrastinate](https://procrastinate.readthedocs.io/en/stable/howto/advanced.html), [pg-boss](https://github.com/timgit/pg-boss), [Temporal Self-hosting](https://docs.temporal.io/self-hosted-guide). Versionen und Fähigkeiten vor einem späteren Einsatz erneut prüfen.

## 7. Umsetzungsetappen

### M0 — Modulgrenzen und Verträge

- [x] Aktuellen Stand und konkrete Survey-Abhängigkeiten inventarisieren; betroffene Tabellen und öffentliche Use Cases benennen.
- [x] Bestehende Funktionen den Zuständigkeiten Plattform, Fachmodul, Bootstrap und Prozessstart zuordnen; nur die für den ersten Schnitt benötigten Dateien migrieren. Gemeinsamen Python-Namespace und bestehende Startpfade erhalten.
- [x] Kleinste Backend-/Frontend-Registrierung implementieren und Shell-Zuständigkeit festlegen.
- [x] Rekursive Architekturtests für Schichten, öffentliche Modulimporte und Zyklen ergänzen. Insbesondere Plattformimporte von Fachmodulen sowie Modulimporte von Bootstrap/Prozess-Entrypoints verbieten. Alte erlaubte Kanten einzeln dokumentieren; neue verbotene Kanten schlagen fehl.
- [x] Startprüfungen für doppelte IDs, Handler und Routenkollisionen implementieren.
- [x] Survey-Host-Pins nach Frontend-Verschiebung korrigieren: vorhandenes `react-dom@19.2.8` im Features-Paket direkt deklarieren. `tools/pins/check.py` und Bun-1.2.19-Frozen-Install bestanden; erneuter CI-Lauf bleibt maßgeblich.
- [x] Bekannten kritischen Perl-Befund im API-/Worker-Image durch gepinntes Debian-Sicherheitsupdate beheben; gebautes Image mit CI-Trivy-Konfiguration lokal erfolgreich geprüft. Vollständige CI-Abnahme bleibt offen.

Abnahme: Tests erkennen absichtlich eingebrachte ungültige Imports/Kollisionen einschließlich Rückabhängigkeiten der Plattform. Backend-/Frontend-Beiträge sind derselben Modul-ID zugeordnet; bestehende Navigation, Startbefehle und API bleiben unverändert. Keine neuen Infrastrukturcontainer, separaten Python-Pakete oder Laufzeitabhängigkeiten.

- [x] CI-Formatierungsfehler im Navigationstest nach Materialregistrierung korrigieren. Vollständige Ruff- und Mypy-Zielmengen aus dem CI-Skript, Prettier und OpenAPI-Aktualität lokal geprüft; Remote-Gesamtabnahme bleibt offen.

- [x] Remote-CI-Typfehler der Inbox-Browser-Seeds beheben: explizite Rückgabeannotation und typisierte Settings-Validierung; Mypy über src und beide Seeds sowie Ruff bestanden.

### M1 — Surveys vertikal migrieren und Jobvertrag festigen

- [x] Export-Render-Abnahme bestätigen: aktuelle Renderer-Fixtures erneut erzeugt, 20 PDF-Seiten vollständig visuell geprüft; vier XLSX-Dateien und zugehörige bereits geprüfte Consumer-PDFs bytegenau bestätigt. Hash-Ledger unter proofs/export-render-review.json.

- [x] Vollständige automatische Survey-Exportgruppe bestehen: exports, export-permissions, export-states, export-recovery und export-limits. Sichtprüfung der erzeugten Exportartefakte und Remote-Gesamt-CI bleiben separate Gates.

- [x] Vollständigen Operations-Gate nach Ergänzung des Sweep-Zeitpunkts bestehen: reale Abhängigkeitsausfälle, Mail-Dead-Letter/Retry im Browser, Metriken und Loghygiene; eigener Stack vollständig bereinigt.

- [x] Aggregat-Runner unabhängig von einer macOS-Host-`.venv` ausführen: gepinnte Linux-Abhängigkeiten temporär außerhalb des schreibgeschützten Checkouts installieren. Echter Aggregat-, Ausfall-/Neustart- und Ressourcenbereinigungsnachweis bestanden.

- [x] Surveys über Modulbeiträge registrieren: Backend-Router, Web-Einstieg und bestehender Zugang aus der PWA. Fehlenden PWA-Link ergänzt; bestehender gemeinsamer Web-Editor bleibt das Ziel. Registrierungs-/Identitätstests, Produktionsbuilds und tatsächlicher Browserwechsel PWA → Survey-Webübersicht bestanden.
- [x] Öffentliche Survey-Operationen benennen und direkte Aufrufe mit denselben Rechteprüfungen absichern; bestehende Autorisierungslogik nicht duplizieren.
  - [x] Lebenszyklus, Liste und Grundeinstellungen: gemeinsame Eingabe-/Ergebnismodelle, benannte typisierte Methoden und Nutzung durch HTTP; Direktaufruf-Validierung einschließlich nachträglich veränderter Eingaben geprüft. Analyse, Antwortauswahl, Teilnahme und vollständiger LIVE-Rechtenachweis bleiben offen.
  - [x] Analyse, Antwortauswahl, Einladungsverwaltung und Teilnahme auf benannte typisierte Methoden umstellen; generische `SurveyService.author`-/`participate`-Aufrufe entfernen. Vollständige LIVE-Matrix und Export-Fassade bleiben offen.
  - [x] Export-Fassade mit Direktaufruf-Validierung und expliziten öffentlichen Python-Exports ergänzen; HTTP auf dieselben Methoden umstellen.
- [ ] Bestehende Survey-Handler und Fristen-Sweep explizit registrieren. Bestehende Export-, Versand-, Lösch- und Recovery-Semantik erhalten.
  - [x] Implementierung: Handler-Konstruktion und vorhandenen Sweep in `modules/surveys/jobs.py` bündeln, über Bootstrap registrieren und doppelte Sweep-Namen beim Start ablehnen. LIVE-Regressionsabnahme bleibt für den übergeordneten Task offen.
- [x] Verzögertes Enqueue, Laufzeit-/Lease-Grenzen und sichere Retry-Fehler anhand eines realen vorhandenen Jobtyps prüfen; keine künstlichen Produktjobs erzeugen.
  - [x] Optionalen timezone-aware Ausführungszeitpunkt in allen Pending-Event-Persistenzen ergänzen; mit echtem ActionProgress-Handler Rollback, Fälligkeitsgrenze, Lease-Übernahme und Fencing im isolierten PostgreSQL-Runner nachweisen. Bestehende SMTP-Retry-/Recovery-Prüfungen bestanden.
  - [x] Diagnostik: rohe Exception-Texte aus gespeicherten Fehlerdetails entfernen; sichere Codes und monotone Laufzeitmessung im Job-Log ergänzen. Unit-/Typprüfung bestanden; PostgreSQL-/Runtime-Abnahme bleibt offen.
  - [x] Vollständige Survey-Exportjobs mit 5.000 synthetischen Antworten über Produktions-API, normale Queue/Worker, PostgreSQL, private Dateiablage und Download messen. Alle vier Exportprodukte verfügbar, längster Durchlauf Antwort-XLSX rund 12 Sekunden bei 240 Sekunden Handlergrenze und 300 Sekunden Lease. Reproduzierbarer Runner unter `tools/outbox/benchmark_export_jobs.py`.
  - [x] Produktionsrenderer im API-Image mit 5.000 synthetischen Antworten messen und Ergebnisse dokumentieren. Vollständige Jobmessung einschließlich Datenbank/Storage und Laufzeitbegrenzung bleiben offen.
  - [x] Explizite Handler-Laufzeitgrenzen unterstützen und Survey-Export auf maximal 240 Sekunden bzw. 80 % der konfigurierten Lease begrenzen. Reale PostgreSQL-Blockade, Abbruch, sicherer Timeout-Code und erfolgreicher Retry mit bestehendem Aktivitäts-Handler nachgewiesen; vollständige Export-Jobmessung bleibt offen.
  - [x] Letzten erfolgreichen Survey-Fristenlauf aus dem laufenden Worker über den bestehenden Health-/Operations-Vertrag anzeigen. Fehlende/alte Worker-Angaben bleiben unbekannt; echter Browsernachweis mit laufendem und gestopptem Worker. Zeitstempel gilt ausdrücklich seit Prozessstart, keine dauerhafte Historie.
  - [x] Worker-Metriken um getrennte Zeitstempel für erfolgreiche Queue-Prüfung, abgeschlossenen Job und vollständig erfolgreichen Survey-Sweep ergänzen. Prozessneustart beginnt ohne Erfolgsnachweis; Operations-UI und dauerhafte Historie bleiben offen.
  - [x] Nächsten Versuch und Alter des ältesten fälligen wartenden Jobs aus PostgreSQL über Operations-API und generierten Client in die bestehende Anzeige aufnehmen. Reale SQL-Grenzfälle bestanden; Browser-/Gesamtabnahme bleibt offen.
- [ ] Ersetzte zentrale Survey-Verdrahtung entfernen; keine dauerhafte doppelte Registrierung.
  - [x] Konkrete Konstruktion von Survey-Service, Export-Service und Erasure-Publisher aus dem API-Entrypoint nach Bootstrap verschieben. LIVE-Start-/Recovery-Abnahme bleibt offen.
  - [x] Survey-Domain, Application und fachliche Adapter samt Typst-Template nach `modules/surveys/` verschieben; alte Implementierungspfade entfernen, Importgrenzen und Fixture-Fingerprints nachziehen. Unit-Suite und Renderer im frisch gebauten Image bestanden; vollständige LIVE-Abnahme bleibt offen.

Abnahme: Survey-Erstellung, Bearbeitung, Veröffentlichung, öffentliche Teilnahme, Kopieren, Export, Fristschluss und berechtigte Zugriffe funktionieren weiterhin. Bestehende HTTP-Verträge, URLs und gespeicherte Jobs bleiben kompatibel. Web, PWA-Zugang und öffentliche Teilnahme jeweils separat nachweisen.

### M2 — Tasks, Wissen und Materialien als Wiederverwendungsnachweis

- [x] Bestehende Akquise-Weiterleitung trotz allgemein verfügbarer Module erhalten: Modulnavigation zählt nicht als Verwaltungszugang. Vollständiger Dokumentengate mit echten Rollen, Browserdownloads und Speicherfehler bestanden.

- [x] Gemeinsamen Modul-Browser-Gate mit sieben Fällen bestehen und Artefaktablage an CI anpassen: Host-UID/GID für Seed und Browser, Bilder/Traces getrennt vom öffentlichen bereinigten Logpaket. Frischer Stack vollständig bereinigt.

- [x] Dauerhaften Aufgaben-Browsertest für Web/PWA ergänzen: persönliche Zuständigkeit, Zurückstellung, Einblenden und Erledigen bei unveränderter Fälligkeit; beide echten Browserabläufe bestanden. Remote-Gesamt-CI bleibt separat offen.

- [x] Vollständigen isolierten Schema-Gate mit aktuellem Backend abschließen: Leeraufbau bis 0041, Task-/Wissens-/Material-/Inbox-Verträge einschließlich HTTP, Konkurrenz und Rechteentzug sowie Upgrade des versionierten Altbestands mit Datenhalt. Eigene Testressourcen vollständig entfernt.

- [x] Reihenfolgeabhängigkeit im Task-Aktions-Paginationstest beheben: eigene eindeutige Suchmenge, Rechteprüfungen unverändert; vollständige Matrix mit fremdem Aktionsbestand in PostgreSQL bestanden. Gesamt-Compose-Gate und Legacy-Upgrade weiterhin offen.

- [x] Tasks: Liste, optional ein Epic pro Task, offen/erledigt, optional persönliche Zuständigkeit, getrennte Fälligkeit und Zurückstellung. Keine verschachtelten Epics oder konfigurierbaren Statusmodelle.
  - [x] Gemeinsamen Editor in Web/PWA mit echten konkurrierenden Änderungen prüfen: Zurückstellung ändern bei unveränderter Fälligkeit, ausgeblendete Aufgabe gezielt einblenden, veralteten Speicherversuch abweisen und Entwurf erhalten. Nach Neuladen bleiben der erste Titel und beide korrekten Zeitpunkte bestehen.
  - [x] Datenbasis: Task-eigene Listen, explizite Mitgliederrechte, Epics und revisionierte Tasks mit getrennten Zeitpunkten migrieren. Same-List-Epic, Zustände, Fremdschlüssel und Rücknahme/erneutes Upgrade mit PostgreSQL nachgewiesen. Fachoperationen, Autorisierung und UI bleiben offen.
  - [x] Erste direkte Fachoperationen: Liste erstellen/lesen und Task erstellen/lesen/ändern mit typisierten Eingaben, aktuellen Datenbankrechten, Revisionen, gemeinsamen Receipts und atomarem Audit. Reale Standalone-Replay-/Rechteprüfung bestanden. HTTP, Listenabfragen, Epic-/Mitgliederverwaltung und vollständige Aktionsmatrix bleiben offen.
  - [x] Task-Modul über Bootstrap in FastAPI registrieren; sieben Listen-/Task-Endpunkte und generierten Client anbinden. Produktions-App mit echten PostgreSQL-Sitzungen, CSRF, strikten JSON-Eingaben und Konflikten geprüft. Navigation/UI und übrige Task-Verwaltung bleiben offen.
  - [x] Epics erstellen, begrenzt auflisten/suchen und mit Revision umbenennen; direkte Fachoperationen, HTTP und Client ergänzen. Replay, Konflikte, Ausschluss von Verschachtelung und stabile Task-Verweise mit echtem PostgreSQL geprüft. Epic-Oberfläche bleibt offen.
- [x] Wissen: Titel, Tiptap-Inhalt, Revision, stabile Task-/Materialreferenzen. Revisionskonflikt statt unbemerktem Überschreiben; kein Yjs-Dienst.
  - [x] Materialreferenzen im gemeinsamen Web-/PWA-Editor auswählen, als feste Version speichern und autorisiert darstellen/herunterladen. Echter Browserablauf für zwei Seiten, Auswahl alter Version trotz neuerem Dateistand, Roundtrip und unabhängige Seiten-/Materialrechte einschließlich Entzug bestanden. Mobile Langtitel und Download-Erreichbarkeit geprüft. Dauerhafte Browser-CI und übrige Gesamt-Abnahmen bleiben offen.
  - [x] Versionsgebundene Materialreferenzen im Dokumentvertrag und in Wissensrevisionen speichern. Öffentliche Material-API prüft aktuellen Zielzugriff auf derselben DB-Verbindung. Echte PostgreSQL-/RustFS- und HTTP-Nachweise für Mehrfachreferenz, feste Version, Entzug und Rollback bestanden. Darstellung und Auswahl im Editor bleiben offen.
  - [x] Gemeinsamen Tiptap-Seiteneditor für Web/PWA anbinden: Titel, Formatierung, revisioniertes Speichern, Entwurfserhalt bei Konflikt und bestätigtes Neuladen. Bestehende Task-Verweise bleiben erhalten und zeigen autorisiert den aktuellen Status. Echte Browsernachweise einschließlich Zwei-Tab-Konflikt und Formatierungs-Roundtrip bestanden; Task-Anlage im Editor, Freigabeoberfläche und Materialien bleiben offen.
  - [x] Aktuelle seitenbezogene Bearbeitungs-/Verwaltungsrechte über Fach-API, HTTP und Client auskunftsfähig machen. Auskunft und Schreibpfade teilen dieselbe Regel; Mitglieder-/Aktionsmatrix einschließlich Entzug mit PostgreSQL bestanden. Editor nutzt diese Auskunft im folgenden UI-Schnitt.
  - [x] Wissens-HTTP-Adapter und Produktions-Lifespan registrieren; OpenAPI/TypeScript-Client generieren. Echter PostgreSQL-/FastAPI-Vertrag für Sitzungen, CSRF, Dokumentvalidierung, Suche, Wiederholung und Revisionskonflikt bestanden. Navigation und Editor folgen separat.
  - [x] Wissensseiten transaktional erstellen, lesen, ändern und begrenzt nach Titel suchen. Aktuelle Konten-/Seitenrechte, idempotente Wiederholung, Revisionskonflikte und autorisierte Task-Verweise mit echtem PostgreSQL geprüft. Interne Task-Transaktionsbindung verhindert Pool-Verklemmung und erhält äußeren Rollback. HTTP, Aktionsrechtematrix, Mitgliederverwaltung, Editor und Materialien bleiben offen.
  - [x] Typisierte Wissenseingaben und begrenzten Tiptap-Dokumentvertrag vorbereiten: erlaubte Block-/Textknoten, sichere HTTP(S)-Links, stabile Task-ID-Knoten, Größen-/Tiefen-/Knotengrenzen und erneute Prüfung veränderter Eingaben. 23 neue Validierungstests bestanden. Repository, Autorisierung, HTTP und Editor bleiben offen.
  - [x] Wissenseigene Seiten, explizite Mitgliederrechte, Revisionssnapshots und revisionsbezogene Task-Verweise migrieren. Gültiger aktueller Revisionskopf, Dokumentwurzel/Größenlimit, Fremdschlüssel und unabhängige Task-Lebensdauer mit PostgreSQL geprüft; Downgrade und erneutes Upgrade bestanden. Fachoperationen, Autorisierung, Tiptap-Editor und Materialreferenzen bleiben offen.
- [x] Materialien: vorhandenen S3-Zugriff und geeignete bestehende Dokumentfunktionen wiederverwenden; explizite Metadaten-/Versionsverantwortung klären. Keine zweite Dateiablage.
  - [x] Kontrollierte Bereinigung nicht wiederaufgenommener Uploads: administrative exakte Versionsauswahl, Prüflauf als Standard, aktuelle System-Admin-Prüfung und dauerhafter Löschversuch. Gemeinsame Transaktionssperre schützt laufende/committete Uploads. Echte PostgreSQL-/RustFS-Konkurrenz, Rollback, Wiederholung, Wiederaufnahme und tatsächlicher CLI-Aufruf bestanden; Betriebsanleitung unter `tools/materials/README.md`.
  - [x] Material-Aktionsrechtematrix mit zehn Identitäten dauerhaft nachweisen: aktuelle Rollen, abgelaufene/künftige/fremde Mitgliedschaft, veraltete globale Rolle, Suche, Versionsmetadaten/Bytes, Upload und Verwaltung. Explizite Rechte umgehen keine Aktionsgrenze; Bearbeitungsentzug sperrt auch Replay bei fortbestehendem Leserecht. PostgreSQL/RustFS-Vertrag bestanden und im Schema-Gate registriert.
  - [x] Gemeinsame Materialoberfläche in Web/PWA registrieren: Upload, begrenzte Suche und Aktionsfilter, Versionswahl, geschützter Download und Freigabeverwaltung. LIVE Web-Upload → PWA-Download/Editor-Version → alte Bytes → Entzug bestanden; Aufgaben-/Wissensfreigaben auf Regressionen geprüft. Vollständige Aktionsmatrix, Wissenseinbettung und Upload-Bereinigung bleiben offen.
  - [x] Materialfreigaben und Rechteauskunft über Service, HTTP und Client bereitstellen: bestehendes Konto per E-Mail, viewer/editor/Entfernen, Eigentümerschutz und separate Freigaberevision. Echte PostgreSQL-/RustFS-Prüfung für Konkurrenz, Editor-Upload, Entzug und aktuelle Aktionsgrenzen bestanden; Freigabeoberfläche und vollständige Aktionsmatrix bleiben offen.
  - [x] Materialmodul über Bootstrap/FastAPI registrieren und typisierten Multipart-/Download-Client generieren. Echter PostgreSQL-/RustFS-HTTP-Vertrag einschließlich Session/CSRF, Replay, Anhängen, Dateinamen und Streaming-Limit bestanden; tatsächlicher TypeScript-Client ebenfalls geprüft. Navigation/UI und übrige Materialabnahme bleiben offen.
  - [x] Erste öffentliche Materialoperationen für Upload, neue Version, Metadaten/Suche und geschützten Download implementieren. Echte PostgreSQL-/RustFS-Nachweise für parallelen Replay, Versionskonflikt, alte Bytes, Rechteentzug und S3-Erfolg mit anschließendem DB-Rollback samt Wiederaufnahme bestanden. HTTP/UI, Freigabeverwaltung, vollständige Aktionsmatrix und Bereinigung nicht wiederaufgenommener Uploads bleiben offen.
  - [x] Materialeigene Metadaten, Dateiversionen und explizite Mitglieder sowie versionsgebundene Wissensreferenzen migrieren. PostgreSQL prüft Versionskopf, Speicherintegrität-Metadaten, zwei Seiten auf derselben Version und unabhängige Dateilebensdauer. Downgrade/Upgrade und Schema-Smoke bestanden. Upload-/Download-Operationen, Rechteauswertung und UI bleiben offen.
- [x] Gemeinsamer Aktionskontext sowie eigenständige Listen/Seiten mit explizitem berechtigtem Personenkreis. Verlinkung oder Erwähnung erweitert keine Rechte.
  - [x] Wissensseiten über die gemeinsame autorisierte Aktionssuche einer verwalteten Aktion zuordnen und Seiten nach Aktion filtern. Suche und Abfrage werden mit Tasks geteilt. LIVE Charity-Admin-Anlage → Aktionsmitglied in PWA lesen/filtern; unerlaubte Anlage per API abgewiesen und Aufgabenregression bestanden. Materialkontexte bleiben offen.
  - [x] Wissens-Mitgliederrechte über Service, HTTP und Client verwalten: bestehendes Konto per E-Mail, viewer/editor/Entfernen, Eigentümerschutz und aktuelle Aktionsgrenzen. Eigene Freigaberevision verhindert verlorene Rechteänderungen ohne neue Inhaltsrevision. PostgreSQL-, HTTP-, Konkurrenz- und Migrationsnachweise bestanden; Oberfläche bleibt offen.
  - [x] Direkte Wissens-Aktionsmatrix mit zehn Identitäten und zwei Aktionen prüfen: aktuelle, abgelaufene, zukünftige und fremde Mitgliedschaften; Admin-/Editor-Schreibrechte; private Seiten trotz System-Admin; entzogene Eigentümer-/Editorrechte und Replay. Mitglieder-API und Browsermatrix bleiben offen.
  - [x] Begrenzte autorisierte Aktionssuche über Fach-API, HTTP und Client ergänzen; System-Admins ohne eigene Aktionsmitgliedschaft können Kontexte auswählen. PostgreSQL-Rechtematrix, Pagination und globaler Web-/PWA-Browsernachweis bestanden.
  - [x] Task-Listen aus der Oberfläche einer aktuell verwalteten Aktion zuordnen, Aktionskontext anzeigen und Listen nach bekannten Aktionen filtern. Echter Web-/PWA-Nachweis mit Charity-Admin und Aktionsmitglied bestanden. Wissens-/Materialkontexte bleiben offen.
  - [x] Explizite Task-Listenrechte über direkte API, HTTP und Client verwalten: viewer/editor hinzufügen/ändern/entfernen, Eigentümer schützen, Revision und Replay prüfen. Standalone-Rechtematrix mit PostgreSQL bestanden. Vollständige Aktionsmatrix, weitere Module und UI bleiben offen.
  - [x] Direkte Task-Aktionsmatrix mit zehn Identitäten und zwei Aktionen prüfen: alle vier Aktionsrollen, System-Admin, abgelaufene/zukünftige/fremde Mitgliedschaften, Rechteentzug, Eigentümerentzug, fremde Referenzen und Replay. Browser-/Aktionsoberfläche und weitere Module bleiben offen.
- [x] Atomaren „Task aus Seite“-Use-Case einschließlich Wiederholung und Revisionskonflikt implementieren. Direkter Service, HTTP und Client vorhanden; PostgreSQL prüft Konkurrenz, vollständigen Rollback am Dokumentlimit und getrennte Seiten-/Task-Rechte einschließlich Replay. Editor-Anbindung und Browser-Gesamtabnahme bleiben Teil der offenen Oberflächenaufgaben.
- [x] „Für mich“ als Abfrage derselben Tasks; begrenzte Suche über die tatsächlich vorhandenen Objekte. Kein separater Taskbestand im Editor oder Dashboard. Gemeinsame Suchbeiträge für Aufgaben, Wissen und Materialien mit Typ, ID, Kontext und Ziel nutzen vorhandene autorisierte APIs; Web-/PWA-Browserprüfung einschließlich fremder privater Objekte und direktem Aufgabenlink bestanden.
  - [x] Direkte Task-/Listenabfragen mit gemeinsamer Leseregel, begrenzter Pagination, Titelsuche, Status-/Zuständigkeitsfilter und datenbankzeitabhängiger Zurückstellung implementieren. Reale Rechte-/Such-/Pagination-Nachweise bestanden. HTTP/UI und modulübergreifende Suche bleiben offen.
- [x] Navigation in Web und PWA sowie verständliche mobile Bearbeitung bereitstellen; gemeinsame Funktionen nur einmal implementieren.
  - [x] Dauerhaften Wissens-Browser-Test für Web und mobile PWA ergänzen: echte Inhaltsänderung, zweite Sitzung, erhaltener Konfliktentwurf sowie abgelehntes und bestätigtes Neuladen. Beide Fälle gegen Produktions-API bestanden und im gemeinsamen CI-Runner eingetragen.
  - [x] Dauerhaften Material-Browser-Gate in CI aufnehmen: Web und 390px-PWA mit frischen privaten Konten, zwei echten Uploads, bytegenauem Download der ersten Version, fremdem Direktzugriff und Prüfung auf horizontalen Überlauf. Isolierter Runner lokal bestanden; Remote-CI bleibt separat maßgeblich.
  - [x] Produktions-Webserver liefert für Modul-Direktlinks in beiden Shells den SPA-Einstieg ohne zweite Routenliste. Echter HTTPS-Proxyvertrag prüft Listen-/Detailrouten, Assets und Offline-Dokument; Chrome zeigt dieselbe gespeicherte Aufgabenliste in Web und mobiler PWA. Vollständige Modul-Bedienabnahme bleibt separat offen.
  - [x] Aufgabe aus gespeicherter Wissensseite über gemeinsames Task-Formular erstellen und zuweisen; neue Seitenrevision samt stabiler Referenz übernehmen. LIVE Web → Task-Anlage → PWA „Für mich“ erledigen → aktueller Status auf Seite bestanden. Echter Seitenkonflikt erhält Aufgabenentwurf und erzeugt keinen Task; bestätigtes Neuladen geprüft.
  - [x] Freigabeoberfläche im Wissenseditor bereitstellen und mit tatsächlicher Task-Mitgliederoberfläche teilen. Echter Zwei-Konten-Browserlauf: viewer → editor → PWA-Inhalt speichern → Entzug → API-404; Task-Regression ebenfalls bestanden. Getrennte Freigaberevision und Inhaltsentwurf bleiben erhalten.
  - [x] Wissensnavigation, gemeinsame verzögert geladene Seitenliste, begrenzte Titelsuche und private Seitenanlage in Web/PWA ergänzen. Echter HTTPS-Browsernachweis Web → PWA, mobile Suche/Axe und unabhängige UI-Prüfung für diesen ersten Slice bestanden. Seiteneditor, Aktionsauswahl und Mitgliederoberfläche bleiben offen.
  - [x] Gemeinsame Listenmitgliederverwaltung mit Suche/Pagination, Hinzufügen eines bestehenden aktiven Kontos per E-Mail, Wechsel viewer/editor und Entfernen bereitstellen. Rechteänderung, E-Mail-Auflösung, Receipt und Audit teilen eine Transaktion. Echter Browsernachweis mit zwei Konten einschließlich anschließendem HTTP-404 nach Entzug bestanden. Aktionskontext-Erstellung und vollständige Browser-Konfliktmatrix bleiben offen.
  - [x] Zuweisung an andere berechtigte Personen über begrenzte listenbezogene Suche in Fach-API, HTTP, Client und gemeinsamem Editor anbieten. PostgreSQL prüft aktive Konten, aktuelle Aktions-/Listenrechte, Pagination und Rechteentzug; echter Browserlauf mit zwei Sitzungen: Eigentümer weist zu → Kollegin erledigt in PWA → Eigentümer sieht denselben Status. Mitgliederoberfläche und vollständige Browser-Rechtematrix bleiben offen.
  - [x] Epic-Auswahl mit begrenzter Suche/Pagination, Anlegen und revisioniertem Umbenennen in den gemeinsamen Task-Editor integrieren. Echter Web-/PWA-Browsernachweis: Zuordnung über Suche und Speichern erhalten, anschließend entfernen. Konflikt-/Rechtewechsel im Browser bleiben offen.
  - [x] Gemeinsame Aufgabenbearbeitung für Titel, Beschreibung, offen/erledigt, Selbstzuweisung, Fälligkeit und Zurückstellung anbinden. Echter HTTPS-Browserlauf mit PostgreSQL: Web erstellt → PWA „Für mich“ erledigt → Web zeigt denselben Status; mobile Axe-Prüfung bestanden. Fremdzuweisung, Epic-/Mitgliederoberfläche und vollständige Konflikt-/Rechteabnahme im Browser bleiben offen.
  - [x] Task-Navigation für aktive Konten und gemeinsame, verzögert geladene Listen-/Filteransicht in beiden Shells registrieren. Typprüfungen, Produktionsbuilds und Registrierungs-/Identitätstests bestanden. Browserabnahme, Task-Bearbeitung, Epics und Mitgliederoberfläche bleiben offen.

Abnahme: Seite anlegen → Task erstellen/zuweisen → in „Für mich“ erledigen → derselbe Status in der Seite. Zurückstellung ändert Fälligkeit nicht. Eine Datei einmal hochladen und mehrfach referenzieren. Nichtberechtigte sehen auch in Suche/Einbettungen keine Inhalte. Konkurrierendes Speichern und wiederholtes Absenden erzeugen weder verlorene Änderungen noch doppelte Tasks.

Diese Etappe ist ein nutzbarer technischer Schnitt, keine vollständige Wissensplattform. Erweiterte Vorlagen, Ordnernavigation und weitere Suchtypen benötigen anschließend eigene kleine Umsetzungsschnitte.

### M3 — Inbox und Twenty-Ausfall als Integrationsnachweis

- [x] Additives Inbox-Schema mit Fallstatus, Abschluss/Wiederöffnung, unabhängiger Kontaktzuordnung, verpflichtender Outbox-Referenz sowie internen Kommentaren und exakten Task-/Materialreferenzen. Echter PostgreSQL-Vertrag prüft 23 ungültige Schreibvorgänge; Service, Autorisierung, atomarer öffentlicher Eingang und CRM-Verarbeitung folgen separat.
- [x] Ein Fallmodell für Kontakt-/Hilfsanfragen: Eingang, optionale Aktionsreferenz, zuständige Person, neu/in Bearbeitung/geschlossen, Abschlussnotiz und Wiederöffnung.
- [x] Öffentliche Eingabe begrenzen und validieren; bestehende Schutzmechanismen gegen missbräuchliche öffentliche Requests passend wiederverwenden. Produktions-FastAPI mit echtem PostgreSQL: strikte Eingaben, 64-KiB-Streaming-Limit, Origin-Prüfung und dauerhafte gemeinsame Adressquote einschließlich paralleler Requests und App-Neustart geprüft. Public-/Campaign-UI folgt separat.
- [x] Direkte Inbox-Eingangsoperation mit strikten Eingaben, gemeinsamem Commit von Fall/Outbox/Audit/Receipt und referenzbasierter Bestätigung. Paralleles Replay und tatsächlicher Datenbankfehler nach Fall-/Job-Schreibvorgängen mit Rollback und Wiederholung geprüft. HTTP-Schutz und CRM-Handler noch nicht freigeschaltet.
- [x] Eingangssnapshot, Fall und Kontaktzuordnungsauftrag gemeinsam speichern. Erst danach Bestätigung mit Referenz. Keine E-Mail durch Formularübermittlung. Aktueller PostgreSQL-Vertrag belegt paralleles Replay und vollständigen Rollback bei echtem Speicherfehler; Codeprüfung und separate Produktionsbrowser-Nachweise belegen Kontaktauftrag ohne Mailversand und Bestätigung erst nach Commit.
- [x] Ausstehende/fehlgeschlagene Twenty-Zuordnung sichtbar machen. Twenty bleibt Stammdatenquelle; der Eingangssnapshot ist kein paralleles CRM. Keine Zusammenführung allein nach Namen und kein stilles Überschreiben verifizierter Kontaktdaten.
- [x] Vorhandene CRM-Recovery-Muster auf Eignung prüfen. Nach unklarem externem Create-Ausgang Kontakt anhand belastbarer Korrelation abgleichen; ohne zuverlässigen Nachweis manuelle Klärung statt blindem erneutem Create.
  - [x] Automatischen Wiederanlauf mit normalem Produktionsworker nach echtem Twenty-Ausfall und Worker-Neustart nachweisen: derselbe persistierte Auftrag wird vor Ausschöpfen des Retry-Budgets abgeschlossen, ohne manuellen Retry und mit genau einem korrelierten Twenty-Kontakt.
  - [x] Inbox-Kontaktauftrag im bestehenden Worker registrieren, Create-Absicht vor externer Anfrage speichern und über exakte Twenty-ID samt Snapshot abgleichen. Echter Twenty-Ausfall/Neustart, verlorene Antwort nach erfolgreichem Create, fehlender Nachweis, abweichender Kontakt und veralteter Claim geprüft. Unklare Fälle stoppen in `needs_review`; autorisierte manuelle Auflösung und UI bleiben offen.
  - [x] Manuelle Kontaktklärung als verwaltungsberechtigte Fachoperation implementieren: Auswahl bestehender Twenty-Person, Datenstand-/Kontaktrevisionsprüfung, Begründung und atomarer Abschluss des ruhenden Jobs. Echter Twenty-/PostgreSQL-Vertrag prüft abweichende Person ohne Überschreiben, paralleles Replay, veraltete Auswahl, Audit-Rollback und Rechteentzug. HTTP-Schutz/Ausfall und Client sind geprüft; erfolgreicher HTTP-Ablauf und UI folgen separat.
  - [x] Erfolgreiche Kontaktbestätigung über Produktions-FastAPI mit echtem Twenty prüfen: Kandidatenvorschau, tatsächliche CRM-Änderung, paralleler HTTP-/Direktaufruf, Ausschluss eines beanspruchten Worker-Jobs, ein Auditabschluss und unveränderte Fallrevision. Der vollständige Twenty-Vertrag einschließlich Ausfall/Wiederanlauf ist bestanden; UI-Abnahme bleibt offen.
- [x] Tasks und Materialien über vorhandene Fachoperationen referenzieren. Interne Kommentare bleiben intern; gemeinsame Kommentar-/Mention-Funktion nur soweit für diesen Schnitt erforderlich bauen und dann wiederverwenden. Fachoperationen und HTTP sind geprüft; die Bedienoberfläche bleibt im eigenen UI-Punkt offen.
  - [x] Interne Klartextkommentare als autorisierte, idempotente Fachoperation und HTTP-Routen mit begrenzter Pagination bereitstellen. Kommentar/Audit/Receipt teilen eine Transaktion; echte PostgreSQL-/HTTP-Verträge prüfen paralleles Replay, Rollback, CSRF und Rechteentzug. Keine öffentliche Kommentarroute; UI und Task-/Materialreferenzen bleiben offen.
  - [x] Task-Verweise im Fall über bestehende Task-Fachoperationen ergänzen/entfernen und aktuell auflösen. Echte PostgreSQL-/HTTP-Verträge prüfen unabhängige Rechte, Statusänderung, Rechteentzug beim Replay, Revisionskonflikt, atomaren Rollback und 100-Verweise-Grenze. Unzugängliche Tasks bleiben inhaltslose Verweise; Materialverweise und UI folgen separat.
  - [x] Materialverweise mit exakter Dateiversion über bestehende Material-Fachoperationen ergänzen/entfernen und autorisiert auflösen. Echter PostgreSQL-/RustFS-/HTTP-Vertrag prüft geteilte Datei, erhaltene Version nach neuem Upload, unabhängige Rechte, Replay/Entzug, Rollback und Grenze mit 101 tatsächlichen Dateiversionen. Bestehende Material-HTTP- und Wissensverträge ebenfalls bestanden; UI folgt separat.
- [x] Interne Inbox-HTTP-Routen über Bootstrap und Produktions-Lifespan registrieren; OpenAPI und TypeScript-Client generieren. Echter PostgreSQL-/FastAPI-Vertrag für Sitzung, CSRF, Rechteentzug, strikte Eingaben und Revisionskonflikte bestanden. Öffentliche Einreichung und UI folgen separat.
- [x] Aktuelle fallbezogene Verwaltungsrechte für die gemeinsame Inbox-Oberfläche über Fachoperation, HTTP und Client auskunftsfähig machen. Dieselbe SQL-Regel wie Zuständigkeits- und Kontaktverwaltung; echte PostgreSQL-/HTTP-Prüfung für Admin, Aktionsverwaltung, zugewiesene Bearbeitende, fremde Fälle und Rechteentzug bestanden.
- [ ] Case-Bearbeitung in Web und PWA, öffentliche Einreichung über vorhandene Public-/Campaign-Surfaces integrieren. Alias-/kanonische Routen bei Nutzung separat prüfen.
  - [x] Gemeinsamen CI-Browser-Gate für Material/Inbox/Public bereitstellen: aus Web-/PWA-Fall feste Version verknüpfen, nach weiterem Upload bytegenau herunterladen und Verweis ohne Dateilöschung entfernen; öffentlicher Retry nach verlorener Bestätigung und echtem Rate Limit. Frischer isolierter Stack bestanden; Runner `tools/testing/modular_browser.sh`.
  - [x] Tatsächlich gespeicherten öffentlichen Eingang mit verlorener Rückantwort und anschließendem realen HTTP 429 im Browser prüfen: identischer Wiederholungsauftrag, unveränderte gesperrte Eingaben und weiterhin unklarer Status. Dauerhafter Playwright-Fall ohne ersetzte Serverantworten.
  - [x] Fehlerfolge verlorene Antwort → echte 422-Ablehnung im Browser prüfen und widersprüchliche Bearbeitungsaufforderung korrigieren. Identischer Befehl samt Wiederholungsschlüssel, gesperrter Entwurf und aktive Wiederholung bleiben erhalten; 429-Folge bleibt separat offen.
  - [x] Verlorene Browser-Bestätigung nach echtem Commit prüfen: HTTP-201-Antwort gezielt verwerfen, Entwurf gesperrt erhalten, identischen Befehl einschließlich Idempotenzschlüssel erneut senden und ursprüngliche Referenz bestätigen. SQL zeigt weiterhin genau einen Fall/Kontaktauftrag; Zusammengesetzte Fehlerfolgen nach unklarem Ausgang bleiben separat zu prüfen.
  - [x] Public-Alias zur publizierten Campaign separat prüfen (302 GET/HEAD, tatsächlicher Browser). Bei gestopptem Twenty Anfrage bestätigen und Fall bearbeiten; nach ausgeschöpften automatischen Versuchen über vorhandenen Admin-Retry fortsetzen. Browser, PostgreSQL und echtes Twenty bestätigen einen Fall/Kontakt und erhaltene Bearbeitung. Automatischer Wiederanlauf vor Erreichen der Retry-Grenze sowie Netzwerk-Replay bleiben separat offen.
  - [x] Kanonische CMS-Kampagnenseite ohne Bestellformular im Produktionsbrowser einreichen: echter CMS-Entwurf/Publish, 308 zur Slash-URL, Referenzbestätigung und SQL-Nachweis für einen aktionsgebundenen Fall samt Kontaktauftrag. Reproduzierbare Public-Fixture um verantwortliche Verwaltung ergänzt; Aktionsalias-Weiterleitung bleibt offen.
  - [x] Lokalen CMS-Storage-Operator für die Campaign-Abnahme unabhängig vom Host-Venv ausführen: vorhandenes Core-Image mit gesperrten Linux-Abhängigkeiten, unverändertes internes Storage-Netz; Build und echte RustFS-Provisionierung bestanden.
  - [x] Öffentliche Inbox-Verfügbarkeit von Bestellfreigaben entkoppeln: veröffentlichte Aktionen ohne Bestellformular zeigen die Anfrage, Archiv/inaktiver Alias nicht. Echter HTTP-Routenvertrag mit reproduzierbarem Seed, Browser-Einreichung vom aktiven Alias und SQL-Aktionszuordnung bestanden. Campaign-/Weiterleitungs-Browserabnahme bleibt offen.
  - [x] Gemeinsames öffentliches Anfrageformular als native Astro-Komponente bereitstellen und auf der Club-Startseite live prüfen: Kontaktpflicht mit Entwurfserhalt, Desktop-/Mobile-Einreichung und Referenzbestätigung; PostgreSQL bestätigt jeweils einen Fall und Kontaktauftrag bei angehaltenem Worker. Public-Produktionsbuild, Campaign-Typprüfung und unabhängige UI-Prüfung bestanden. Aktions-/Campaign-Einbindung vorbereitet; deren Browser-/Alias-Abnahme und vollständige Netzfehler-/Replay-Prüfung bleiben offen.
  - [x] Gemeinsame Inbox-Liste und Fallbearbeitung in beiden Shells registrieren; Status, Abschluss/Wiederöffnung, interne Notizen und bewusste Twenty-Kontaktklärung anbinden. Echter Produktionsbrowser prüft Speichern, erhaltenen Konfliktentwurf, bestätigtes Neuladen, Kontaktzuordnung und zwei Konten. Web verknüpft Aufgabe; PWA-Bearbeitung erledigt sie und sieht den aktuellen Status im Fall. Materialpicker-Regressionsprüfung, vollständige Konflikt-/Rechtematrix und öffentliche Formulare bleiben offen.
  - [x] Gemeinsamen Materialpicker nach Extraktion in Inbox und Wissen im Produktionsbrowser prüfen: alte Version trotz neuerem Upload auswählen, speichern und per Web-Direktlink erhalten; Inbox-Verweis entfernen/erneut setzen ohne Dateiverlust. Fallverwaltung ohne Materialrecht sieht keinen Dateinamen/Download; Freigabe und erneuter Entzug über echte API samt Browserdarstellung geprüft. Mobile Referenzdarstellung bei 390 px ohne Überlauf. Wiederholter Browser-Upload und Inbox-Browserdownload bleiben separat offen.
  - [x] Inbox-Buttons nach Nutzerfeedback kompakter gestalten: 36 px am Desktop, 44 px bei Touch, neutrale Nebenaktionen und führende Icons aus der vorhandenen Bibliothek bei erhaltenen Labels. Tatsächliche Browsermessung, Desktop-/Mobile-Screenshots und unabhängige Prüfung der Button-Überarbeitung bestanden.
  - [x] Fallbezogene Zuständigkeitsauswahl als direkte Fachoperation und HTTP-Route mit generiertem Client bereitstellen. Gemeinsame Regel für Suche und Zuweisung; echtes PostgreSQL prüft Pagination, aktive Konten, aktuelle Aktionsrechte und Verwaltungsentzug. Produktions-HTTP-Vertrag einschließlich Sitzung, fremdem Fall und Eingabegrenzen bestanden; UI folgt separat.

Abnahme: Bei abgeschaltetem Twenty wird genau ein Fall bestätigt und bleibt bearbeitbar. Nach Wiederanlauf entsteht eine nachvollziehbare Kontaktzuordnung ohne doppelten Fall. Timeout nach extern erfolgreichem Create führt zu Recovery oder sichtbarer Klärung. Wiederholungen, fremde Zugriffe und Wechsel der Zuständigkeit sind geprüft. Abschluss ist keine Förderzusage oder Auszahlung. Kein automatischer Mailversand.

## 8. Prüfgates und Nachweise

| Gate        | Erforderlicher Nachweis                                                                                                                   |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Architektur | Rekursive Importprüfung, keine neuen Zyklen oder fremden Schreibzugriffe; Review ergänzt die Grenzen statischer Importtests               |
| API         | Bestehende Contract-Gates; direkte Modulaufrufe und HTTP haben gleiche erlaubte/verbotene Ergebnisse; Replay nach Rechteentzug verweigert |
| Daten       | Migration mit Altbestand; atomarer Rollback zusammengesetzter Operationen; keine doppelten Zustände                                       |
| Jobs        | Echtes PostgreSQL: zwei Worker, Claim-Verlust, Absturz vor/nach Commit, Retry und Dead Letter; externe Nebenwirkung mit unklarem Ausgang  |
| Zeit        | Kontrollierbare Uhr für Fälligkeiten; Neustart/Nachholen, konkurrierende Scheduler; UTC und erforderliche lokale Zeitgrenzen              |
| Oberflächen | Pro betroffener Surface tatsächlicher Browserablauf; Direktlink, fehlende Rechte, mobile Bedienung, Lade-/Fehlerzustände                  |
| Bestand     | Passende vorhandene Survey-/Order-/Invoice-/Delivery-Prüfungen für berührte Pfade; vollständige erforderliche CI-Gates                    |
| Betrieb     | Gleiche Compose-Topologie, kompatible Health-/Operations-Anzeige, begrenzte Laufzeiten und vorhandene Backup-Pfade                        |

Vorhandene Testwerkzeuge und Runner verwenden; keine zusätzliche Testplattform. LIVE-Nachweise verwenden synthetische Daten und isolierte Compose-Projekte. Jeder fertiggestellte Schnitt dokumentiert Commit, Befehle, Ergebnis und verbleibende Grenze in einer erst dann angelegten `PROGRESS.md`. Keine grünen Abnahmehäkchen allein aufgrund von Unit-Tests oder einem erfolgreichen Build.

## 9. Rollout und Rücknahme

Refactoring und fachliche Erweiterungen in getrennten reviewbaren Änderungen liefern. M1 erhält URLs, API-Formate, Handler-Namen und Datenhaltung. Neue Tabellen/Felder additiv migrieren; destruktive Bereinigung erst nach bewiesener Umstellung. Beim Upgrade bestehende Jobs abarbeiten können und keinen Handler entfernen, solange sein Payload noch in der Queue liegt.

Vor jeder Etappe Rücknahme auf den vorherigen Code mit dem erweiterten Schema prüfen. Bereits geschriebene neue Fachobjekte oder neue Jobtypen können ein einfaches Code-Rollback verhindern; dann neuen Eingang stoppen, Jobs gezielt drainieren und kompatible Handler erhalten oder einen Forward-Fix ausrollen. Keine Module durch Ausblenden des Menüs als technisch zurückgenommen betrachten. Keine Tabellen, Volumes oder Nutzerdaten zur Rücknahme löschen.

- [x] Frühere API-Quellstände vor Registrierung, Tasks und Inbox mit erweitertem Schema prüfen: echter Lifespan, persistierte Sitzung, aktueller Kontosperrstatus und erhaltene neue Task-Daten. Reproduzierbarer Runner: `sh tools/schema/test.sh . code-rollback`. Heutige Python-Laufzeit; kein Nachweis für alte Images oder neue Jobtypen.
- [x] Wartungsablauf bei neuen Jobs mit gestopptem Eingang und erhaltenem kompatiblen Produktionsworker nachweisen: gespeicherter Inbox-Auftrag während API-Stopp abgeschlossen, danach API wieder gesund. Betriebsanleitung in `ROLLBACK.md`; kein Nachweis für einen alten Worker ohne neue Handler und keine solche Freigabe.

## 10. Abschlusskriterium

Die Grundlage ist nach M1 abgeschlossen, wenn ein bestehendes Modul über die Registrierung integriert ist, seine Fachoperationen transportunabhängig autorisiert sind, die Grenzen automatisch geprüft werden und bestehende Jobs/Surfaces unverändert funktionieren. M2 und M3 weisen anschließend nach, dass neue Funktionen diese Grundlage tatsächlich wiederverwenden. Kein Schritt benötigt pauschal weitere Dienste; jede spätere Infrastrukturentscheidung verlangt einen konkreten Bedarf und einen eigenen Nachweis.
