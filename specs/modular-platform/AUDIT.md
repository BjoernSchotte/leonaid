# Abschlussprüfung der modularen Plattform

Stand: 14.09.2026. M0–M3 und die Prüfgates aus [PLAN.md](PLAN.md) sind
abgenommen. Geprüfter letzter Implementierungs-/Teststand: `7869ed8`.
Die abschließende Änderung betrifft ausschließlich diese Dokumentation.
Historische Slice-Ergebnisse und damalige Grenzen stehen in
[PROGRESS.md](PROGRESS.md); die folgende Matrix nennt den Abschlussnachweis.

| Anforderung                                                | Abschlussnachweis                                                                                                                                        | Ergebnis                                                              |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| §1/3: Namespace, Dateneigentum, keine zusätzlichen Dienste | `src/leonaid/modules`, Plattform/Bootstrap getrennt; SQL-Review unten; Compose ergänzt nur zwei Twenty-Einstellungen am vorhandenen Worker.              | Bestanden                                                             |
| §3.1/3.2: Importgrenzen und azyklische Abhängigkeiten      | Rekursive Architekturtests mit ungültigen Import-/Zyklusfällen; manuelles SQL-/Transaktionsreview.                                                       | Bestanden                                                             |
| §4.1: explizite Registrierung und Startvalidierung         | Modul-/Handler-/Routenkollisionen und fehlende Abhängigkeiten vor App-Mutation geprüft; Inbox/Wissen verlangen Tasks/Materialien.                        | Bestanden                                                             |
| §4.1/M1: Survey-Handler und Sweep genau einmal             | Produktionsregistrierung, unveränderte Handler-Namen, vollständige Survey-, Export-, Versand-, Lösch- und Recovery-Gates.                                | Bestanden                                                             |
| §4.2: Web/PWA und bisherige Navigation                     | Geteilte UI-Beiträge, Direktlink-/Rollenprüfungen einschließlich Anna-Akquise, mobile Browserfälle und Nicht-gefunden-Zustand.                           | Bestanden                                                             |
| §4.3/M2: autorisierte Suche und stabile Referenzen         | Zwei-Konten-Suche, begrenzte Treffer, unabhängige Zielrechte; erhaltene Dateiversionen und Task-Identitäten.                                             | Bestanden                                                             |
| §5: direkte typisierte Fachoperationen und HTTP            | Datenbank-/HTTP-Verträge für jede Schreibgruppe unten; Rechteentzug beim Replay, Revision, Audit und atomare Receipts.                                   | Bestanden                                                             |
| §5.1: Task aus Seite atomar                                | Echter Transaktionsrollback nach Task-Anlage, paralleler Replay, Seitenkonflikt ohne Task; Web→PWA→Seite-Abnahme.                                        | Bestanden                                                             |
| §6: dauerhafte Jobs und Laufzeitgrenzen                    | Zwei echte Worker, Commit-/Claim-Verlust, Fencing, verzögerte Fälligkeit, DB-Sperrtimeout, SMTP-/Twenty-Ausfall und unklare externe Erfolge.             | Bestanden                                                             |
| §6/§8: Zeitsteuerung                                       | Separater Worker-Neustart, zwei nachweislich konkurrierende PostgreSQL-Sweeps, genau ein Abschluss; UTC-Grenzen und getrennte Zurückstellung/Fälligkeit. | Bestanden                                                             |
| M2: Tasks, Wissen, Materialien                             | Gemeinsame Web-/PWA-Abläufe, Freigabe/Entzug, Konfliktentwurf, wiederverwendete Materialien, exakte Versionsdownloads.                                   | Bestanden                                                             |
| M3: Inbox und öffentliche Eingänge                         | Web/PWA, Club-/Campaign-/Alias-Eingänge, Commit-Replay, Rate Limit, Kontaktklärung und automatischer Twenty-Wiederanlauf.                                | Bestanden                                                             |
| §8: Bestand und Betrieb                                    | Vollständige Haupt-CI, Survey-Abnahme und erweiterte Backup-/Recovery-/Upgrade-Gates; Operations-Ausfall und Job-Signale.                                | Bestanden                                                             |
| §9: additive Migration und Rücknahme                       | Altbestandmigration; drei frühere API-Stände mit erweitertem Schema; neuer Job bei API-Stopp mit kompatiblem Worker; voller Upgrade-Rollback.            | Bestanden                                                             |
| §10: Auslieferung                                          | Geprüfte Slices auf Draft-PR #7, Abschlussdokumentation und echte Browser-Screenshots in PR-Kommentaren.                                                 | Erbracht; abschließender Dokumentationspush gehört zu dieser Änderung |

## Endgültige CI-Zuordnung

Auf `7869ed8b50639117703df63f5f9f1cee84a19f6e` bestanden:

- [Haupt-CI 34801326600](https://github.com/BjoernSchotte/leonaid/actions/runs/34801326600), Versuch 1.
- [Survey-Abnahme 34801326723](https://github.com/BjoernSchotte/leonaid/actions/runs/34801326723), Versuch 2.
- [API-Contract 34801326478](https://github.com/BjoernSchotte/leonaid/actions/runs/34801326478).
- [Dependency-Pins 34801326552](https://github.com/BjoernSchotte/leonaid/actions/runs/34801326552).

Die [erweiterte Survey-/Backup-Abnahme 34798774994](https://github.com/BjoernSchotte/leonaid/actions/runs/34798774994)
bestand vollständig auf `bc3adab5e7d03eb3215de502a5632c537efb9944`, Versuch 2.
Sie umfasst Backup, Pilot-Import/-Deployment/-Release/-Backup, Upgrade sowie
Retention-, Receipt-, Pilot-, Export-, Restic- und Deletion-Recovery.
Der Diff von `bc3adab` zu `7869ed8` enthält ausschließlich den zusätzlichen
Lifecycle-Test und Dokumentation; `src`, `apps` und `packages` sind unverändert.
Deshalb gilt die erweiterte Produktabnahme weiter. Reguläre Survey-PR-Gates
werden nicht als Ersatz für ihre übersprungenen Nightly-Jobs gewertet.

Der erfolgreiche Upgrade-Bericht (Artefakt 10330794805) bestätigt `status=0`,
den exakten Commit und Abschluss am 14.09.2026 um 03:17:33 UTC. Das gelesene
Command-Log bestätigt reale Twenty-/RustFS-Upgrades, Golden Journeys jeweils
vorher/nachher/Rollback, Wartungsgrenze, Fehlermigration, Manifest-Promotion,
Recovery und Entfernung der eigenen Ressourcen. Die separaten lokalen Berichte
[Pilot-Recovery](proofs/pilot-recovery.json) und
[Upgrade/Rollback](proofs/upgrade-rollback.json) ergänzen diese CI-Evidenz.

Fehlgeschlagene Erstversuche bleiben nachvollziehbar: Upgrade erreichte zunächst
wegen einer nicht sichtbaren Twenty-Metadatenfeldanlage seine Prüfung nicht;
Foundation endete zunächst im Migrations-Check mit Exit 125. Die konkreten
Ursachen sind nicht rückwirkend bewiesen. Gezielte Wiederholungen mit
unveränderten Assertions bestanden; keine Produktprüfung wurde abgeschwächt.

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
Die M3-Zuordnung wird unten durch die echten Twenty-Ausfall- und
Antwortverlust-Nachweise vervollständigt.

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
Ihre Nachweise gelten deshalb weiter; die bestandene CI auf `7869ed8` prüft zusätzlich die Integration des
aktuellen Standes.

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
Chromium-Breitenmatrix besteht separat. Die Oberflächen- und Fachcodepfade sind seit dieser Abnahme unverändert.
Die vollständige CI auf `7869ed8` und die erweiterte Abnahme auf `bc3adab`
sind inzwischen bestanden.

## Zeitsteuerung und Grenzen der Abnahme

`tools/surveys/infrastructure.sh . lifecycle` bestand lokal als Lauf 38924 mit
Exit 0. Die ursprünglichen Fristenprüfungen stoppen den echten Worker, prüfen
abgelaufene Eingaben und lassen ihn nach Neustart genau einmal schließen.
Antworten und Teilnahme-Revisionen bleiben erhalten; Wiederöffnung ist gesperrt.

Der ergänzte `schedule.py compete` verwendet zwei separate PostgreSQL-Pools und
die unveränderte Produktionsoperation. Eine echte Tabellensperre hält beide
Aufrufe an; `pg_stat_activity` bestätigt beide gleichzeitig als aktiv wartend.
Nach Freigabe ergeben die beiden Ergebnisse genau `[0, 1]`, eine beendete Umfrage
und eine Revisionsänderung. Ein weiterer Worker-Neustart erhält diesen Stand.
Drei Chromium-Browserfälle und alle drei eigenen Cleanup-Inventare bestanden.
Die [visuell geprüften Screenshots](https://github.com/BjoernSchotte/leonaid/pull/7#issuecomment-5658401423)
zeigen die Desktop-Lifecycle-Ansicht und die mobile Designer-Rolle. Die Bilder
belegen die Oberfläche; der Datenbankvertrag belegt die Konkurrenz.

Es wurde kein zweiter periodischer Produktbedarf eingeführt. Daher entsteht
entsprechend §6.3 keine neue Schedule-Tabelle oder Kalender-Engine. MCP und ein
veröffentlichtes SDK bleiben ausdrücklich außerhalb von M0–M3. FastAPI und die
autorisierten direkten Fachoperationen bilden den späteren Adapteranschluss.

Die Rücknahmegrenzen aus [ROLLBACK.md](ROLLBACK.md) gelten: kein alter Worker
ohne neue Handler; neue Jobs nur mit kompatiblem Worker drainieren. Der lokale
Pilotnachweis verwendete einen vorher gesicherten Checkpoint und ein externes
S3-Ziel auf demselben Docker-Host. Er beweist keine automatische Wiedergewinnung
des neuesten Checkpoints nach unerwartetem Hostverlust. Diese ausdrücklich
beschriebenen Betriebsgrenzen werden nicht als zusätzliche Funktionen ausgegeben.
