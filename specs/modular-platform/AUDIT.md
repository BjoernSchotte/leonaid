# Abschlussprüfung der modularen Plattform

Status: laufend, keine Gesamtabnahme. Maßgeblich bleibt der vollständige Umfang von
[PLAN.md](PLAN.md), einschließlich M0–M3, Prüfgates und Rücknahme. Die historischen
Slice-Nachweise stehen in [PROGRESS.md](PROGRESS.md); dort genannte damalige offene
Grenzen gelten erst durch einen späteren passenden Nachweis als geschlossen.

Die folgende Matrix trennt aktuelle Codeprüfung von Laufzeitabnahme. Der zuletzt
gepushte Produktstand ist `bc3adab`. Modulabhängigkeiten, Runner-Korrekturen und
beide lokalen Recovery-Berichte sind ausgeliefert. Haupt-CI 34798766304 besteht
im zweiten Versuch vollständig; reguläre Survey-Abnahme 34798766283 ebenfalls.
Erweiterte Abnahme 34798774994 hat sämtliche Recovery-Shards einschließlich
Restic bestanden. Ausschließlich der Upgrade-Job scheiterte im ersten Versuch
bei der initialen Twenty-Feldprovisionierung. Versuch 2 dieses Jobs läuft.
Der ergänzte lokale Konkurrenznachweis für Fristen-Sweeps ist bestanden;
sein vollständiger Lifecycle-/Browser-Lauf ist noch nicht beendet.

| Anforderung                                                                  | Aktuell geprüfte Evidenz                                                                                                                                                                                                                    | Noch erforderlicher Abschluss                                                                               |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| §1/3: gemeinsamer Namespace, fachliches Eigentum, keine zusätzlichen Dienste | Module unter `src/leonaid/modules/`; Bootstrap und Plattform getrennt. Compose-Diff zum Ausgangspunkt ergänzt nur Twenty-Verbindungseinstellungen am vorhandenen Worker.                                                                    | Auf bc3adab geprüft: keine weitere Topologie- oder Paketänderung.                                           |
| §3.1/3.2: Importgrenzen, keine Zyklen oder privaten Modulimporte             | `tests/unit/test_architecture_boundaries.py` prüft rekursiv Plattform-Rückabhängigkeiten, Modulgrenzen und Infrastrukturimporte; absichtlich ungültige Imports und Zyklen werden erkannt.                                                   | Importprüfung und SQL-/Transaktionsreview zugeordnet; erneute Gesamt-CI läuft.                              |
| §4.1: statische Registrierung, fehlende Abhängigkeiten, Kollisionen          | `bootstrap/registry.py` prüft IDs, Abhängigkeiten und Zyklen sowie Routen vor App-Mutation. Tatsächliche Inbox-/Wissensbeiträge verlangen jetzt Tasks und Materialien; vier Weglassfälle geprüft.                                           | Ergänzung gepusht; CI auf bc3adab abnehmen.                                                                 |
| §4.1/M1: Survey-Handler und Sweep genau einmal                               | `modules/surveys/jobs.py` konstruiert die drei vorhandenen Handler; `bootstrap/worker.py` registriert diese und `surveys.deadlines`. Registry-Test bestätigt den tatsächlichen Sweep-Beitrag.                                               | Lokaler Pilot bestanden; erweiterten CI-Lauf abschließen.                                                   |
| §4.2: Web/PWA, Rechte und bestehende Navigation                              | Beide Shells verwenden die Modulauflösung; gemeinsame Beiträge liegen im Features-Paket. Web besitzt einen Nicht-gefunden-Zustand. Bisherige Rollen-/Browsernachweise sind in PROGRESS dokumentiert.                                        | Separater Rollen-/Direktlinknachweis und sieben Browserfälle zugeordnet; neue CI läuft.                     |
| §4.3/M2: begrenzte autorisierte Suche und stabile Verweise                   | Gemeinsamer UI-Vertrag beschränkt Suchtypen auf Task, Wissensseite und Material; Fachoperationen bleiben Ziel der Beiträge.                                                                                                                 | Zwei-Konten-Suche, Zielrechte und mobile Darstellung separat nachgewiesen.                                  |
| §5: typisierte direkte Operationen, Rechte, Replay, Revisionen               | Direkte APIs, HTTP-Routen und echte Datenbankverträge vorhanden; bisherige Einzelabnahmen in PROGRESS.                                                                                                                                      | Schreibgruppen unten vollständig ihren Datenbank-/HTTP-Verträgen zugeordnet; neue CI läuft.                 |
| §5.1: Task aus Seite atomar                                                  | `knowledge/repository.py` hält die äußere Transaktion; Bootstrap injiziert Task-Service mit derselben Verbindung. `tools/knowledge/task_contract.py` prüft Konkurrenz, Revision, fremde Rechte und vollständigen Rollback nach Task-Anlage. | Zugehörigen vollständigen Schema-/Browser-Gate auf finalen CI-Stand beziehen.                               |
| §6: bestehende Queue, verzögertes Enqueue, Claim-Fencing, Retry und Laufzeit | Produktions-Outbox und dokumentierte PostgreSQL-/Export-/Operations-Nachweise vorhanden; kein zweites Queue-System.                                                                                                                         | Echte Queue-, Timeout-, CRM-Ausfall- und Operations-Nachweise zugeordnet; neue CI läuft.                    |
| M2: Tasks, Wissen, Materialien und gemeinsamer Ablauf                        | Implementierte Module und dokumentierte reale Web-/PWA-, Datenbank- und RustFS-Verträge.                                                                                                                                                    | Fachabnahmen mit unverändertem Modulcode zugeordnet; übergreifende CI bleibt offen.                         |
| M3: Inbox, öffentliche Eingänge und Twenty-Recovery                          | Implementiertes Inbox-Modul und dokumentierte echte Ausfall-, Replay-, Rechte- und Browsernachweise.                                                                                                                                        | Public-/Campaign-Alias, Falloberflächen und automatischer Wiederanlauf separat zugeordnet; neue CI läuft.   |
| §8: vorhandene CI und Betrieb                                                | Upgrade-Bericht `.artifacts/poc113/result.json` bestätigt vollständigen Lauf einschließlich drei Golden Journeys, Fehlermigration und Rollback.                                                                                             | Lokaler Pilot bestanden; vollständige reguläre und erweiterte CI auf bc3adab.                               |
| §9: additive Migration und Rücknahme                                         | Getrennte Nachweise und Grenzen in [ROLLBACK.md](ROLLBACK.md).                                                                                                                                                                              | Drei frühere API-Stände und separater neuer Job bei API-Stopp geprüft; Grenzen unten festgehalten.          |
| §10: vollständige Auslieferung                                               | Draft-PR #7 bleibt Ziel; Screenshot-Kommentare sind Bestandteil der bisherigen Browsernachweise.                                                                                                                                            | Offene Gates schließen, alle Änderungen pushen, Plan und diese Matrix erst danach auf abgeschlossen setzen. |

Aktueller gezielter Start-/Architekturtest: 31 bestanden, neun bestehende
Pydantic-Aliaswarnungen; Ruff, Formatprüfung, No-Test-Doubles und Diffprüfung
bestanden. Dies ersetzt keine der in der Matrix noch offenen Laufzeitprüfungen.

Während des manifestgebundenen Pilot-Laufs bleibt Git-HEAD unverändert. Seine
gebauten Images enthalten die nachträgliche Abhängigkeitsergänzung nicht; sein
Ergebnis darf deshalb nicht als Test dieser Ergänzung ausgegeben werden.

Aktualisierung: Der Pilot-Lauf 78399 ist inzwischen vollständig mit Exit 0
beendet; alle zwölf Ressourceninventare seiner vier Projekte sind leer.
Die Commit-Sperre ist aufgehoben. Die in der Matrix verlangte lokale
Pilot-Abnahme ist damit erbracht; der neue Remote-Nightly-Lauf bleibt offen.
Die geprüften Berichte liegen unter [Pilot-Recovery](proofs/pilot-recovery.json)
und [Upgrade/Rollback](proofs/upgrade-rollback.json), Ablauf und Grenzen in
PROGRESS. Die Gesamtprüfung ist weiterhin nicht abgeschlossen.

## Zugeordnete Nachweise: Queue und bestehende CI

Die GitHub-Abfrage bestätigt Haupt-CI
[34793420688](https://github.com/BjoernSchotte/leonaid/actions/runs/34793420688)
und reguläre Survey-Abnahme
[34793420719](https://github.com/BjoernSchotte/leonaid/actions/runs/34793420719)
mit `success` auf dem exakten Commit
`1ee033925a46200ff7aa0c1bbbd8ee368271aa62`. Die Survey-PR-Abnahme überspringt
ihre Nightly-Jobs ausdrücklich; ihr grüner Recovery-Sammelcheck wird nicht als
Nachweis der dabei nicht ausgeführten erweiterten Recovery-Shards gewertet.

Für §6 und das Jobs-Gate ist die Zuordnung zum tatsächlich ausgeführten Code
geprüft: `tools/ci/integration.sh schema-outbox` ruft den vollständigen
Schema-Runner und anschließend `tools/outbox/test.sh` auf. Dieser bestand in
der genannten Haupt-CI. Der Outbox-Runner prüft:

- Producer-Abbruch nach Commit vor Dispatch und Wiederaufnahme des gespeicherten
  Auftrags durch einen echten Worker.
- Zwei eigenständige Worker-Prozesse auf derselben PostgreSQL-Queue und den
  anschließenden Abgleich von 20 Aufträgen.
- Tatsächlichen Mailpit-Stopp, drei erfolglose Zustellversuche bis Dead Letter,
  manuellen Retry nach Wiederanlauf und fachlich idempotenten Replay.
- Atomaren Rollback eines verzögerten Auftrags, gespeicherten Zeitpunkt,
  Nichtbeanspruchung eine Mikrosekunde vor Fälligkeit, Claim bei Fälligkeit und
  Übernahme nach Lease-Ablauf. Ein alter Claim kann weder abschließen noch eine
  zweite Aktivitätsprojektion hinterlassen (`verify_delayed_fencing`).
- Eine echte exklusive PostgreSQL-Sperre gegen den Aktivitäts-Handler. Die
  Worker-Frist bricht vor Lease-Ablauf ab, speichert nur `job_timeout`, hinterlässt
  keine Fachänderung und verarbeitet nach Freigabe genau eine Projektion
  (`verify_handler_timeout`).

Der Produktcode begrenzt Survey-Exports auf höchstens 240 Sekunden und Inbox-
Kontaktjobs auf höchstens 90 Sekunden, jeweils zusätzlich auf 80 Prozent der
konfigurierten Lease. Der Typst-Unterprozess besitzt einen eigenen Timeout.
`OutboxWorker` speichert sichere Fehlercodes statt roher Exceptions; permanente
Fehler verwenden keinen weiteren automatischen Versuch. Diese Codeprüfung
ergänzt die tatsächlichen Laufzeitnachweise, ersetzt sie nicht.

Für die externe Nebenwirkung besitzt `InboxContactHandler` eine vor dem
Twenty-Aufruf committete Create-Absicht und prüft den aktuellen Claim bei jeder
Statusänderung. Wiederaufnahme sucht die exakte vorgesehene Twenty-ID und
vergleicht den Snapshot; ein ungeklärter Ausgang endet in `needs_review`.
Die endgültige M3-Zuordnung muss zusätzlich die vorhandenen echten Twenty-
Ausfall-/Antwortverlust-Nachweise enthalten.

## Zugeordnete Nachweise: dauerhafter Modul-Browser-Gate

`tools/ci/e2e.sh modules` startet `tools/testing/modular_browser.sh` im isolierten
Produktionsstack. Der erfolgreiche Job `E2E leaf / modules` des oben genannten
CI-Laufs führt sieben konkrete Playwright-Fälle aus. Die Testdateien wurden für
diese Zuordnung gelesen:

| Fälle                          | Tatsächliche Assertions                                                                                                                                                                                                                                                                                         |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tasks, Web und PWA             | Liste und Task über UI anlegen, eigene Zuständigkeit wählen, Fälligkeit und Zurückstellung getrennt speichern. „Für mich“ blendet zurückgestellte Tasks aus; gezieltes Einblenden, Zurückstellung entfernen und Erledigen erhalten dieselbe Fälligkeit. Kein horizontaler Überlauf bei 390 px.                  |
| Wissen, Web und PWA            | Seite anlegen und Inhalt speichern; über die jeweils andere Shell denselben Stand lesen. Konkurrierendes Speichern erzeugt einen sichtbaren Konflikt und erhält den lokalen Entwurf. Abgelehntes Neuladen erhält ihn weiter, bestätigtes Neuladen übernimmt den tatsächlich gespeicherten Inhalt.               |
| Materialien/Inbox, Web und PWA | Zwei echte Dateiversionen hochladen, erste Version in Inbox referenzieren und nach dem zweiten Upload sowohl aus Materialansicht als auch Inbox bytegenau herunterladen. Verweis entfernen erhält das Material. Ein anderes Konto sieht am Direktlink weder Titel noch Download.                                |
| Öffentliches Inbox-Formular    | Tatsächlichen HTTP-201-Commit ausführen und dessen Rückantwort im Transport verwerfen. Echte Folgeanfragen erreichen das serverseitige Rate Limit. Der Browser wiederholt denselben Befehl, erhält den Entwurf gesperrt und meldet nach HTTP 429 weiterhin den unklaren Ausgang. Keine erfundene Serverantwort. |

Die Tests erzeugen reale Browserbilder im separaten Ergebnisverzeichnis.
Screenshot-Kommentare früherer lokaler Abnahmen sind in PROGRESS aufgeführt.
Diese sieben Fälle ersetzen insbesondere nicht die separaten Nachweise für
Task-Anlage aus einer Wissensseite, Freigabeentzug, Aktionsrollen,
Campaign-/Alias-Einreichung oder tatsächlichen Twenty-Ausfall. Diese bleiben
Bestandteil des vollständigen Abgleichs und werden nicht aus dem Namen des
Modul-Sammelchecks abgeleitet.

Die Schema-Zuordnung ist ebenfalls geprüft: `tools/schema/test.sh` ruft die
Task-, Wissens-, Material- und Inbox-Verträge tatsächlich auf, einschließlich
HTTP, Mitgliedschaften, Aktionsrechten, zusammengesetzter Task-Anlage,
Materialverweisen und Upload-Bereinigung; anschließend prüft er den
versionierten Altbestand. Der separate Modus `code-rollback` ist eine eigene
Abnahme und wird nicht durch den normalen Schema-Job behauptet.

## Zugeordnete Nachweise: Inbox und tatsächlicher Twenty-Ausfall

Der erfolgreiche CI-Job `Integration / crm-gateway` verwendet über
`tools/ci/integration.sh` den Runner `tools/twenty/gateway_test.sh`. Dieser stoppt
den echten Twenty-Server, führt `tools/inbox/jobs_contract.py expect-outage`
aus, startet Twenty wieder und führt den Vertrag in einem neuen Prozess mit
`verify-after-restart` fort.

Der gelesene Vertrag bestätigt bei Ausfall einen einzigen idempotent angelegten
Fall, einen wartenden Retry und weitere Fallbearbeitung trotz fehlender
Kontaktzuordnung. Nach Wiederanlauf konstruiert er den Produktionsworker erneut
und verarbeitet denselben gespeicherten Auftrag. Sein zusätzlicher
`timeout_after_real_create`-Fall leitet echte HTTP-Bytes an Twenty weiter und
hält ausschließlich die tatsächlich erfolgreiche Create-Rückantwort zurück.
Damit wird der unklare Ausgang eines externen Erfolgs geprüft, ohne einen
CRM-Erfolg zu erfinden. Der Vertrag enthält außerdem exakte ID-/Snapshot-
Prüfung, sichtbare Klärung bei fehlendem Nachweis, Schutz gegen einen alten
Claim und manuelle Zuordnung mit Rechte-/Revisionsprüfung.

Diese CI-Evidenz betrifft den genannten gepushten Produktstand. Die separat
dokumentierten öffentlichen Browser-, Campaign- und Alias-Nachweise bleiben
zusätzlich erforderlich; der CRM-Vertrag ersetzt keine Oberflächenabnahme.

## Fortgeltung der separaten Fach- und Rücknahmenachweise

Der aktuelle Diff von `c6dcaae` bis `bc3adab` unter `src`, `packages` und `apps`
enthält ausschließlich die vollständigen `requires`-Einträge im API-Bootstrap
und die Entfernung des globalen sanften Scrollens. Die zuvor abgenommenen
Fachoperationen, SQL-Regeln, Module und Formulare wurden seither nicht geändert.
Ihre Nachweise gelten deshalb weiter; die laufende CI prüft zusätzlich die
Integration des jetzigen Standes.

Die separaten M2-Abnahmen in PROGRESS decken den zusammengesetzten Ablauf ab:
Web-Seite speichern, über denselben Editor einen Task anlegen und zuweisen,
in der PWA „Für mich“ erledigen und den geänderten Status in der Seite lesen.
Ein konkurrierender Seitenzugriff erzeugt 409 mit erhaltenem Aufgabenentwurf
und ohne neuen Task. Der reale Datenbankvertrag ergänzt dies um atomaren
Rollback bei Dokumentgrenzen und parallelen Replay. Die Freigabeabnahme prüft
Lesen → Bearbeiten → Speichern in PWA → Entzug → HTTP 404 mit zwei Sitzungen.
Die Aktionsverträge für Tasks, Wissen und Materialien verwenden jeweils zehn
Identitäten und prüfen auch abgelaufene/künftige Mitgliedschaft und Replay nach
Entzug. Diese Verträge sind im vollständigen Schema-Gate registriert.

Die getrennte Suchabnahme zeigt in Web und PWA genau die drei eigenen Treffer
für Task, Wissensseite und Material; fremde private Titel bleiben unsichtbar.
Der vorhandene mobile Screenshot wurde im Abschlussabgleich erneut angesehen:
alle drei Ergebnisarten, mobile Navigation und Bedienung sind sichtbar. Die
Berechtigungsbehauptung beruht auf dem dokumentierten Zwei-Konten-Ablauf und
den Datenbankverträgen, nicht allein auf diesem Bild.

Für §9 ist der tatsächlich ausgeführte Rollback-Runner geprüft:
`tools/schema/test.sh . code-rollback` lädt drei feste Git-Quellstände aus
Archiven, ohne den Checkout zu ändern, und prüft mit echtem FastAPI-Lifespan
persistierte Sitzung, tatsächliche Kontosperrung, erhaltene Task-Daten und
unveränderte Schema-Revision. Der dokumentierte lokale Lauf 60135 ist bestanden.
Dies ist bewusst ein Quellcode-/Schema-Nachweis in der aktuellen Python-Laufzeit.

Der separate erhaltene Bericht `/tmp/leonaid-rollback-jobs-result.json`
bestätigt den API-Stopp mit HTTP 502 sowie denselben Inbox-Auftrag mit
`linked/completed`, einem Versuch und `manual_retry_count: 0`. Zusammen mit
dem dokumentierten erfolgreichen Lauf 75299 belegt er das Drainieren durch
den kompatiblen Produktionsworker. [ROLLBACK.md](ROLLBACK.md) erlaubt daraus
ausdrücklich keinen alten Worker ohne neue Handler und verlangt den Erhalt
offener Jobs und Daten. Diese beiden Nachweise decken verschiedene Grenzen ab.

## Architektur- und Betriebsvergleich mit dem Ausgangsstand

Der vollständige Diff von `2043b72` bis `bc3adab` für `pyproject.toml` ist leer.
In `infra/compose/compose.yml` kommen ausschließlich zwei Twenty-
Verbindungseinstellungen am vorhandenen Worker hinzu. Die Modulanzahl erzeugt
keine weiteren Dienste, Datenbanken oder Queue-Systeme.

Unter den bisherigen Domain-, Application-, Adapter- und Entrypoint-
Verzeichnissen liegen keine Survey-Implementierungsdateien mehr. Die
Prozess-Startpfade bleiben erhalten. Der Worker-Entrypoint startet ausschließlich
den in Bootstrap konstruierten Worker, die Datenbank-Readiness und die
registrierten Hintergrundbeiträge. Die Survey-Handler und der Fristenlauf
werden im Modul konstruiert und genau einmal über Bootstrap eingebunden.

Ein direkter Inhaltsvergleich mit dem Ausgangscommit bestätigt für
`survey_retention.py`, `survey_deletion.py` und `survey_checkpoint_publisher.py`
ausschließlich geänderte Imports beziehungsweise deren Formatierung. Die
Aufbewahrungssperren, begrenzten Batches, Löschaufträge und Veröffentlichung
offener Checkpoints wurden bei der Migration nicht ersetzt. Der vorhandene
Sweep bleibt der einzige periodische Fachbeitrag; gemäß §6.3 wird ohne zweiten
konkreten Bedarf keine zusätzliche Schedule-Tabelle oder Kalender-Engine
eingeführt. Die erweiterten Recovery-Gates prüfen die Laufzeitkompatibilität
dieser erhaltenen Abläufe zusätzlich.

## Schreiboperationen und Dateneigentum

Die SQL-Inventarisierung der vier neuen Module bestätigt fachliche Writes nur
auf `task*`, `knowledge_page*`, `material*` beziehungsweise `inbox_case*`.
Zusätzlich verwenden sie die gemeinsame Audit-/Receipt-Infrastruktur; Inbox
verknüpft und beendet ihren eigenen Auftrag in der vorhandenen Outbox. Wissen
schreibt Task-Daten über den injizierten öffentlichen Task-Service, nicht mit
eigenem Task-SQL. Die Suche schreibt keinen zusätzlichen Fachbestand.
Die Inventarisierung ergänzt die manuelle Transaktionsprüfung; sie ist kein
allgemeiner SQL-Parser oder Ersatz für die laufenden Datenbankverträge.

| Schreibgruppe                                                        | Zugeordnete vorhandene Verträge                                                                                                                                                             |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Task-Listen und Tasks anlegen/ändern, Zuständigkeit und Zeitpunkte   | `tools/tasks/service_contract.py`, `http_contract.py`, `action_contract.py`; Web-/PWA-Taskfall                                                                                              |
| Epics anlegen/umbenennen und Listenmitglieder verwalten              | Task-HTTP-Vertrag für Epic-Erstellung, Umbenennung, Revision und Replay; Service-/Aktionsvertrag für Mitglieder und Objektgrenzen                                                           |
| Wissensseiten anlegen/ändern und Freigaben setzen                    | `tools/knowledge/service_contract.py`, `http_contract.py`, `action_contract.py`, `member_contract.py`; Zwei-Sitzungen-Konflikt und Freigabe-/Entzugsablauf                                  |
| Task aus Seite und Materialreferenzen in Seiten                      | `tools/knowledge/task_contract.py`, `material_contract.py`; äußerer Rollback, stabile Referenz und getrennte Zielrechte                                                                     |
| Material anlegen, Version anhängen, Freigaben und Upload-Bereinigung | `tools/materials/service_contract.py`, `http_contract.py`, `member_contract.py`, `action_contract.py`, `cleanup_contract.py`; echte RustFS-Versionen, Fehler nach Upload und Wiederaufnahme |
| Öffentlicher Inbox-Eingang und Fallbearbeitung                       | `tools/inbox/submission_contract.py`, `public_contract.py`, `case_contract.py`, `http_contract.py`; atomarer Eingang und aktueller Fallzugriff                                              |
| Kommentare und Task-/Materialverweise im Fall                        | `tools/inbox/case_contract.py`, `task_contract.py`, `material_contract.py`; Rechteentzug, Replay, Revisionen und unabhängige Objektlebensdauer                                              |
| Twenty-Kontaktauftrag und bewusste Bestätigung                       | `tools/inbox/jobs_contract.py` im tatsächlichen CRM-Ausfallrunner; exakte Korrelation, konkurrierende Bestätigung und atomarer Abschluss                                                    |

Die API-Module stellen typisierte Operationen bereit und validieren veränderbare
Eingaben erneut. HTTP verwendet diese Fachoperationen; Sitzungs-/CSRF- und
Transportgrenzen kommen dort hinzu. Private Datei-/Objektzugriffe werden auch
beim Replay erneut geprüft. Ein Menüeintrag oder gespeicherter Personenbezug
ersetzt keine aktuelle Objektberechtigung.

## Öffentliche Inbox-Surfaces und Wiederanlauf

Die getrennten Nachweise in PROGRESS umfassen Club-Startseite, veröffentlichten
Public-Alias und die tatsächlich im CMS publizierte kanonische Campaign-Seite.
`tools/inbox/public_form_routes.py --campaign --campaign-alias` prüft die 302-
Weiterleitung für GET und HEAD sowie 308 auf die kanonische Slash-URL. Er prüft
auch die Formular-Aktions-ID, fehlende Bestellfreigabe und die jeweils erlaubten
Formulare. `browser_receipt.py --linked` verlangt einen Fall samt Auftrag,
richtige Aktion, erhaltene Bearbeitungsrevision und genau einen korrelierten
Twenty-Kontakt. Die aktuellen Assertions beider Werkzeuge wurden abgeglichen.

Der öffentliche Twenty-Ausfallablauf weist Bestätigung und weitere Bearbeitung
nach, erreicht dabei aber absichtlich Dead Letter und verwendet anschließend
den autorisierten manuellen Retry. Davon getrennt bestätigt der dokumentierte
automatische Wiederanlauf denselben ursprünglichen Auftrag mit vier Versuchen,
`manual_retry_count=0` und genau einem Kontakt nach Twenty-/Worker-Neustart.
Damit wird die automatische Erholung nicht aus einem manuellen Retry abgeleitet.

Die verlorene Commit-Bestätigung wurde an einer echten Campaign-Einreichung
geprüft; identischer Replay bestätigt dieselbe Referenz und hinterlässt nur
einen Fall. Die spätere dauerhafte 429-Folgeprüfung und die Web-/PWA-Downloads
schließen die in früheren Einzelnachweisen genannten offenen Grenzen.
Der vollständige Public-Katalog-Gate mit drei Browsern und zusätzlicher
Chromium-Breitenmatrix besteht separat. Die Oberflächen- und Fachcodepfade sind
seit dieser Abnahme unverändert; die laufende CI auf bc3adab bleibt der noch
offene übergreifende Nachweis.

## Aktueller erweiterter CI-Abgleich auf bc3adab

Die erneute GitHub-Abfrage bestätigt den exakten Head
`bc3adab5e7d03eb3215de502a5632c537efb9944` für Lauf
[34798774994](https://github.com/BjoernSchotte/leonaid/actions/runs/34798774994).
Backup, Pilot-Import, Pilot-Deployment, Pilot-Release und Pilot-Backup sind
erfolgreich abgeschlossen. Ebenfalls bestanden sind die Survey-Shards
`recovery-retention`, `restore-receipts`, `recovery-pilot`, `exports-recovery`
und `recovery-deletion`. `recovery-restic` ist weiterhin in Arbeit.

Der fehlgeschlagene Upgrade-Job erreicht die eigentliche Upgrade-/Rollback-
Prüfung nicht: Die anfängliche Twenty-Provisionierung sieht das angelegte
Personenfeld nicht innerhalb ihres bestehenden Zeitlimits. Die Ursache ist
noch nicht bewiesen. Der erfolgreiche lokale Upgrade-Bericht bleibt ein
separater Nachweis; er macht diesen Remote-Fehler nicht grün. Nach Abschluss
des laufenden Elternlaufs wird ausschließlich der fehlgeschlagene Job erneut
gestartet, ohne Assertions oder Zeitgrenzen zu ändern.

## Noch zu schließender Zeitsteuerungsnachweis

Die gelesenen Runner `tools/surveys/schedule.py` und `timeouts.py` werden durch
`infrastructure.sh` mit echtem Worker-Stopp und -Neustart ausgeführt. Sie prüfen
Nachholen, unveränderte Antworten und Teilnahme-Revisionen sowie ausbleibende
Doppelrevision nach einem weiteren Sweep. Der Schedule-Vertrag weist außerdem
naive Zeitangaben zurück und prüft UTC-Zeitpunkte.

Diese sequenziellen Wiederholungen beweisen für sich allein keine konkurrierenden
Scheduler. Für das explizite Zeit-Gate aus §8 ist noch ein gezielter Abgleich
beziehungsweise ein realer Datenbanknachweis konkurrierender Fristen-Sweeps
erforderlich. Die bestehende Zwei-Worker-Queue-Prüfung deckt diese andere
Operation nicht automatisch ab.

Aktualisierung: Lauf 34798774994, Versuch 1, ist beendet. Auch
`recovery-restic` ist erfolgreich; ausschließlich `test-upgrade` scheiterte.
Der gezielte Wiederholungslauf über `gh run rerun 34798774994 --failed` wurde
erfolgreich angefordert. Die Assertions und Zeitgrenzen bleiben unverändert.

Für die Sweep-Konkurrenz erweitert `schedule.py compete` den vorhandenen
Lifecycle-Runner: Zwei separate PostgreSQL-Pools führen die Produktionsoperation
aus. Eine echte Tabellensperre hält beide an; `pg_stat_activity` muss beide
als aktiv und auf eine Sperre wartend bestätigen. Nach Freigabe werden genau
ein Abschluss und eine Revisionsänderung verlangt. Der unveränderte vorherige
Neustart-Test und die Antwort-/Revisionsprüfung laufen weiterhin separat.
Der vollständige lokale Lifecycle-Lauf ist gestartet; noch keine Abnahme.

Zwischenergebnis des lokalen Lifecycle-Laufs 38924: Der bestehende echte
Worker-Neustart ist bestanden. Auch `schedule.py compete` bestätigt nach
beobachteter PostgreSQL-Sperrkonkurrenz genau einen Abschluss durch die zwei
Produktionsaufrufe. Die nachgelagerte Antwort-/Revisionsprüfung und der gesamte
Browser-/Cleanup-Abschluss bleiben abzuwarten; der Slice ist noch nicht
als vollständig abgenommen markiert.

Abschluss des lokalen Lifecycle-Laufs 38924: Exit 0, drei Browserfälle
bestanden, beide Modul-Screenshots angesehen und alle drei eigenen
Ressourceninventare leer. Damit ist der oben offene Konkurrenznachweis
einschließlich unveränderter Antworten/Revisionen geschlossen. Der separate
Upgrade-Wiederholungslauf bleibt offen. Details in PROGRESS.
