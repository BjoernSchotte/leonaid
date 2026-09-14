# Abschlussprüfung der modularen Plattform

Status: laufend, keine Gesamtabnahme. Maßgeblich bleibt der vollständige Umfang von
[PLAN.md](PLAN.md), einschließlich M0–M3, Prüfgates und Rücknahme. Die historischen
Slice-Nachweise stehen in [PROGRESS.md](PROGRESS.md); dort genannte damalige offene
Grenzen gelten erst durch einen späteren passenden Nachweis als geschlossen.

Die folgende Matrix trennt aktuelle Codeprüfung von Laufzeitabnahme. Der zuletzt
gepushte Produktstand ist `1ee0339`; die lokale Ergänzung der Modulabhängigkeiten
und die Runner-Korrekturen benötigen noch einen Push und CI auf diesem Stand.

| Anforderung                                                                  | Aktuell geprüfte Evidenz                                                                                                                                                                                                                    | Noch erforderlicher Abschluss                                                                                   |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| §1/3: gemeinsamer Namespace, fachliches Eigentum, keine zusätzlichen Dienste | Module unter `src/leonaid/modules/`; Bootstrap und Plattform getrennt. Compose-Diff zum Ausgangspunkt ergänzt nur Twenty-Verbindungseinstellungen am vorhandenen Worker.                                                                    | Abschließenden Diff des ausgelieferten Standes prüfen.                                                          |
| §3.1/3.2: Importgrenzen, keine Zyklen oder privaten Modulimporte             | `tests/unit/test_architecture_boundaries.py` prüft rekursiv Plattform-Rückabhängigkeiten, Modulgrenzen und Infrastrukturimporte; absichtlich ungültige Imports und Zyklen werden erkannt.                                                   | SQL-Eigentum bleibt zusätzlich manuell zu prüfen; Importtests allein beweisen es nicht.                         |
| §4.1: statische Registrierung, fehlende Abhängigkeiten, Kollisionen          | `bootstrap/registry.py` prüft IDs, Abhängigkeiten und Zyklen sowie Routen vor App-Mutation. Tatsächliche Inbox-/Wissensbeiträge verlangen jetzt Tasks und Materialien; vier Weglassfälle geprüft.                                           | Lokale Ergänzung pushen und CI abnehmen.                                                                        |
| §4.1/M1: Survey-Handler und Sweep genau einmal                               | `modules/surveys/jobs.py` konstruiert die drei vorhandenen Handler; `bootstrap/worker.py` registriert diese und `surveys.deadlines`. Registry-Test bestätigt den tatsächlichen Sweep-Beitrag.                                               | Vollständigen Pilot-Recovery-Lauf und erweiterten CI-Lauf abschließen.                                          |
| §4.2: Web/PWA, Rechte und bestehende Navigation                              | Beide Shells verwenden die Modulauflösung; gemeinsame Beiträge liegen im Features-Paket. Web besitzt einen Nicht-gefunden-Zustand. Bisherige Rollen-/Browsernachweise sind in PROGRESS dokumentiert.                                        | Nachweiskette für jede betroffene Surface mit finalem CI-Stand abgleichen.                                      |
| §4.3/M2: begrenzte autorisierte Suche und stabile Verweise                   | Gemeinsamer UI-Vertrag beschränkt Suchtypen auf Task, Wissensseite und Material; Fachoperationen bleiben Ziel der Beiträge.                                                                                                                 | Vollständige Rechte-/Such- und Browsernachweise gegen die Anforderungen abgleichen.                             |
| §5: typisierte direkte Operationen, Rechte, Replay, Revisionen               | Direkte APIs, HTTP-Routen und echte Datenbankverträge vorhanden; bisherige Einzelabnahmen in PROGRESS.                                                                                                                                      | Alle implementierten Schreiboperationen und ihren passenden Vertrag systematisch zuordnen.                      |
| §5.1: Task aus Seite atomar                                                  | `knowledge/repository.py` hält die äußere Transaktion; Bootstrap injiziert Task-Service mit derselben Verbindung. `tools/knowledge/task_contract.py` prüft Konkurrenz, Revision, fremde Rechte und vollständigen Rollback nach Task-Anlage. | Zugehörigen vollständigen Schema-/Browser-Gate auf finalen CI-Stand beziehen.                                   |
| §6: bestehende Queue, verzögertes Enqueue, Claim-Fencing, Retry und Laufzeit | Produktions-Outbox und dokumentierte PostgreSQL-/Export-/Operations-Nachweise vorhanden; kein zweites Queue-System.                                                                                                                         | Zeit-, Crash-, Nebenwirkungs- und Betriebsnachweise einzeln im finalen Abgleich zuordnen.                       |
| M2: Tasks, Wissen, Materialien und gemeinsamer Ablauf                        | Implementierte Module und dokumentierte reale Web-/PWA-, Datenbank- und RustFS-Verträge.                                                                                                                                                    | Alle M2-Unterpunkte und Abnahmesätze abschließend gegen diese Nachweise prüfen.                                 |
| M3: Inbox, öffentliche Eingänge und Twenty-Recovery                          | Implementiertes Inbox-Modul und dokumentierte echte Ausfall-, Replay-, Rechte- und Browsernachweise.                                                                                                                                        | Alle M3-Unterpunkte einschließlich Public-/Campaign-Alias und automatischem Wiederanlauf abschließend zuordnen. |
| §8: vorhandene CI und Betrieb                                                | Upgrade-Bericht `.artifacts/poc113/result.json` bestätigt vollständigen Lauf einschließlich drei Golden Journeys, Fehlermigration und Rollback.                                                                                             | Pilot-Recovery und neue erweiterte Remote-Abnahme nach Push; vollständige CI des endgültigen Codes.             |
| §9: additive Migration und Rücknahme                                         | Getrennte Nachweise und Grenzen in [ROLLBACK.md](ROLLBACK.md).                                                                                                                                                                              | Befehle, Schema-/Jobgrenzen und zugehörige Ergebnisse im abschließenden Abgleich prüfen.                        |
| §10: vollständige Auslieferung                                               | Draft-PR #7 bleibt Ziel; Screenshot-Kommentare sind Bestandteil der bisherigen Browsernachweise.                                                                                                                                            | Offene Gates schließen, alle Änderungen pushen, Plan und diese Matrix erst danach auf abgeschlossen setzen.     |

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
