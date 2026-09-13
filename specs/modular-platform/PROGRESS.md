# Modularisierung: Fortschritt und Nachweise

## M0.1 — Ausgangsstand und Survey-Inventar

Status: abgeschlossen am 13.09.2026. Ausgangscommit `b82ac45`; Slice-Commit ist der Commit, der diesen Abschnitt anlegt. Implementierung und LIVE-Abnahme von M0–M3 sind weiterhin offen.

Der per GitHub API gelesene Hauptbranch ist `2043b72b7c5453b37978f2a58436243dbc378a00` und entspricht der Spec-Basis. Der Worktree war sauber. Keine Migration, kein laufender Dienst und keine fachlichen Daten wurden verändert.

### Eigentum und Abhängigkeiten des ersten Moduls

| Bereich                       | Bestehender Pfad / Vertrag                                                                                 | Einordnung für Migration                                                                                   |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Definitionen und Lebenszyklus | `domain/surveys/`, `application/surveys/`, `adapters/postgres/surveys.py`                                  | Survey-Modul; `SurveyService` delegiert heute an einen Persistence-Port                                    |
| Transport                     | `entrypoints/fastapi/surveys.py`                                                                           | Survey-Router einschließlich Pydantic-Eingaben; Sitzung, CSRF und Body-Grenzen erhalten                    |
| Identität                     | `domain/identity.py`, `domain/policies.py`                                                                 | Gemeinsame Identität und Aktionszugriffsprüfung; keine neue Identitätskopie                                |
| Analyse/Antworten             | `application/surveys/{analysis,analysis_snapshot,response_selection}.py`, entsprechende PostgreSQL-Adapter | Survey-eigen; Analyse-/Antwortauswahl nicht in globale Plattform verschieben                               |
| Exporte                       | `application/surveys/exports.py`, `adapters/postgres/survey_exports.py`                                    | Survey-eigene Jobs mit gemeinsamem Storage, Queue und Typst-Adapter                                        |
| Löschung/Recovery             | `adapters/postgres/survey_{deletion,retention,recovery,checkpoint_publisher}.py`                           | Fachliche Lösch- und Wiederherstellungsregeln bleiben Surveys; bestehendes Archiv erhalten                 |
| Einladungen                   | Survey-Repository und `adapters/mail/survey_smtp.py`                                                       | Fachliche Einladungen mit gemeinsamem sicheren Mailtransport                                               |
| Verdrahtung                   | `entrypoints/fastapi/platform.py`, `entrypoints/worker/{outbox,platform}.py`                               | Modulregistrierung/Komposition nach Bootstrap; Prozessstart kompatibel halten                              |
| Frontend                      | `apps/web/src/surveys*.tsx`, `packages/surveys/`, bestehender API-Client                                   | Web-Einstieg modularisieren, Renderer/Client weiterverwenden; PWA verweist bereits auf Web-Survey-Einstieg |

Survey-eigene Tabellen aus Migrationen 0027–0034: `survey`, `survey_grant`, `survey_draft`, `survey_version`, `survey_participation`, `survey_operation`, `survey_settings`, `survey_settings_operation`, `survey_invitation`, `survey_analysis_snapshot`, `survey_export_job`, `survey_deletion`, `survey_recovery_identity`. Gemeinsame Abhängigkeiten umfassen `charity_action`, Benutzer-/Mitgliedschaftsdaten, `outbox_event` und Audit; diese werden nicht Survey-Eigentum.

Öffentliche bestehende Use Cases: Umfragen auflisten; globale Frist-/Retention-Einstellungen; erstellen; Zusammenfassung und Entwurf lesen; Entwurf speichern/validieren/veröffentlichen; Ende planen; beenden/archivieren/wiederherstellen/in Papierkorb verschieben; kopieren; endgültig löschen und Löschstatus abfragen; Zugangsmodus und Einladungen verwalten; Einladungen einlösen; öffentliche Definition lesen; Teilnahme beginnen/fortsetzen; Antworten speichern/abschließen; Analyseversionen und Snapshots; Antwortauswahl, einzelne Antworten und Freitext; Export erstellen, Status lesen und herunterladen.

Wichtige Befunde für M1:

- `SurveyService.author` verwendet einen String-Dispatcher und Dict-Eingaben. Typisierte, transportneutrale Eingaben müssen ergänzt werden, ohne parallel einen zweiten Fachpfad zu bauen.
- `AsyncpgSurveyRepository._author` prüft Aktionsrechte und Survey-Capabilities innerhalb der Transaktion. Direkte Aufrufe dürfen diese Prüfung nicht umgehen; aktuell im HTTP-Vertrag liegende Eingabegrenzen müssen ebenfalls gelten.
- Survey-Auswertungen und Export-Adapter haben zusätzliche eigene Autorisierung. Alle Aufrufwege inklusive Replay sind getrennt zu testen.
- Worker-Typen: `survey.delete.v1`, `survey.export.render.v1`, `survey.invitation.send.v1`. Fristschluss, Inaktivitätsklassifikation und Retention laufen im bestehenden Sweep; keine neue Scheduler-Semantik ohne Nachweis.
- Der bestehende Architekturtest scannt Domain/Application teilweise nicht rekursiv. Die neue Prüfung muss verschachtelte Pakete und relative Imports erfassen.

### Prüfung

- `git status --short`, `git log -3 --oneline`: sauberer Ausgangsstand festgestellt.
- `gh api repos/BjoernSchotte/leonaid/commits/main --jq .sha`: Spec-Basis bestätigt.
- Repository-Quellen, Transportoperationen und Survey-Migrationen gelesen; Tabellen-/Use-Case-Liste gegen diese Quellen geprüft.
- Nur Dokumentation in diesem Slice: keine Anwendungstests erforderlich; keine Aussage über Laufzeitabnahme. Alle funktionalen Gates bleiben offen.

## M0.2 — Rekursive Architekturprüfung

Status: abgeschlossen am 13.09.2026. Slice-Commit ist der Commit, der diesen Abschnitt anlegt.

`tests/unit/test_architecture_boundaries.py` prüft Domain/Application nun rekursiv. Zusätzlich werden absolute und relative Imports in Plattform, Modulen und Bootstrap auf Rückabhängigkeiten, fremde interne Modulimporte und Modulzyklen geprüft. Absichtlich ungültige Quelltexte in temporären Verzeichnissen beweisen die Erkennung; erlaubte öffentliche API-Imports werden ebenfalls geprüft. Keine Alt-Ausnahmen erforderlich, da die neuen Verzeichnisse bisher nicht existierten. Beim Migrieren bleibt jede neu erforderliche Ausnahme explizit zu behandeln. SQL-Eigentum bleibt zusätzlich Gegenstand des Reviews.

Prüfung:

- `.venv/bin/pytest tests/unit/test_architecture_boundaries.py -q`: 13 bestanden.
- `.venv/bin/ruff check tests/unit/test_architecture_boundaries.py`: erfolgreich; Datei mit Ruff formatiert.
- `env PYTHONPATH=src .venv/bin/pytest tests/unit -q`: 383 bestanden.
- Der erste Aufruf ohne explizites `PYTHONPATH` hatte vier fehlgeschlagene Subprozess-Tests mit `ModuleNotFoundError`. Der Wiederholungslauf mit der im Repository-Runner vorgesehenen Umgebung bestand vollständig; keine Produktänderung zur Umgehung nötig.

Noch offen: tatsächliche Modul-/Bootstrap-Migration, Registrierung, Runtime-/Browser-Nachweise und sämtliche M1–M3-Abnahmen. Die Architekturprüfung allein schließt M0 nicht ab.

## M0.3 — Startprüfungen an API und Worker angeschlossen

Status: abgeschlossen am 13.09.2026. Slice-Commit ist der Commit, der diesen Abschnitt anlegt.

`bootstrap/registry.py` validiert explizite Beiträge auf gültige/eindeutige Modul-IDs, fehlende Abhängigkeiten, Zyklen, kollidierende HTTP-Methoden/Pfade und doppelte Jobtypen. Routenparameter mit unterschiedlichen Namen zählen als dieselbe Route. Die Routenprüfung erfolgt vollständig vor dem Einhängen der Beiträge. Der echte FastAPI-Start registriert Surveys über `bootstrap/api.py`; der Worker sammelt seine bestehenden Handler über die geprüfte Registrierung. Handler-Namen, Payloads und Prozessbefehle bleiben erhalten.

Übergang bis M1: `bootstrap/api.py` importiert noch den existierenden Survey-Router unter `entrypoints/fastapi/surveys.py`. Die konkreten Worker-Handler werden noch im vorhandenen Worker-Composition-Root instanziiert. M1 verschiebt diese Beiträge in das Fachmodul bzw. Bootstrap; die derzeitige Registrierung wird dabei wiederverwendet. Frontend-Registrierung und vollständige Fachoperationen fehlen noch.

Die Architekturprüfung unterscheidet nun außerdem Bootstrap-Verdrahtung von Fach-APIs: `bootstrap/api.py` darf FastAPI importieren, eine fachliche `modules/<name>/api.py` weiterhin nicht. Dies ist die in der Spec vorgesehene Schichtentrennung und keine Alt-Ausnahme.

Prüfung:

- `env PYTHONPATH=src .venv/bin/pytest tests/unit -q --disable-warnings`: 391 bestanden. Neun Pydantic-Warnungen aus der bestehenden OpenAPI-Erzeugung; keine Testfehler.
- Ruff-Check und Formatierung der geänderten Python-Dateien: erfolgreich.
- `.venv/bin/mypy src/leonaid/bootstrap src/leonaid/entrypoints/worker/outbox.py`: erfolgreich (vier Quelldateien).
- `env PYTHONPATH=src .venv/bin/python tools/openapi/generate.py --root . --check`: OpenAPI und TypeScript-Client unverändert/aktuell.
- `.venv/bin/python tools/ci/no_test_doubles.py .`: erfolgreich. Registry-Tests verwenden reale FastAPI-Router und einen realen, nicht gestarteten PostgreSQL-Pool; sie behaupten keinen Worker-I/O-Nachweis.

M0 als Gesamtetappe sowie Runtime-, Browser- und Jobabnahmen bleiben offen. FastAPI bleibt auf ausdrücklichen Wunsch das Backend-Framework; der spätere FastMCP-Anschluss läuft über dieselben Fachoperationen und ist keine aktuelle Abhängigkeit.

## M0.4 — Erste vertikale Backend-Zuordnung

Status: abgeschlossen am 13.09.2026. Slice-Commit ist der Commit, der diesen Abschnitt anlegt.

SurveyService und Survey-Router liegen jetzt in `modules/surveys/api.py` bzw. `routes.py`. Die bisherigen Definitionen wurden entfernt, alle gefundenen Produktions- und Testtool-Imports aktualisiert. Gemeinsame Transport-/Fehlermodelle liegen in `platform/http.py`; das alte Schema-Modul importiert dieselben Klassen für seine bestehenden Verbraucher. Die konkrete Worker-Konstruktion liegt in `bootstrap/worker.py`; der bestehende CLI-Prozesspfad bleibt erhalten. Die API-Registrierung importiert nun das tatsächliche Fachmodul und nicht mehr den alten Router-Entrypoint.

Bewusst noch vorhandene Alt-Struktur: Survey-Domain, Analyse-/Export-Application-Verträge und PostgreSQL-/Mail-Adapter verbleiben bis zu ihrem jeweiligen M1-Schnitt an den inventarisierten Orten. Der neue Survey-Service verwendet denselben Repository-Port; die Verbesserung der typisierten Eingaben und Direktaufruf-Verträge bleibt offen. Keine neuen Dienste oder Pakete.

Prüfung:

- Unit-Suite mit `PYTHONPATH=src`: 391 bestanden, neun bestehende Pydantic-Warnungen.
- Ruff für alle neuen/verschobenen Python-Bereiche: erfolgreich.
- Mypy für Plattform, Module, Bootstrap und Worker-CLI: erfolgreich, elf Quelldateien.
- `tools/openapi/generate.py --root . --check`: OpenAPI und TypeScript-Client unverändert.
- `python -m leonaid.entrypoints.worker.outbox --help`: bestehender Prozesspfad und CLI-Operationen verfügbar.

Dieser Slice weist Struktur- und Vertragskompatibilität nach, nicht den Betrieb mit Datenbank oder Browser. Frontend-Registrierung, komplette M0-Abnahme und M1–M3 bleiben offen.

## M0.5 — Navigation und Frontend-Beiträge

Status: Implementierungsslice abgeschlossen am 13.09.2026; die übergreifende LIVE-Abnahme von M0/M1 bleibt offen. Slice-Commit ist der Commit, der diesen Abschnitt anlegt.

Die Backend-Registrierung liefert jetzt autorisierte Navigationsbeiträge aus dem Survey-Modul. `IdentityQueryService` erhält den Provider aus Bootstrap; Plattform/Identity importieren keine Registrierung. Die bestehende Survey-Navigation inklusive PWA-Link zur Web-Oberfläche bleibt erhalten, gesperrte Konten erhalten keine Moduleinträge. `NavigationItem` ist ein gemeinsamer Plattformvertrag.

Survey-Seiten, Analyse, Antworten, Exportdarstellung, CSS und Vorlagen wurden nach `packages/features/src/surveys/` verschoben. Ein lazy geladener Modulbeitrag besitzt Routen und Darstellung; die Web-Shell löst ihn über die gemeinsame Registrierung auf. Unbekannte Web-Pfade erhalten einen Nicht-gefunden-Zustand. Die Registrierung prüft IDs, identische Routenmuster und mehrdeutige Matches. Die getrennten Package-Exports verhindern, dass die PWA allein durch ihren Features-Import den Survey-Editor mitbündelt. Native PWA-Beiträge für die neuen Arbeitsmodule folgen in M2; für Surveys bleibt bewusst der bestehende Oberflächenwechsel erhalten.

Prüfung:

- Python-Unit-Suite: 393 bestanden; neun bestehende Pydantic-Warnungen.
- Gezielte Vitest-Prüfung für Modulregistrierung, Aktionsort und Campaign-Link: neun Tests bestanden. Ein vollständiger Component-Aufruf ohne Testserver scheiterte erwartungsgemäß am erforderlichen `LEONAID_COMPONENT_API_BASE_URL`; dieser LIVE-Test bleibt über den bestehenden Runner abzuarbeiten.
- Mypy: zwölf Quelldateien erfolgreich; Ruff erfolgreich. OpenAPI/TypeScript-Client unverändert.
- `typecheck:features`, `typecheck:web`, `typecheck:pwa`: erfolgreich. UI-Paket mit explizitem `--typeRoots ./node_modules/@types` erfolgreich; der direkte lokale Gesamtaufruf liest ansonsten inkompatible MDX-Typen aus einem übergeordneten Verzeichnis außerhalb des Repositories. Der isolierte CI-Gesamtcheck bleibt maßgeblich.
- Features übernimmt `skipLibCheck` vom bisherigen Web-Verbraucher: Die verschobene SurveyJS-Integration zieht eine inkonsistente externe nullable Render-Signatur ein. Eigener TypeScript-Code bleibt unter `strict`; keine Eingabe-, API- oder Fachtests wurden abgeschwächt. PWA-Konfiguration bleibt unverändert.
- Web- und PWA-Produktionsbuild erfolgreich; Survey-JS/CSS als separater Web-Chunk, kein Survey-Chunk im PWA-Ausgabeverzeichnis. Bestehende Chunkgrößen-/Sourcemap-Warnungen bleiben sichtbar.
- Workspace-Lockfile mit Bun 1.2.19 und `--frozen-lockfile --ignore-scripts` geprüft; einzige fachliche Lockänderung ist die bereits existierende Survey-Workspace-Abhängigkeit des Features-Pakets.
- No-test-doubles-Policy erfolgreich.

Ein isolierter Survey-Journey-Lauf wurde gestartet. Während seiner Buildphase wurden noch Frontend-Korrekturen vorgenommen; sein Ergebnis allein darf deshalb nicht als vollständiger Nachweis des finalen Slices gewertet werden. Nach Fixierung des Stands ist der aktuelle Browser-/CI-Nachweis erneut zu prüfen.

Zusätzlicher offener CI-Befund: Security-Job `103701928640` meldet im API-Image drei kritische Perl-Funde (CVE-2026-13221, CVE-2026-42496, CVE-2026-8376), installiert `5.40.1-6`, korrigiert ab `5.40.1-6+deb13u1`. Vor Gesamtabnahme Image korrigieren und Security-Gate erneut bestehen; keine Ausnahme/Unterdrückung geplant.

## M1.1 — Survey-Worker-Beiträge

Status: Implementierungsslice abgeschlossen am 13.09.2026; LIVE-Regressionsabnahme offen.

`modules/surveys/jobs.py` konstruiert die drei bisherigen Handler für Export, Einladungsversand und Löschung. Bootstrap bindet diese über dieselbe Handler-Registrierung ein. Der bestehende Fristen-/Retention-Sweep wurde unverändert aus dem Prozess-Entrypoint in das Survey-Modul verschoben; Bootstrap registriert ihn als `surveys.deadlines`. Der Prozess startet die registrierten Hintergrundaufgaben. Leere und doppelte Namen werden vor Ausführung abgewiesen. Keine neue Queue, kein neuer Scheduler-Dienst und keine veränderten Payloads oder Wiederholungsintervalle.

Prüfung: 395 Python-Unit-Tests bestanden (neun bestehende Pydantic-Warnungen), Mypy für sechs betroffene Quelldateien, Ruff inklusive Formatprüfung, No-test-doubles-Prüfung und unveränderter OpenAPI-/Client-Vertrag erfolgreich. Neue Registry-Tests verwenden den tatsächlichen Survey-Sweep als Beitrag; sie führen keine Datenbankarbeit aus und ersetzen keinen LIVE-Nachweis.

Der zuvor gestartete Survey-Journey-Prozess ist weiterhin aktiv. Sein Stand ist nicht der aktuelle Commit; M1-Abnahme und Job-/Recovery-Laufzeitnachweise bleiben ausdrücklich offen.

## M1.2 — Typisierte Lebenszyklus-Operationen

Status: Implementierungsslice abgeschlossen am 13.09.2026; vollständiger M1-Direktaufruf-/LIVE-Nachweis offen.

Survey-Eingaben und -Ergebnisse liegen nun in `modules/surveys/models.py`, ohne FastAPI-Abhängigkeit. `SurveyService` bietet benannte, typisierte Methoden für Erstellen, Lesen, Entwurf, Validierung, Veröffentlichung, Zustandswechsel, Kopieren, Fristen, Zugangsmodus, Einladungserstellung und endgültige Löschung. Liste sowie Lesen/Ändern der Grundeinstellungen sind ebenfalls typisiert. Die HTTP-Routen verwenden diese Methoden tatsächlich. Jede mutierende Methode validiert das übergebene Modell erneut; nach Konstruktion veränderte Eingaben können so die bisherigen HTTP-Grenzen nicht umgehen. Die bestehenden Repository-Transaktionen und ihre Rechteprüfungen bleiben der einzige Fachpfad.

Grundeinstellungen behalten die Unterscheidung zwischen ausgelassenem Retention-Feld und explizitem `null`; dies ist für partielle Änderung und Wiederholung relevant. Ergebnisobjekte werden auch für direkte Verbraucher validiert. Die Modelle sind über die verwendeten Imports der öffentlichen `api.py` verfügbar.

Prüfung: 397 Unit-Tests bestanden, Mypy für fünf Moduldateien, Ruff, No-test-doubles sowie OpenAPI-/TypeScript-Vertragsvergleich erfolgreich. Der neue Direktaufruf-Test verwendet den echten Repository-Adapter mit nicht gestartetem PostgreSQL-Pool: ungültiger Titel, zu große Definition und Datum ohne Zeitzone scheitern vor I/O; ein unberechtigter Aufruf der Grundeinstellungen scheitert an der bestehenden Repository-Rechteprüfung. Das belegt nicht die noch offene aktions-/surveybezogene LIVE-Berechtigungsmatrix.

Der vorherige Survey-Journey-Lauf `be5b01315e1a4c38a193f5efbdd29dc0` ist erfolgreich abgeschlossen (`PASS: journeys`, ein vollständiger Durchlauf). Er wurde vor diesem Slice gestartet und ist daher nur Regressionsevidenz für den vorherigen Umbau, kein Nachweis dieser API-Änderungen. Die verbliebenen generischen Analyse-/Antwort-/Teilnahme-Aufrufe werden im nächsten Schnitt ersetzt; die übergeordnete M1-Checkbox bleibt offen.

## M1.3 — Analyse-, Antwort- und Teilnahmeverträge

Status: Implementierungsslice abgeschlossen am 13.09.2026; LIVE-Nachweise offen.

Die verbliebenen String-Aufrufe der HTTP-Routen wurden durch benannte Methoden für Analyse, Exportauswahl, Antwortauswahl, Einladungslisten/-widerruf und Teilnahme ersetzt. `SurveyService.author` und `SurveyService.participate` entfallen. Der interne Repository-Dispatcher bleibt während der Adaptermigration bestehen und ist keine öffentliche Fachoperation. UUID-Referenzen und Paginierungsgrenzen werden über gemeinsame Eingabemodelle geprüft. Teilnahme-Cookies bleiben im HTTP-Adapter; die Fachmethoden erhalten explizite Zugangstoken und verwenden dieselbe bestehende Prüfung. Verschachtelte Analysefilter werden vor dem Repository-Aufruf neu validiert.

Prüfung: 397 Unit-Tests bestanden; der Direktaufruf-Test deckt zusätzlich veränderte verschachtelte Statusfilter, zu großen Offset, ungültiges Resume-Secret und übergroße Antworten ab. Mypy für fünf Moduldateien, Ruff, No-test-doubles und unverändertes OpenAPI erfolgreich. Der bestehende LIVE-Modultest wurde um echte Direktaufrufe ergänzt: Listenvergleich mit HTTP, Survey-/Aktionsgrenzen und verweigerte Veröffentlichung. Dieser neue Test muss noch im Lifecycle-Runner ausgeführt werden; seine bloße Existenz ist kein LIVE-Nachweis. Die drei eigentlichen Exportoperationen nutzen noch den bereits typisierten Export-Port; ihre öffentliche Modul-Fassade und die verbleibende Bootstrap-Bereinigung folgen separat.

## M1.4 — Export-Fassade und API-Komposition

Status: Implementierungsslice abgeschlossen am 13.09.2026; LIVE-Abnahme offen.

`SurveyExportService` bietet Erstellen, Status und Download über den vorhandenen Export-Port an. Die HTTP-Routen nutzen diese Fassade. Export-Eingaben werden auch nach einer nachträglichen Änderung erneut validiert; die bestehenden Datenbankprüfungen laden weiterhin aktuelle Rechte. Keine neue Exportverarbeitung und kein zusätzliches Storage. Öffentliche Modelle und Services sind nun explizit in `api.__all__` exportiert, damit auch strikt typisierte Modulverbraucher sie importieren können.

`bootstrap/api.py` konstruiert Survey-Service, Export-Fassade und Erasure-Publisher; der Prozess-Entrypoint erhält die konkreten Instanzen nach Aufbau des gemeinsamen Storage. Die bisherige Konstruktion wurde entfernt. Der Publisher bleibt am vorhandenen Startup-Punkt vor Annahme von Requests aktiv.

Prüfung: 397 Unit-Tests bestanden, Mypy für neun Quelldateien, Ruff, No-test-doubles und unverändertes OpenAPI erfolgreich. Der Direktaufruf-Test verwendet den tatsächlichen Exportadapter und S3-Client mit synthetischer Konfiguration; eine manipulierte Snapshot-ID scheitert vor I/O. Ein beim ersten Lauf entdeckter Fehler durch sofort ausgewertete `asyncpg.Pool`-Annotation wurde durch aufgeschobene Annotationen korrigiert und die Suite anschließend vollständig wiederholt.

Lifecycle-Lauf `d5218eac529147baa1347df176c69a43` läuft noch. Er wurde auf `9f72c27` gestartet; während seiner Buildphase kamen Änderungen dieses Slices hinzu. Sein Ergebnis ist deshalb kein sicherer Nachweis des finalen aktuellen Commits. Vollständige LIVE-Abnahme, Jobvertrag und M2–M3 bleiben offen.

## M1.5 — Optionaler Ausführungszeitpunkt: Implementierung und Inventar

Status: abgeschlossen am 13.09.2026. PostgreSQL-/Worker-Abnahme inzwischen erfolgreich, siehe Ergebnis unten.

`PendingOutboxEvent.available_at` ist optional und verlangt bei Angabe einen Zeitpunkt mit Zeitzone. Die bestehende Datenbankspalte `outbox_event.available_at` genügt; keine Migration oder Änderung bestehender Payloads. Alle Verbraucher des Pending-Vertrags wurden inventarisiert und angepasst:

| Producer/Persistenz                                               | Verhalten ohne Zeitpunkt                          | Verhalten mit Zeitpunkt                              |
| ----------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------- |
| ActionProgress / `AsyncpgTransactionalOutboxRepository.append`    | Datenbank-Transaktionszeit wie bisheriger Default | Zeitpunkt atomar beim Append                         |
| Einladungen und Ersatzeinladungen / `AsyncpgInvitationRepository` | bisheriges `occurred_at`                          | eigener Zeitpunkt; `created_at` bleibt `occurred_at` |
| E-Mail-Wechsel / `AsyncpgEmailChangeRepository`                   | bisheriges `occurred_at`                          | eigener Zeitpunkt; `created_at` bleibt `occurred_at` |
| Login-Mail / `AsyncpgSessionRepository`                           | Datenbank-Transaktionszeit wie bisheriger Default | eigener Zeitpunkt; `created_at` unverändert          |

Direkte SQL-Producer für Rechnung, Rechnungsversand, Survey-Einladung, Export, Löschung und Recovery verwenden keinen `PendingOutboxEvent` und bleiben bei ihrem vorhandenen Default. Ihre Replay-/Ledger-Pfade werden nicht verändert. Bestehende ActionProgress-Command-Hashes und Ereignis-IDs bleiben gleich. Die Speicherung liegt weiterhin in derselben fachlichen Transaktion.

Prüfung bisher: 398 Unit-Tests, Mypy für sechs betroffene Quellen, Ruff und No-test-doubles erfolgreich. Der erweiterte vorhandene Outbox-Runner verwendet einen echten ActionProgress-Handler mit synthetischen Daten: Rollback, Persistenz des Termins, Grenze vor/bei Fälligkeit, Claim-Übernahme, Fencing und idempotente Projektion. Der gestartete LIVE-Lauf ist noch nicht beendet; Laufzeitgrenzen und sichere Retry-Fehler sind weitere offene M1-Arbeit.

## Worker-Diagnostik und zwischenzeitliche LIVE-Ergebnisse

Diagnostik-Implementierung abgeschlossen: Der Worker speichert als Fehlerdetail nur noch den sicheren Fehlercode, keinen rohen Exception-Text. Auch der Fallback-Code erfüllt die bestehende Code-Grammatik. Completion und Retry/Dead-Letter-Logs erhalten die mit monotoner Uhr gemessene Dauer; Claim-Logs haben noch keine Dauer. Der tatsächliche Log-Adapter wurde auf Dauer und Nichtausgabe von Payload-Inhalten getestet. Unit-Suite: 400 bestanden; Mypy, Ruff und No-test-doubles erfolgreich. Der bereits laufende Queue-Test verwendet sein zuvor gebautes Image und belegt diese Diagnostikänderung noch nicht.

Lifecycle-Lauf `d5218eac529147baa1347df176c69a43` erfolgreich abgeschlossen: direkter Listenvergleich mit HTTP, Survey-/Aktionsgrenzen und verweigerte Veröffentlichung; reale Worker-Neustarts und Fristnachholung; 25 Lifecycle-/Aktionspaare; drei Browsertests einschließlich mobiler eingeschränkter Designeransicht. Die zuvor dokumentierte Einschränkung der Commit-Zuordnung bleibt bestehen. Der separate Queue-Lauf hat bislang Commit-Abbruch/Recovery und zwei konkurrierende Worker bestanden; SMTP-Ausfall, Abschluss und neuer verzögerter Claim-Test laufen noch.

CI-Ursache behoben und separat gepusht: `features` deklarierte `react-dom@19.2.8` nur als Peer, die vorhandene Survey-Host-Pin-Policy verlangt eine direkte Dependency. Pin-Check und Bun-1.2.19-Frozen-Install bestanden nach der Korrektur, ohne Versionswechsel. Neue CI-Ergebnisse sind noch abzuwarten; dies ersetzt nicht die offene Image-Security-Korrektur.

### Abschluss M1.5: reale Queue-Prüfung

`sh tools/outbox/test.sh` ist erfolgreich beendet. Eigener Compose-Teststack `leonaid-poc022-test-2137972478-13179`, alle eigenen Ressourcen anschließend entfernt. Nachgewiesen: Commit überlebt Producer-Prozessende; vorhandene Aktivitätsprojektion wird nachgeholt; zwei Worker teilen 20 zusätzliche Jobs ohne doppelte Verarbeitung; physisch gestopptes SMTP führt über drei Versuche zu Dead Letter; manueller Retry und Replay erzeugen keine zusätzliche Mail. Der neue Test ergänzt atomaren Rollback eines terminierten Events, gespeicherten Ausführungszeitpunkt, kein Claim vor Fälligkeit, Claim bei Fälligkeit, Übernahme nach Lease-Ablauf, Zurückweisung des alten Claim-Tokens und genau eine Aktivitätsprojektion trotz erneutem Handler-Aufruf.

Der Lauf enthält die unveränderten Implementierungsdateien des Delayed-Enqueue-Slices. Später ergänzte Worker-Diagnostik ist ausdrücklich nicht durch das vorher gebaute Image abgedeckt. Unit-Gesamtsuite nach beiden Änderungen: 400 bestanden. Repräsentative Exportmessung, begrenzte Joblaufzeit und die vollständige aktuelle CI-/LIVE-Abnahme bleiben offen.

### Export-Renderer-Messung als Grundlage für Laufzeitgrenzen

`tools/outbox/benchmark_exports.py` lief im bestehenden API-Image ohne Netzwerk, mit den Produktionsrenderern und synthetischem Fixture. Das validierte Fünf-Antworten-Fixture wurde 1000-fach wiederholt; aggregierte Zähler wurden entsprechend skaliert und erneut validiert. Drei Durchläufe pro Produkt:

| Produkt                  |   Median | Einzelmessungen in Sekunden |    Ausgabegröße |
| ------------------------ | -------: | --------------------------- | --------------: |
| Aggregat-PDF             |  0,034 s | 0,046 / 0,0287 / 0,034      |    34.591 Bytes |
| Aggregat-XLSX            | 0,0225 s | 0,0254 / 0,0216 / 0,0225    |    17.795 Bytes |
| 5.000 Antworten als CSV  | 0,0978 s | 0,1096 / 0,0978 / 0,0938    | 5.433.474 Bytes |
| 5.000 Antworten als XLSX | 7,1703 s | 7,0186 / 7,1703 / 7,2747    |   625.775 Bytes |

Dies misst Rendering, keine vollständige Joblaufzeit mit PostgreSQL/S3 und keinen Worst Case jeder zulässigen Umfrage. Die serielle Verarbeitung und 300-Sekunden-Standard-Lease bleiben bestehen; aus diesen Messungen folgt noch keine Notwendigkeit für Parallelität oder Lease-Verlängerung. Der erste Messversuch scheiterte korrekt an inkonsistenter Antwortanzahl; nach Skalierung und erneuter Modellvalidierung bestand der vollständige Lauf. Das Tool enthält keine zusätzlichen Produktjobs oder Abhängigkeiten.

### Begrenzte Handler-Laufzeit

Implementierung und gezielter LIVE-Slice abgeschlossen: `OutboxWorker` akzeptiert explizite Laufzeitgrenzen für registrierte Handler, lehnt unbekannte Handler sowie nicht-positive/unendliche Werte ab und behandelt einen Ablauf als wiederholbaren `job_timeout`. Bootstrap begrenzt den Survey-Export auf `min(240 Sekunden, 80 % der Lease)`. Der bestehende Typst-Subprozess behält seinen eigenen 30-Sekunden-Timeout. Andere bestehende Handler bleiben bei ihrer bisherigen Semantik; insbesondere wurde keine pauschale Mail-Cancellation ohne Berücksichtigung unklarer externer Wirkungen eingeführt.

`sh tools/outbox/test.sh . handler-timeout` bestand im eigenen Stack `leonaid-poc022-test-2137972478-16277`: echte Tabellenblockade vor dem Aktivitäts-Insert, Abbruch nach 0,2217 Sekunden bei einer Fünf-Sekunden-Lease, keine halbe Projektion, Queue wieder pending mit sicherem Fehlercode/-detail, anschließend erfolgreiche Verarbeitung mit genau einer Projektion. Eigene Testressourcen wurden entfernt. Das prüft die Worker-Mechanik mit einem echten vorhandenen Handler, noch nicht die Gesamtlaufzeit des Exportpfads inklusive Storage. Unit-Suite: 401 bestanden; Mypy, Ruff und No-test-doubles erfolgreich.

### API-/Worker-Image: kritischen Perl-Befund behoben

Das gepinnte Basisimage enthielt `perl-base 5.40.1-6`. Die offiziellen Debian-Quellen liefern `5.40.1-6+deb13u1`; diese exakte Korrekturversion wird nun beim gemeinsamen Core-Image-Build installiert. Apt-Listen werden anschließend entfernt. Keine neue Infrastruktur und keine Vulnerability-Ausnahme.

Docker-Build `leonaid-modular-core-security:local` erfolgreich; `dpkg-query` bestätigt `5.40.1-6+deb13u1`. Scan mit gepinntem Trivy 0.72.0 und denselben Image-Flags wie CI (`--scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1`) erfolgreich beendet, null behebbaren kritischen Befunden. Lokaler Lauf auf arm64; vollständiger CI-Image-Scan auf dem CI-Zielsystem bleibt Teil der Gesamtabnahme. Pin-Policy ebenfalls erfolgreich. Der zuvor dokumentierte konkrete Perl-Befund ist damit lokal behoben, nicht pauschal jedes Security-Gate abgenommen.

### Survey-Modul: vertikale Implementierung zusammengeführt

Survey-Domain, Application-Services und fachliche PostgreSQL-, Mail-, Storage-, Tabellen- und Typst-Adapter liegen jetzt unter `src/leonaid/modules/surveys/`. Die bisherigen Implementierungspfade wurden entfernt; Bootstrap, HTTP-Routen, Tests und LIVE-Werkzeuge verwenden die neuen Pfade. Gemeinsame Infrastruktur bleibt gemeinsam. Das Typst-Template liegt beim Renderer. Die Fixture-Fingerprints berücksichtigen weiterhin die verschobenen Domain- und Template-Dateien.

Die Architekturprüfung erfasst auch Modulmodelle und interne Application-Verzeichnisse; Fachlogik darf weder eigene konkrete Adapter noch Plattformadapter importieren. Prüfung am verschobenen Stand: 405 Unit-Tests und sechs Fixture-Cache-Tests bestanden. Neun bestehende Pydantic-Warnungen bleiben sichtbar.

Frisches Image `leonaid-modular-surveys:local`: FastAPI-App importiert erfolgreich und registriert `/api/v1/surveys`. Alle vier Produktionsrenderer liefen ohne Netzwerk mit Image-Quellcode; Median PDF 0,0316 s, Analyse-XLSX 0,023 s, 5.000 Antworten CSV 0,0989 s und XLSX 7,1843 s. Das belegt Importe und mitgeliefertes Template, keine vollständige Datenbank-/Storage-Recovery-Abnahme. Zwei vorherige Quellcode-Bind-Mount-Läufe meldeten unvollständig gelesene Python-Dateien; Ursache nicht bestätigt. Der erfolgreiche Image-Lauf verwendet keinen Quellcode-Bind-Mount. Übergeordnete M1-Abnahme bleibt offen.

### Worker-Aktivität getrennt von Datenbank-Readiness

Der vorhandene Worker-Endpunkt `/metrics` liefert `leonaid_worker_last_success_timestamp_seconds` mit den drei festen Aktivitäten `queue_poll`, `job_completion` und `survey_sweep`. Die Queue-Marke wird erst nach erfolgreichem `run_once` aktualisiert, auch wenn die Queue leer ist. Die Job-Marke folgt ausschließlich dem bestehenden Completion-Ereignis nach erfolgreicher Queue-Bestätigung. Der Survey-Sweep meldet Erfolg erst nach allen drei bestehenden Fristen-/Retention-Schritten. Fehler aktualisieren die jeweilige Erfolgsmarke nicht.

Die Metrik ist ausdrücklich pro Prozess: Neustart beginnt bei null, erfolgreiche PostgreSQL-Erreichbarkeit setzt keine Aktivitätsmarke. Keine Objekt- oder Kontaktdaten als Labels. Gezielt 21 Tests einschließlich frischem Python-Prozess, Retry-vs-Completion und Architekturgrenzen bestanden; Mypy, Ruff und No-test-doubles bestanden. Integration in Operations-Ansicht, persistente letzte Sweep-Aktivität und Nachweis am laufenden Worker bleiben offen; dieser Slice ist kein Ersatz für die vollständige Betriebsabnahme.

### Operations: Zeitangaben für wartende Jobs

Die bestehende Operations-Antwort ergänzt `nextPendingAttemptAt` und `oldestDuePendingAgeSeconds`; der generierte TypeScript-Client und die vorhandene Outbox-Kachel verwenden sie. Die Abfrage verwendet PostgreSQL-Zeit und ausschließlich pending-Zeilen. Ein bereits fälliger nächster Versuch bleibt als vergangener Termin sichtbar. Ohne wartende Jobs ist der nächste Zeitpunkt null; ohne fällige wartende Jobs ist das Alter null. Processing-Zeilen mit aktiver oder abgelaufener Lease sind ausdrücklich nicht Teil dieser Pending-Kennzahlen.

`tools/operations/queue_timing.py` ruft die Produktionsabfrage gegen echtes PostgreSQL auf. Geprüft in eigenem kurzlebigem PostgreSQL-16.9-Container: leere Queue, ausschließlich zukünftiger Termin, Ausschluss anderer Zustände, ältester fälliger Termin und exakt jetzt fälliger Termin. Testdaten liegen nur in einer temporären Tabelle der Testverbindung; Container und eigenes Volume anschließend entfernt. Der Nachweis ist in den bestehenden Operations-Contract-Schritt `prepare` eingebunden.

406 Unit-Tests bestanden (neun bestehende Pydantic-Warnungen), Features-Typecheck sowie betroffene Python-Typprüfung, Ruff und No-test-doubles bestanden. Der vollständige Operations-Runner und die Browserdarstellung wurden für diesen Slice noch nicht erneut abgenommen. Sweep-Aktivität in der Operations-Ansicht bleibt ein eigener offener Punkt.

### M2: Task-Datenbasis

Migration `0037_work_tasks` baut auf `0036_delivery_windows` auf und legt `task_list`, `task_list_member`, `task_epic` und `task` an. Listen haben einen Eigentümer und optionalen Aktionskontext; explizite Mitglieder erhalten viewer/editor. Fachliche Zugriffsregeln werden im nächsten Slice implementiert: Die Tabellen allein gewähren keinen API-Zugriff. Tasks haben genau einen Listenbezug, optional ein Epic derselben Liste, offen/erledigt, optionale persönliche Zuständigkeit, getrennte Fälligkeit/Zurückstellung und positive Revisionen. Es gibt keine verschachtelten Epics oder konfigurierbaren Zustände.

Fremdschlüssel verhindern verwaiste Bezüge und implizites Löschen von Tasks durch Löschen ihrer Liste oder ihres Epics. Nach explizitem Entfernen des Epic-Bezugs bleibt der Task bestehen. Konto- und Aktionslöschung sind bei vorhandenen Bezügen ebenfalls nicht kaskadierend; eine spätere Löschoperation muss diese Datenverantwortung ausdrücklich behandeln.

`tools/tasks/schema_contract.py` prüft reale PostgreSQL-Constraints mit vollständig zurückgerollten synthetischen Daten und ist im vorhandenen Schema-Runner eingebunden. Isolierter PostgreSQL-16.9-Lauf erfolgreich: komplette Migration ab leerer Datenbank, unabhängige Zeitpunkte, Same-List-Epic, ungültige Status/Titel/Revisionen, ungültiger Assignee, referenzielle Löschsperren; Downgrade bis `0035_merge_campaign_surveys`, Wiederaufbau einschließlich Lieferfenstern und erneuter Constraint-Nachweis. Eigener Container samt Volume entfernt. Anfänglich falsch am Merge angehängte Migration wurde vor dem Datenbanklauf auf den tatsächlichen Head korrigiert. Migration-Policy, einzelner Head, Architekturtests, Mypy, Ruff und No-test-doubles bestanden.

Der Operations-Gesamtlauf wurde zuvor mit Stand `07d1008` gestartet und läuft noch im Image-Build. Er ist kein Nachweis dieses neuen Task-Schemas. M2 als Produktfunktion bleibt offen.

### M2: erste direkte Task-Fachoperationen

`modules/tasks/api.py` bietet `TaskService` mit typisierten Erstellungs-, Lese- und Änderungsoperationen. Die PostgreSQL-Implementierung verwendet den vorhandenen Command-Receipt-Adapter; kein zweiter Idempotenzspeicher. Schlüssel sind nach Akteur, Operation und Kontext begrenzt. Eingaben werden am Service erneut validiert, Titel getrimmt und Zeitpunkte vor Hashbildung nach UTC normalisiert. Task-Änderungen ersetzen die ausdrücklich übergebenen Felder und verlangen die erwartete Revision.

Aktueller Kontostatus wird innerhalb jeder Transaktion aus der Datenbank geprüft. Standalone-Listen sind für Eigentümer und explizite viewer/editor sichtbar; nur Eigentümer/editor schreiben. Aktionslisten verlangen aktuelle Aktionsrechte: aktive Mitgliedschaft zum Lesen, Charity-Admin/System-Admin zur Erstellung; Schreibzugriff zusätzlich für weiterhin aktionsberechtigte Eigentümer/editor. Explizite Listenzuweisung überstimmt keinen Aktionsrechteentzug. Referenzierte Epics müssen zur Liste gehören; zuständige Personen müssen aktiv sein und die Liste lesen dürfen. Die vollständige Aktionsmatrix und die Oberfläche zum Verwalten dieser Rechte fehlen noch.

Alle Mutationen, der inhaltsfreie Audit-Eintrag und der Receipt-Abschluss liegen in einer Transaktion. Vor Replay wird aktueller Objektzugriff erneut geprüft. Replays erzeugen keine zusätzlichen Tasks oder Audit-Einträge; Revisionkonflikte rollen die Receipt-Reservierung zurück.

`tools/tasks/service_contract.py` bestand gegen eine vollständig migrierte isolierte PostgreSQL-Datenbank: konkurrierendes Listen-Replay, abweichender Input mit gleichem Schlüssel, private Liste, Task-Replay einschließlich gleicher Zeit mit anderer Zeitzonendarstellung, Revisionkonflikt, nachträglich ungültig gemachte Eingabe, Editorzugriff und anschließender Rechteentzug vor Replay sowie Kontosperre bei altem Principal. Exakte Task-/Audit-/Receipt-Zahlen geprüft; synthetische Zeilen und eigener Container samt Volume entfernt. Der Test läuft künftig im bestehenden Schema-Runner.

Vorläufe fanden einen korrigierten Runtime-Importfehler der asyncpg-Typannotation sowie einen Datenbank-Verbindungsabbruch beim Start. Der erfolgreiche Lauf wartet auf PostgreSQL-TCP-Readiness. 406 Unit-Tests, Mypy, Ruff, Architekturgrenzen und No-test-doubles bestanden. HTTP-/Shell-Anbindung, Listenabfragen, Epic-/Mitgliederverwaltung und die weiteren M2-Module bleiben offen. Der Operations-Gesamtlauf läuft weiterhin separat.

### M2: autorisierte Task-Listen, Suche und persönliche Abfrage

`TaskService.list_lists` und `list_tasks` liefern typisierte, begrenzte Seiten. Einzelzugriff, Listenabfrage, Titelsuche und „Für mich“ verwenden denselben SQL-Leseausdruck. SQL filtert Rechte vor Pagination; keine fremden Trefferzahlen oder Vorschauen. Suche ist eine wörtliche, nicht case-sensitive Teilzeichenfolge im Titel, kein vom Nutzer steuerbares LIKE-Muster. Limits: 1–100 Ergebnisse, Offset maximal 5.000, Suchtext maximal 200 Zeichen. Die feste Sortierung nach Erstellungszeit und ID macht aufeinanderfolgende Seiten bei unverändertem Bestand eindeutig.

„Für mich“ filtert denselben Taskbestand nach persönlicher Zuständigkeit; Status und Liste sind optional. Standardmäßig sind Tasks mit zukünftigem `deferred_until` verborgen. `include_deferred` zeigt sie ausdrücklich an. Sichtbarkeit verwendet `now()` der Datenbank; Fälligkeit wird weder verschoben noch als Scheduler-Job behandelt. Der UI-Einstieg kann für offene persönliche Tasks zusätzlich `status="open"` setzen.

Der erweiterte direkte PostgreSQL-Contract bestand nach vollständiger Migration in eigenem kurzlebigem Container: private Listen/Suche ohne Treffer, wörtliches Prozentzeichen, zurückgestellter Task verborgen und nach erreichtem Zeitpunkt wieder sichtbar bei unveränderter Fälligkeit, persönliche/statusbezogene Abfragen, zwei getrennte Ergebnisse über Pagination sowie sofortiger Ausschluss nach Rechteentzug. Die bisherigen Mutation-/Replay-/Revisions-/Kontosperren-Nachweise bestanden ebenfalls. Eigene synthetische Daten, Container und Volume entfernt. Mypy, Ruff und No-test-doubles bestanden; die HTTP-/Browser-Anbindung und die vollständige Aktionsmatrix sind weiterhin offen.

### M2: Task-HTTP-Anbindung und generierter Client

Bootstrap registriert den Tasks-Router und konstruiert `TaskService` beim bestehenden FastAPI-Start. Sieben Endpunkte: Listen erstellen/auflisten/lesen sowie Tasks erstellen/auflisten/lesen/ändern. HTTP authentifiziert über den bestehenden Identity-Service; die Fachoperationen prüfen weiterhin aktuelle Datenbankrechte. Bestehende CSRF-, Maintenance-, Fehler- und Request-Logging-Middleware bleibt aktiv. Erfolgreiche Antworten sind `no-store`.

Gemeinsame Task-Modelle verwenden die vorhandene camelCase-Alias-Konvention. UUID- und ISO-Zeitstrings werden gezielt eingelesen; numerische Zeitwerte, stringförmige Revisionen und sonstige unerlaubte Eingaben bleiben abgewiesen. Der bestehende Receipt-Adapter bleibt unverändert; das Tasks-Modul übersetzt seinen Idempotenzkonflikt in den bestehenden Conflict-Typ für HTTP 409. OpenAPI und TypeScript-Client neu generiert; alle bisherigen Pfade und Schemas sind im strukturellen Vergleich unverändert.

`tools/tasks/http_contract.py` bestand mit produktivem `create_app`, vollständigem Lifespan, Middleware und echter migrierter PostgreSQL-Datenbank über ASGI-HTTP. Keine Ersetzung von Services, Authentifizierung oder Datenbankantworten. Nachgewiesen: 401 ohne Sitzung/nach Kontosperre, 403 für Browser-Write ohne Origin, camelCase-UUID-/Zeitdaten, Replay, 409 bei Idempotenz-/Revisionskonflikt, persönliche Abfrage, 422 für zu großes Limit, numerischen Zeitwert und String-Revision. Der direkte Service-Contract bestand im selben Lauf ebenfalls. Testdaten/Container/Volume entfernt. Dies ist noch kein Nachweis über Proxy oder Task-Browseroberfläche; CRM/S3 werden im Test nicht aufgerufen.

Der Contract ist im Schema-Runner eingebunden; `tools/tasks` gehört nun auch zu den CLI-/CI-Lint- und Typprüfungen. Vorläufe korrigierten fehlende Testkonfiguration, die synthetischen Sitzungszeitpunkte und Browser-Header gemäß den bestehenden Regeln. 406 Unit-Tests, Python-/Client-/Features-Typprüfung, Ruff, Frontend-Client-Grenze und No-test-doubles bestanden.

### Operations-Gesamtlauf abgeschlossen

`tools/operations/test.sh` im eigenen Stack `leonaid-poc114-test-2137972478-20483` erfolgreich beendet und alle eigenen Ressourcen entfernt. Reale Ausfälle von Twenty, Storage, Mail und Worker, korrelierte Logs, technische Metriken, Dead Letter und manueller Mail-Retry geprüft. Ein Chromium-Browsertest bestand einschließlich mobiler Ansicht und Accessibility-Prüfungen des vorhandenen Runners. Die mobile Ergebnisgrafik wurde angesehen; die neuen Queue-Zeitangaben sind in der Outbox-Kachel sichtbar. Auch der ergänzte PostgreSQL-Zeitabfrage-Contract bestand.

Der Lauf wurde bei `07d1008` gestartet; parallel entstandene Task-Änderungen sind dadurch nicht pauschal abgenommen. Worker-Aktivitätszeitstempel in der Operations-Ansicht, vollständige Export-Jobmessung und die übrigen M1/M2/M3-Gates bleiben offen.

### M2: Epic-Fachoperationen

Tasks bietet jetzt `create_epic`, `list_epics` und `update_epic` über dieselbe öffentliche API, drei FastAPI-Endpunkte und den generierten Client. Listenrechte werden vor Lesen, Schreiben und Replay geprüft. Erstellung und Umbenennung speichern fachliche Änderung, inhaltsfreien Audit-Eintrag mit `entity_type=task_epic` und bestehenden Command Receipt atomar. Umbenennen verlangt die erwartete Revision. Titeländerungen behalten die Epic-ID und bestehende Task-Referenzen; keine Eltern-/Kind-Epics oder zusätzlichen Zustände. Die vorhandenen begrenzten Such-/Seitenparameter sind in einem gemeinsamen Eingabemodell zusammengeführt.

Der erweiterte HTTP-Contract bestand mit vollständigem produktivem App-Lifespan und echtem PostgreSQL: Erstellung und Replay, Ablehnung von `parentId`, Umbenennen und Replay, 409 bei veralteter Revision, Suche nach geändertem Titel sowie unveränderte `epicId` am zugehörigen Task. Die bisherigen direkten Task-, Sitzungs-, CSRF-, Validierungs- und Revisionsprüfungen bestanden ebenfalls. Eigene Testdaten und Container samt Volume entfernt.

406 Unit-Tests, Python-/Client-Typprüfung, Ruff, No-test-doubles und Frontend-Client-Grenze bestanden. Bestehende OpenAPI-Pfade und Schemas sind strukturell unverändert. Mitgliedschaftsverwaltung, Aktionsmatrix und Task-/Epic-Oberfläche bleiben offen; M2 ist nicht insgesamt abgenommen.

### M2: explizite Listenrechte verwalten

`set_list_member` und `list_members` ergänzen Fach-API, FastAPI und Client. Nur der weiterhin zugriffsberechtigte Eigentümer bzw. die aktuelle Aktionsverwaltung verwaltet die expliziten Rechte. Leser/Bearbeiter können sich nicht selbst hochstufen. Setzen auf viewer/editor erfordert ein aktives Zielkonto und bei Aktionslisten dessen aktuellen Aktionszugriff. Entfernen ist auch bei inzwischen inaktivem Zielkonto möglich. Der Eigentümer kann über diesen Pfad nicht entfernt oder herabgestuft werden. Aktionsrollen bestehen daneben weiter; Entfernen einer expliziten Listenzuweisung widerruft keine Aktionsmitgliedschaft.

Rechteänderungen sperren die Listenzeile vor dem Lesen, verlangen die erwartete Listenrevision und erhöhen diese atomar mit Audit und Receipt. Der Audit-Eintrag enthält nur Zielkonto-ID und Zugriffswert, keine Namen oder Kontaktangaben. Der bestehende `_finish`-Pfad wird wiederverwendet. Die begrenzte Mitgliederabfrage liefert der Verwaltung Namen, explizite Rolle und Aktivstatus; sie ist kein globales Personenverzeichnis.

Der direkte PostgreSQL-Contract verwendet nun echte Fachoperationen statt SQL zur Rechtevergabe/-entfernung. Bestanden: Eigentümerschutz, paralleles Replay ohne doppelte Änderung, Lesen als viewer aber kein Schreiben, verweigerte Selbstbeförderung, veraltete Revision, Promotion zum editor, Schreiben, Rechteentzug und verweigertes Task-Replay danach. Exakt sieben Audit-/Receipt-Einträge für sieben erfolgreiche Fachänderungen. HTTP prüft zusätzlich die Mitgliederantwort und 409 beim versuchten Entfernen des Eigentümers; die bisherigen Task-/Epic-Contracts bestanden. Eigene Datenbank samt Volume entfernt.

406 Unit-Tests, Python-/Client-Typprüfung, Ruff und No-test-doubles bestanden. Bestehende OpenAPI-Pfade/-Schemas unverändert. Die vollständige Aktionsmatrix und die Bedienoberfläche bleiben offen.

### M2: Task-Rechtematrix im Aktionskontext

`tools/tasks/action_contract.py` prüft die bestehende Task-Implementierung direkt gegen eine vollständig migrierte PostgreSQL-Datenbank. Zehn aktive Testkonten, zwei getrennte Aktionen, alle vier Aktionsrollen, aktueller globaler System-Admin, abgelaufene/zukünftige Mitgliedschaft und Außenseiter. Die übergebenen Principals enthalten bewusst keine aktuellen Rollen; einem Außenseiter wird sogar nur im Speicher System-Admin behauptet. Die Datenbankrechte bleiben ausschlaggebend.

Bestanden: Lesen und gefilterte Suche für berechtigte Rollen, keine Treffer/kein Einzelzugriff für unberechtigte Rollen, Schreiben nur mit Verwaltung oder explizitem Editorrecht, Verwaltung durch Charity-Admin/System-Admin, keine Freigabe an kontofremde Aktionsaußenseiter, kein Epic oder Assignee aus der anderen Aktion. Nach Entzug von Aktionsmitgliedschaft verlieren auch Listenbesitzer und explizite Editoren den Zugriff; nach Entzug der globalen Rolle ebenso der bisherige System-Admin. Früheres erfolgreiches Task-Kommando lässt sich dann nicht mehr replayen. Die verbleibende Aktionsverwaltung kann die Liste weiterhin verwalten.

Der reale Lauf bestand; alle synthetischen Datensätze, eigenen Container und dessen Volume entfernt. Der Contract ist in den vorhandenen Schema-Runner aufgenommen. Ruff, Mypy, Shellsyntax und No-test-doubles bestanden. Dies ergänzt die vorherige Standalone-/Sitzungsprüfung, ersetzt jedoch keine Task-Browserabnahme oder die noch fehlenden anderen M2-Module.

## M2 — Task-Navigation und erste gemeinsame Oberfläche

Das Task-Modul liefert Navigation für aktive Konten nach Web und PWA. Beide Shells laden dieselbe Aufgabenansicht mit Listen, Seitennavigation, Titelsuche, Status, „Für mich“, Zurückstellungsfilter und Erstellung einer zunächst privaten Liste. Alle Daten stammen aus den vorhandenen autorisierten Fachoperationen. Die PWA verwendet eine explizite Zusammenstellung ihrer Modulbeiträge; dadurch wird der ausschließlich im Web benötigte Survey-Editor nicht in ihren Importgraph aufgenommen. Ein erster Versuch mit der vollständigen Web-Zusammenstellung zeigte einen SurveyJS-Deklarationsfehler in der strikten PWA-Typprüfung; die getrennte Zusammenstellung beseitigt den unnötigen Import ohne Compiler-Ausnahmen.

Nachweise: Features-, Web- und PWA-Typprüfung, beide Produktionsbuilds, 40 Python-Registrierungs-/Identitätstests und sieben UI-Registrierungstests. Der lokale Node-Lauf benötigt `NODE_OPTIONS=--no-experimental-webstorage`, damit jsdom sein eigenes localStorage bereitstellt; ohne diese Option scheitert bereits das bestehende Test-Setup. Bestehende Pydantic-Warnungen und Vite-Hinweise zu Sourcemaps/großen Chunks bleiben. Die neue Aufgabenansicht wird separat als kleiner Chunk geladen. Dies ist keine Browser- oder M2-Gesamtabnahme: Aufgabenbearbeitung, Epic-/Mitgliederverwaltung, Aktionskontext und reale Desktop-/Mobile-Prüfung bleiben offen.

## M2 — Gemeinsame Aufgabenbearbeitung und echter Browserlauf

Web und PWA verwenden denselben Editor für Titel, Beschreibung, Selbstzuweisung bzw. Entfernen der Zuständigkeit, Statuswechsel, Fälligkeit und Zurückstellung. Bestehende fremde Zuständigkeit und Epic-Referenz bleiben beim Speichern erhalten. Ein unveränderter Datumseingang behält den exakten Serverwert, einschließlich Sekunden und Zeitzoneninstant. Wiederholung ohne Eingabeänderung behält den Idempotenzschlüssel; Änderungen verwenden einen neuen. Updates senden die gelesene Revision. Fehler erhalten den Entwurf und erklären Rechte-/Revisionskonflikte. Weitere Personenauswahl und Epic-Bearbeitung bleiben offen.

Die visuelle Prüfung entdeckte eine bisher zusätzliche Navigations-Allowlist in AppShell: Tasks wurde trotz Registrierung als „In Aufbau“ dargestellt. Die Shell erhält nun die registrierten Modul-IDs von Web/PWA und schaltet damit die bereits vom Backend autorisierten Navigationseinträge frei. Es entsteht keine zweite Task-spezifische Registrierung in der Shell.

LIVE: isoliertes PostgreSQL 16 mit allen Migrationen, echte FastAPI-Lifespan/Middleware und echte Sitzung, gebaute Web-/PWA-Assets über lokalen HTTPS-Server. Chrome: private Liste und Aufgabe im Web erstellen, selbst zuweisen, Fälligkeit setzen; bei 390 px in PWA „Für mich“ dieselbe Aufgabe erledigen; im Web denselben erledigten Task lesen. Erfolgreicher Wiederholungslauf nach Navigationskorrektur. Mobile Axe: keine critical/serious violations; kein horizontaler Overflow. Screenshots `/tmp/leonaid-tasks-desktop.png` und `/tmp/leonaid-tasks-mobile.png` visuell geprüft. Der Browser nutzt echte HTTP-/Datenbankoperationen, keine gemockten Antworten. Externe Dienste und produktiver Proxy-/PWA-Service-Worker-Betrieb sind damit nicht abgenommen. Browser-Harness/temporärer HTTPS-Server lagen unter `/tmp/leonaid-tasks-*`; synthetische Identitäten und Daten ausschließlich in isolierter Testdatenbank.

Features-/Web-/PWA-Typprüfung und beide Produktionsbuilds bestanden; Impeccable-Detektor meldet keine Treffer. Dieser Schnitt belegt noch keine vollständige M2-Abnahme: konkurrierende Browserbearbeitung, Rechtewechsel im Browser, Fremdzuweisung, Epics, Mitglieder und Wissens-/Materialfunktionen bleiben offen.

## M2 — Epic-Auswahl und Verwaltung im gemeinsamen Editor

Der Task-Editor bietet die autorisierte Epic-Suche mit begrenzter Pagination, optionaler Zuordnung sowie Anlegen und revisioniertem Umbenennen. Eine bestehende Auswahl bleibt erhalten, wenn sie auf der aktuellen Suchseite fehlt; „Kein Epic“ entfernt die Zuordnung ausdrücklich. Anlegen/Umbenennen speichern sofort und werden im Formular entsprechend erklärt. Während eines Epic-Schreibvorgangs ist der Aufgabenentwurf gegen gleichzeitiges Absenden gesperrt. Fehler erhalten den eingegebenen Titel; ein erneutes Laden erlaubt bei Revisionskonflikten die bewusste Prüfung des aktuellen Stands. Keine zusätzliche API oder verschachtelte Epic-Struktur.

LIVE mit frischem PostgreSQL, sämtlichen Migrationen und echter HTTPS-FastAPI: im Web Epic anlegen, umbenennen und einem neuen Task zuordnen; in PWA trotz erfolgloser Epic-Suche Zuordnung beim Statuswechsel erhalten; im Web dieselbe Epic-ID mit neuem Titel lesen, Zuordnung entfernen und erneut lesen. Zwei erfolgreiche Browserläufe. Mobile Liste und geöffneter Editor ohne critical/serious Axe-Befunde; Editor-Screenshot `/tmp/leonaid-epics-editor.png` visuell geprüft. Temporärer Nachweis `/tmp/leonaid-epics-browser.cjs` verwendet echte HTTP-Aufrufe ohne Antwort-Doubles.

Features-/Web-/PWA-Typprüfung und beide Produktionsbuilds bestanden. Impeccable-Detektor ohne Treffer. Browsernachweis umfasst noch keine konkurrierende Epic-Umbenennung bzw. Rechteänderung und keinen produktiven Proxy-/Service-Worker-Betrieb. Die übergeordneten M2-Abnahmen bleiben offen.

## M2 — Berechtigte Personenauswahl und Fremdzuweisung

`list_assignees` ergänzt die öffentliche Task-API, einen GET-Endpunkt und den generierten Client. Die Abfrage verlangt ein aktives Konto mit Schreibrecht auf die konkrete Liste und wendet dieselbe vorhandene Listen-Leseregel auf mögliche Zuständige an. Ergebnis enthält ausschließlich Benutzer-ID und Anzeigename aktiver berechtigter Konten; keine E-Mail-Adressen oder allgemeine Kontosuche. Namenssuche ist literal und unabhängig von Großschreibung, Ergebnisse sind begrenzt und paginiert. Die Schreiboperation prüft die Zuständigkeit beim Speichern weiterhin erneut.

Der gemeinsame Editor ersetzt die bisherige Selbst-/Bestandsauswahl durch diese Personensuche. Eine bestehende Auswahl außerhalb der aktuellen Suchseite bleibt ausdrücklich erhalten; Entfernen ist eine eigene Auswahl. Fehler legen keine weiteren Personen offen.

LIVE PostgreSQL: Standalone-Eigentümer und expliziter Editor, Aktionsrollen, fremde/abgelaufene/zukünftige Mitgliedschaft, entzogene Systemrolle und Aktionsrechte, suspendiertes Zielkonto, Namenssuche, literal `%` und Pagination nachgewiesen. Beide erweiterten Task-Verträge bestanden. LIVE HTTPS/Chrome mit zwei tatsächlichen Sitzungen: Eigentümer legt Liste an, gibt der synthetischen Kollegin Editorrechte, weist ihr eine Aufgabe über den Editor zu; Kollegin erledigt sie in PWA „Für mich“; Eigentümer sieht denselben erledigten Task. Mobile Axe ohne critical/serious und kein horizontaler Overflow. Temporärer Lauf `/tmp/leonaid-assignees-browser.cjs`; keine HTTP-Doubles.

406 Unit-Tests bestanden (neun bestehende Pydantic-Warnungen), Ruff/Mypy, Features/Web/PWA/API-Client-Typprüfung und beide Builds erfolgreich. Vorhandene OpenAPI-Pfade und Schemas strukturell unverändert; nur neuer Vertrag ergänzt. Impeccable-Detektor ohne Treffer. Mitgliederverwaltung im Produkt, vollständige Browser-Rechte-/Konfliktmatrix und weitere M2-Module bleiben offen.

## M2 — Listenmitglieder verwalten

Die gemeinsame Web-/PWA-Oberfläche zeigt zusätzliche Listenrechte mit begrenzter Namenssuche und Pagination. Listen-/Aktionsverwaltung kann bestehende aktive Konten über ihre bekannte E-Mail hinzufügen, zwischen Lesen und Bearbeiten wechseln und zusätzliche Rechte entfernen. Aktionsrollen bleiben ausdrücklich separat wirksam. Fehler und Revisionskonflikte erhalten Eingaben; wiederholte unveränderte Versuche behalten ihren Schlüssel.

`set_list_member_by_email` ergänzt Fach-API, HTTP und Client. Es verwendet denselben internen Transaktionspfad wie die bestehende ID-basierte Operation: aktuelle Berechtigung und Listenrevision, Receipt, Auflösung der E-Mail, aktives Zielkonto/Aktionszugriff, Eigentümerschutz, Änderung und inhaltsfreies Audit. Auflösung erfolgt nach der Verwaltungsprüfung; die E-Mail wird nicht im Audit oder Ergebnis gespeichert. Keine Kontoanlage und kein Mailversand.

LIVE PostgreSQL: E-Mail mit unterschiedlicher Großschreibung, unbekanntes Konto, Eigentümerschutz, paralleles Replay, bestehende Rechte-/Revisions- und Audit-/Receipt-Zählungen bestanden. Aktionsmatrix ebenfalls unverändert bestanden. Echte HTTPS-Browserprüfung: Eigentümer fügt Kollegin als Leserin hinzu, erlaubt Bearbeitung; Kollegin erledigt eine zugewiesene Aufgabe in PWA; Eigentümer reduziert auf Lesen und entfernt anschließend den Listenzugriff. Kollegin sieht den Task danach nicht mehr und der direkte Listenabruf liefert 404.

Desktop-Axe entdeckte einen bestehenden unzulässigen aria-label auf dem Rollencontainer der Shell. Rollen und Arbeitskontext besitzen nun die passende group-Semantik. Wiederholter Browserlauf mit Desktop-/Mobile-Axe ohne critical/serious erfolgreich; Screenshot `/tmp/leonaid-members-desktop.png` visuell geprüft. Temporärer Nachweis `/tmp/leonaid-members-browser.cjs` gegen reale API/Datenbank.

406 Unit-Tests (neun bestehende Pydantic-Warnungen), Ruff/Mypy, Features/Web/PWA/API-Client-Typprüfung, beide Builds und strukturelle Kompatibilität sämtlicher bisheriger OpenAPI-Pfade/-Schemas bestanden. Browsernachweis umfasst noch nicht konkurrierende Mitgliederänderungen, aktionsgebundene Listenerstellung oder produktiven Proxy-/Service-Worker-Betrieb. Übergeordnete M2-Abnahme bleibt offen.

## M2 — Aktionskontext für Task-Listen

Die gemeinsame Oberfläche bietet bei der Listenerstellung neben „Eigenständig“ die aktuell verwalteten Aktionen aus der authentifizierten Identität an. Zugehörige Aktionen lassen sich außerdem als Listenfilter auswählen. Die ausgewählte Liste zeigt ihren Kontext und erklärt die unterschiedlichen Zugriffsvoraussetzungen. Der vorhandene serverseitige CreateList-/ListQuery-Vertrag bleibt unverändert und prüft aktuelle Rechte beim Speichern/Lesen. Ein veralteter Identitätsstand ist keine Schreibberechtigung.

LIVE: frisches PostgreSQL mit vollständigen Migrationen, echte HTTPS-FastAPI, synthetische Aktion mit Charity-Admin und Acquirer. Browser erstellt eine Liste im Aktionskontext, bestätigt die persistierte actionId und den Listenfilter, weist dem berechtigten Aktionsmitglied einen Task zu; dieses erledigt in PWA „Für mich“, der Admin sieht den gemeinsamen Status im Web. Mobile Axe ohne critical/serious und kein horizontaler Overflow. Desktop-Screenshot `/tmp/leonaid-tasks-desktop.png` geprüft; temporärer Nachweis `/tmp/leonaid-context-browser.cjs`. Der erste Lauf begann vor abgeschlossener Datenbankinitialisierung und scheiterte beim Verbindungsaufbau; derselbe Container wurde nach bestätigter Bereitschaft erfolgreich verwendet.

Features-/Web-/PWA-Typprüfung und beide Produktionsbuilds bestanden; Impeccable-Detektor ohne Treffer. Bekannte Grenze: Die Auswahl stammt derzeit aus eigenen aktuellen Aktionsmitgliedschaften. System-Admins ohne solche Mitgliedschaft benötigen noch eine berechtigte globale Aktionsauswahl; dieser Fall und die übergeordnete M2-Abnahme bleiben offen.

## M2 — Globale und autorisierte Aktionsauswahl

`list_action_contexts` liefert begrenzt durchsuchbare Aktionen und die aktuelle Berechtigung zum Erstellen von Listen. Aktive normale Konten sehen ausschließlich Aktionen ihrer aktuellen Mitgliedschaften; aktive System-Admins können Aktionen ohne eigene Mitgliedschaft wählen. Die Abfrage liest aktuelle Rollen aus PostgreSQL und vertraut keinen mitgebrachten Rollenbehauptungen. Erstellung prüft die Rechte weiterhin erneut.

Die gemeinsame Oberfläche verwendet diesen Vertrag statt der eigenen Mitgliedschaftsliste für Kontextwahl und Listenfilter. Die Suche besitzt Pagination; Auswahl außerhalb der aktuellen Ergebnisse bleibt erhalten. Damit ist die im vorherigen Abschnitt beschriebene System-Admin-Lücke geschlossen.

LIVE PostgreSQL: alle vier Aktionsrollen, globale Berechtigung ohne Mitgliedschaft, fremde/abgelaufene/zukünftige Mitgliedschaften, gefälschte Principal-Rolle, Rollen-/Mitgliedschaftsentzug und begrenzte Pagination bestanden. LIVE HTTPS/Chrome: System-Admin ohne Aktionsmitgliedschaft sucht Aktion, erstellt und filtert zugeordnete Liste, weist Aktionsmitglied eine Aufgabe zu; PWA-Mitglied erledigt und Admin sieht denselben Status. Wiederholung mit geöffneter Desktop-Aktionssuche und Desktop-/Mobile-Axe ohne critical/serious erfolgreich; Screenshot `/tmp/leonaid-action-search.png` geprüft. Temporärer Nachweis `/tmp/leonaid-global-context-browser.cjs`.

406 Unit-Tests (neun bestehende Pydantic-Warnungen), Ruff/Mypy, Features-/Web-/PWA-Typprüfungen und beide Produktionsbuilds bestanden. Bestehende OpenAPI-Pfade/-Schemas strukturell unverändert. Wissens-/Materialkontexte und übergeordnete M2-Abnahmen bleiben offen.

## M2 — Datenbasis der Wissensseiten und aktivierter Schema-Smoke

Migration `0038_knowledge_pages` ergänzt wissenseigene Seiten mit optionalem Aktionskontext/Eigentümer, explizite viewer/editor-Zugriffe und Revisionssnapshots mit Titel, JSON-Dokument und Autor. Titel/Inhalt liegen ausschließlich in der jeweiligen Revision; der Seitenkopf zeigt auf die aktuelle Revision. Ein bis Transaktionsende aufschiebbarer Fremdschlüssel erlaubt atomare Erstellung und verhindert fehlende aktuelle Revisionen. Dokumente besitzen einen `doc`-Wurzeltyp und maximal 1 MiB JSONB-Textgröße; vollständige Tiptap-Validierung folgt in der Fach-API. Revisionsbezogene Task-Verweise nutzen echte Fremdschlüssel. Seiten-/Referenzentfernung löscht keine Tasks.

`tools/knowledge/schema_contract.py` prüft diese Regeln mit echten PostgreSQL-Savepoints und rollt sämtliche synthetischen Daten zurück. Eingebunden in den bestehenden Schema-Lauf sowie lokale/CI-Lint- und Typprüfungen. LIVE: leer bis Head migriert, Wissen geprüft, auf `0037_work_tasks` zurückgenommen, erneut bis Head migriert und Wissen einschließlich Größenlimit nochmals geprüft.

Bei der Integration wurde entdeckt, dass `tools/schema/smoke.py` bei direktem Aufruf gar nicht startete. Nach Aktivierung waren weitere alte Annahmen sichtbar: fest kodierter Head 0020, fehlende Template-Version 2, Vergleich von asyncpg-Records mit Dictionaries, nicht dekodierte JSONB-Snapshots und Kollisionen der Smoke-IDs mit der Vorgänger-Fixture. Diese Prüfprobleme sind korrigiert. Der Smoke-Lauf liest den tatsächlichen Alembic-Head, verlangt auch Task-/Wissenstabellen und rollt eigene Daten zurück; erwartete Constraint-Fehler verwenden Savepoints.

LIVE bestanden: tatsächlich gestarteter Schema-Smoke auf leer migriertem PostgreSQL sowie auf Migration 0011 mit `tests/fixtures/schema/v0.sql` und anschließendem Upgrade bis Head. Vorherige leere Skriptaufrufe gelten ausdrücklich nicht als Nachweis. Ruff/Mypy, Migrationspolicy und no-test-doubles bestanden; 406 Unit-Tests im Verlauf dieser Änderung bestanden (neun bekannte Pydantic-Warnungen). Keine neue Laufzeitkomponente. Wissens-Fachoperationen, Autorisierung, Editor, Materialintegration und Gesamt-M2 bleiben offen.

## M2 — Typisierter Wissens- und Dokumentvertrag

`modules/knowledge/api.py` definiert Erstellen/Ändern/Lesen/Listen sowie deren typisierte Eingaben/Ergebnisse. Mutierende Service-Einstiege validieren Modelle erneut; die konkrete Repository-Implementierung und Runtime-Registrierung folgen noch. Die Erstellung besitzt ein leeres Absatzdokument als sicheren Standard.

`document.py` prüft den für den ersten Editor vorgesehenen Tiptap-Umfang: Absätze, Überschriften, Listen, Zitate, Codeblöcke, Text, Umbrüche, Trennlinie und Task-Referenzblöcke. Zulässige Textmarkierungen sind bold/italic/strike/code sowie vollständige HTTP(S)-Links mit begrenzten Attributen. Unbekannte Knoten/Attribute, unsichere Linkschemata, ungültige Kindstrukturen und veränderliche Nicht-JSON-Werte werden abgewiesen. Höchstens 1 MiB Dokument, 10.000 Knoten und Tiefe 32. Validierung liefert eine unabhängige JSON-Kopie. Task-Referenzen enthalten ausschließlich IDs und werden dedupliziert extrahiert; das ist keine Objektzugriffsfreigabe. Materialknoten werden erst mit der Materialintegration ergänzt.

23 neue echte Validierungstests ohne Repository-/Transport-Doubles: unterstützte Strukturen, stabile Referenzen, kein kopierter fremder Task-Titel, unsichere Links, falsche Attribute, Größen-/Tiefen-/Knotengrenzen, Snapshot-Kopie sowie erneut validierte manipulierte Befehle und strikte Revisionen. Gesamte Unit-Suite: 429 bestanden, neun bestehende Pydantic-Warnungen. Ruff/Mypy und no-test-doubles bestanden. Kein HTTP-/Persistenz-/Browsernachweis für Wissen behauptet; Fachoperationen mit echten Daten, Autorisierung und Editor bleiben offen.

## M2 — Transaktionale Wissensoperationen

`AsyncpgKnowledgeRepository` implementiert Erstellen, Lesen, Ändern und begrenzte Titelsuche. Änderungen schreiben Revisionssnapshot, stabile Task-Verweise, Audit und Command-Receipt atomar. Der Seitenkopf wird vor dem Lesen der aktuellen Revision gesperrt; konkurrierende Änderungen derselben erwarteten Revision ergeben einen Erfolg und einen Revisionskonflikt. Wiederholungen prüfen weiterhin aktuelle Konten- und Seitenrechte.

Task-Verweise werden über den öffentlichen Task-Service autorisiert. Der Bootstrap bindet dessen Repository intern an die vorhandene Verbindung; öffentliche Fach-APIs erhalten keine Datenbankverbindung. Damit funktionieren Verweise auch bei nur einer Pool-Verbindung. Verschachtelte Task-Schreiboperationen respektieren den äußeren Rollback. Historische Seitenrevisionen behalten ihre Verweise; Entfernen eines Verweises verändert oder löscht keine Aufgabe. Ein Seitenleser erhält über eine Referenz keine zusätzlichen Task-Rechte.

LIVE bestanden: Wissensvertrag mit Ein-Verbindungs-Pool, tatsächlicher Konkurrenz auf zwei Verbindungen, äußerem Rollback, Viewer/Editor-Wechsel, widerrufenem Zugriff, gesperrtem Konto, Titelsuche und unveränderter Historie nach abgewiesener Referenz. Bestehende Task-Service-, Aktionsrechte- und Produktions-FastAPI-Verträge ebenfalls bestanden. Ruff/Mypy und no-test-doubles erfolgreich. 429 Unit-Tests bestanden (neun bekannte Pydantic-Warnungen). Der Wissensvertrag läuft künftig im Schema-Gate. HTTP-Anbindung, vollständige Wissens-Aktionsrechtematrix, Mitgliederverwaltung, Editor, atomare Aufgabe-aus-Seite und Materialien bleiben offen.

## M2 — Wissens-HTTP-Adapter

Die Produktions-App erstellt den Knowledge-Service im Lifespan und registriert das Modul mit expliziter Tasks-Abhängigkeit. Vier Endpunkte unter `/api/v1/knowledge-pages` bieten Erstellen, Lesen, begrenzte Suche und revisioniertes Ändern. Der Adapter verwendet den bestehenden Sitzungsdienst sowie die globale CSRF-/Fehlerbehandlung; erfolgreiche Antworten sind `no-store`. Fachoperationen und deren Autorisierung bleiben im Modul-Service. OpenAPI und der gemeinsame TypeScript-Client sind regeneriert; bestehende Pfade und Schemas wurden strukturell unverändert bestätigt.

`tools/knowledge/http_contract.py` startet die tatsächliche Produktions-App gegen frisch migriertes PostgreSQL und ist ins Schema-Gate eingebunden. Bestanden: fehlende Sitzung, CSRF, camelCase, idempotentes Replay und abweichender Wiederholungsinhalt, Such-/UUID-Grenzen, unbekannte Seite, unerlaubte Dokumentknoten/Links, strikte Revision, Änderung und Revisionskonflikt sowie Kontosperre einschließlich Replay. Der erste Migrationsversuch traf den noch startenden Testcontainer; nach bestätigter Bereitschaft war das vollständige Upgrade erfolgreich. Keine externen Dienste oder Browserabläufe als geprüft behauptet.

429 Unit-Tests bestanden (neun bekannte Pydantic-Warnungen), Ruff/Mypy, API-Client-Typprüfung, Frontend-Transportgrenze und no-test-doubles ebenfalls erfolgreich. Wissensnavigation, Editor, Mitgliederverwaltung, Aktionsrechtematrix, Materialien und M2-Gesamtabnahme bleiben offen.

## M2 — Wissens-Aktionsrechte mit PostgreSQL

`tools/knowledge/action_contract.py` prüft zehn echte Konten über den Produktions-Bootstrap und zwei Aktionen. Aktuelle Mitglieder aller vier Aktionsrollen sowie der aktuelle System-Admin können die Aktionsseite lesen und finden. Schreiben ist auf Eigentümer/Aktionsadministration/System-Admin und explizite aktuelle Editoren begrenzt. Abgelaufene, zukünftige und fremde Mitgliedschaften sowie eine nur im Principal behauptete Systemrolle gewähren keine Rechte. Ein expliziter Editor-Eintrag für einen Außenstehenden umgeht die Aktionsgrenze nicht.

Nach Entzug der Mitgliedschaft verlieren auch Seiteneigentümer und expliziter Editor Lesen, Suche und Wiederholung alter Schreibbefehle. Nach Entzug der globalen Rolle verliert der System-Admin den Aktionszugriff. Private Seiten bleiben auch vor diesem Entzug für ihn unsichtbar; der Eigentümer behält seine private Seite unabhängig von seiner Aktionsmitgliedschaft. Der verbleibende Charity-Admin kann die Aktionsseite weiterhin lesen.

LIVE auf frisch bis 0038 migriertem PostgreSQL bestanden. Ruff/Mypy, no-test-doubles und Diffprüfung bestanden. Der Vertrag ist im Schema-Gate eingebunden. Die expliziten Editor-Zuordnungen sind reale SQL-Fixtures; damit ist keine Mitglieder-API oder Browser-Rechteprüfung behauptet. Diese sowie die übrigen offenen M2-/M3-Aufgaben bleiben erforderlich.

## M2 — Atomare Aufgabe aus Wissensseite

`KnowledgeService.create_task_from_page` verwendet den öffentlichen Task-Erstellungsvertrag einschließlich Zuständigkeit, Epic, Fälligkeit und Zurückstellung. Erwartete Seitenrevision und Zielliste ergänzen diesen Vertrag. Der aktuelle gespeicherte Seiteninhalt erhält eine stabile Task-ID am Dokumentende; Titel und Status der Aufgabe werden nicht in den Seiteninhalt kopiert. Der gemeinsame Transaktionsrahmen umfasst Task, Seitenrevision, Referenzen, beide Audits und Receipts. Der innere Task-Befehl erhält einen seitenbezogen abgeleiteten Wiederholungsschlüssel. Replay prüft erneut Seiten-Schreibrecht und Task-Leserecht, bevor das ursprüngliche Ergebnis zurückgegeben wird.

Der neue HTTP-Endpunkt `POST /api/v1/knowledge-pages/{page_id}/tasks` und der generierte Client sind verfügbar. Bestehende OpenAPI-Pfade und Schemas sind strukturell unverändert. Änderungen im noch ungespeicherten Editor werden von diesem Befehl nicht übertragen; die spätere Oberfläche muss sie vorher revisioniert speichern.

LIVE bestanden: gleicher Befehl bei einem Pool-Slot erzeugt genau eine Aufgabe; zwei konkurrierende Befehle auf zwei Verbindungen erzeugen einen Erfolg und einen Konflikt; veraltete Revision und fehlende Seiten-/Listenrechte werden abgewiesen. Ein bereits volles Dokument löst nach der inneren Task-Erstellung einen `document_limit`-Konflikt aus: Task-, Audit-, Receipt- und Revisionsanzahl bleiben unverändert. Task-Erledigung ändert dasselbe Task-Objekt, während die Seite ihre stabile Referenz behält. Nach Entzug der Listenrechte verrät auch Replay keine Task-Daten. Der Produktions-HTTP-Vertrag prüft Erstellung, Zuordnung, Replay und Konflikt ebenfalls. Der direkte Vertrag ist ins Schema-Gate aufgenommen.

429 Unit-Tests bestanden (neun bekannte Warnungen), Ruff/Mypy, API-Client-Typprüfung, Frontend-Transportgrenze und no-test-doubles erfolgreich. Editor, Darstellung des aktuellen referenzierten Task-Status im Browser, Mitgliederverwaltung, Materialien und vollständige M2-/M3-Abnahme bleiben offen.

## M2 — Wissens-Mitgliederverwaltung mit eigener Freigaberevision

Migration `0039_knowledge_access_revision` ergänzt einen positiven, bei 1 beginnenden Revisionszähler für Seitenrechte. Inhaltssnapshots behalten ihren bisherigen Revisionszähler. Die Verwaltung sperrt denselben Seitenkopf, prüft aktuelle Eigentümer-/Aktionsadministrationsrechte und vergleicht `expectedAccessRevision`; Freigabe, Zähler, Audit und Receipt werden atomar geschrieben. Editor-Rechte allein berechtigen nicht zur Freigabeverwaltung. Eigentümer sind geschützt; bei Aktionsseiten müssen hinzugefügte aktive Konten bereits aktuellen Aktionszugriff besitzen. Entfernen bleibt auch für inzwischen inaktive Konten möglich.

Benannte Service-Methoden, drei HTTP-Endpunkte und generierter Client unterstützen begrenzte Mitgliedersuche, viewer/editor/Entfernen sowie Hinzufügen eines bestehenden aktiven Kontos per E-Mail. Keine Einladung und kein Versand. E-Mail-Auflösung erfolgt erst nach Autorisierung. Inhalts- und Freigabeänderungen beeinflussen die jeweils andere Revision nicht.

LIVE bestanden: Standalone-Vertrag mit E-Mail-Auflösung, Replay, Eigentümerschutz, Managergrenze, Lesen/Bearbeiten/Entfernen und zwei tatsächlichen konkurrierenden Verbindungen; genau ein Freigabebefehl gewinnt. Aktionsvertrag ergänzt Charity-Admin-Verwaltung, System-Admin-Lesen und Ablehnung fremder Mitglieder. Produktions-HTTP prüft Freigabevertrag, Eigentümerschutz, unbekannte E-Mail und Query-Grenzen. Migration vorwärts, rückwärts und erneut vorwärts sowie erneuter Mitgliedervertrag und echter Schema-Smoke bestanden. Migrationspolicy, Ruff/Mypy, no-test-doubles, API-Client-Typprüfung und 429 Unit-Tests bestanden (neun bekannte Warnungen); bestehende OpenAPI-Verträge unverändert.

Die Mitgliederoberfläche, Wissenseditor, Materialintegration und übergeordnete M2-/M3-Abnahme bleiben offen. Frühere SQL-Fixtures bleiben als unabhängige Prüfung der Rechteauswertung bestehen.

## M2 — Gemeinsame Wissensnavigation und Seitenliste

Das Wissensmodul liefert aktive Konten in beiden Shells mit einem autorisierten Navigationseintrag. Die gemeinsame lazy-geladene Ansicht unter `/admin/knowledge` beziehungsweise `/app/knowledge` bietet begrenzte Titelsuche/Pagination und Anlage einer zunächst privaten Seite. Leere Ergebnisse, Laden, Fehler mit Wiederholung, unverlorener Eingabetitel und Erfolgsmeldung sind abgebildet. Die bestehende Shell und deren UI-Tokens bleiben maßgeblich. Diese erste Ansicht zeigt Seitenüberschriften; Öffnen/Bearbeiten, Aktionsauswahl und Freigabeverwaltung folgen noch.

LIVE: tatsächliche Produktionsbuilds gegen FastAPI/PostgreSQL über HTTPS in Chrome: Web legt Seite an → dieselbe Seite in der PWA → nicht passende und passende Suche. Mobile Aufnahme mit 390 × 844 und Desktop mit 1280 × 900, keine horizontale Überbreite; mobile Axe-Prüfung ohne serious/critical. Impeccable-Detektor ohne Treffer. Unabhängiger Screenshot-/Source-Reviewer: `ship` ausschließlich für den ersten Listen-/Anlage-Slice, keine notwendigen Korrekturen. Fehler-/Lade-/Paginationzustände wurden im Code, nicht als eigener Browsernachweis geprüft.

Web-/PWA-Typprüfung und beide Produktionsbuilds bestanden (bestehende Chunkgrößenwarnungen). Acht Modulregistrierungstests und 429 Unit-Tests bestanden; die Navigationserwartung wurde um Wissen ergänzt. Ruff/Mypy und no-test-doubles erfolgreich. Der temporäre Browser-Harness ist noch kein dauerhafter CI-Browser-Gate. Gesamte M2-/M3-Abnahme bleibt offen.

## M2 — Rechteauskunft für den Wissenseditor

`get_permissions` liefert für eine lesbare Seite `canEdit` und `canManage`. Die Rechteberechnung wird ebenfalls von Schreib- und Freigabeoperationen verwendet. Aktive Konten und aktueller Seiten-/Aktionszugriff werden davor geprüft; insbesondere gewährt Eigentümerschaft nach Entzug der Aktionsmitgliedschaft keine Auskunft. Die Oberfläche muss keine Rollenregeln nachbauen. Die Auskunft ist kein Berechtigungsnachweis für spätere Schreibaufrufe: diese prüfen weiterhin selbst den aktuellen Zustand.

HTTP und generierter Client ergänzt. LIVE: Eigentümer/Viewer/Editor, aktuelle Aktionsrollen, System-Admin sowie entzogene Mitgliedschaften über die vorhandenen Mitglieder-/Aktionsverträge; Produktions-HTTP prüft camelCase-Rechteantwort. Alle drei PostgreSQL-Verträge bestanden. 429 Unit-Tests, Ruff/Mypy, API-Client-Typprüfung und no-test-doubles bestanden; bestehende OpenAPI-Verträge unverändert. Editor und übrige offene Planaufgaben bleiben erforderlich.

## M2 — Gemeinsamer Tiptap-Editor und aktuelle Task-Verweise

Seitenlinks öffnen denselben lazy-geladenen Editor in Web und PWA. Der Editor übernimmt den typisierten Dokumentinhalt, zeigt serverseitige Bearbeitungsrechte und speichert Titel/Inhalt mit erwarteter Revision und stabilem Wiederholungsschlüssel. Toolbar für Fett/Kursiv/Überschrift/Aufzählung und Undo/Redo; weitere unterstützte Dokumentstrukturen bleiben erhalten. Ein Content-Check sperrt Speichern bei nicht darstellbaren Strukturen. Laufendes Speichern sperrt Eingaben. Konflikte ersetzen den Entwurf nicht; Hintergrundabfragen setzen ihn ebenfalls nicht zurück. Neuladen verwirft ihn nur nach ausdrücklicher Bestätigung und erfolgreichem Abruf. Ungespeicherte Änderungen erhalten den üblichen Browser-Verlassensschutz; keine lokale Speicherung vertraulicher Inhalte.

Task-Verweise sind atomare Tiptap-Knoten mit stabiler ID. Darstellung fragt das Task-Modul separat ab und zeigt aktuellen Titel/Status oder einen neutralen Nichtverfügbarkeitshinweis. Der Verweis öffnet die betreffende Aufgabenliste. Keine Task-Daten werden in den Dokumentknoten kopiert. Die Backend-Validierung berücksichtigt eng begrenzt Tiptaps tatsächliche Standardattribute für Listennummerierung und Linktitel. Die vier direkten Tiptap-Abhängigkeiten verwenden Version 3.31.3, bereits im vorhandenen Lockfile enthalten; keine zusätzliche Laufzeitkomponente. Frozen Install mit Bun 1.2.19 bestanden.

LIVE Chrome mit Produktionsbuilds, echtem FastAPI und PostgreSQL: Web speichern → PWA lesen → zweite Änderung im Web → PWA-Konflikt mit unverändertem Entwurf → bestätigtes Neuladen. Anschließend Task per tatsächlichem zusammengesetztem API-Aufruf erstellt, Titel im Editor gespeichert, stabile Referenz erhalten, Task erledigt und aktueller Status in beiden Shells nach Neuladen sichtbar. Separater echter Roundtrip für nummerierte Liste (Start 2), HTTP(S)-Link und Fettdruck bestanden. Das ist noch kein Browsernachweis für Task-Anlage über Editor-Bedienelemente.

Desktop/Mobilaufnahmen geprüft, mobile Axe ohne serious/critical und ohne horizontale Überbreite. Nach anfänglicher Prüfanforderung wegen überlagernder fixer Navigation bestätigt eine Aufnahme am Seitenende plus echte elementFromPoint-Prüfung beide unteren Schaltflächen als frei erreichbar. Unabhängiger Reviewer: `ship` für diesen Editor-Slice; Dokumentationsprüfung bestätigt unverändertes UI-System. Detektor ohne Treffer. Features-/Web-/PWA-Typprüfung, beide Builds, neun Registrierungstests sowie 436 Unit-Tests bestanden (neun bekannte Warnungen). Ruff/Mypy, no-test-doubles und Diffprüfung erfolgreich. Vorhandene Build-Chunkwarnungen bleiben sichtbar.

Freigabeoberfläche, Aktionsauswahl, Task-Anlage über Editor, Materialfunktionen, dauerhafte vollständige Browser-Gates und übrige M2-/M3-Abnahme bleiben offen.

## M2 — Gemeinsame Freigabeoberfläche für Seiten und Aufgabenlisten

`AccessMembersPanel` wird von beiden tatsächlichen Nutzern, Tasks und Wissen, wiederverwendet. Die gemeinsame Darstellung verwaltet begrenzte Mitgliedersuche, vorhandenes Konto per E-Mail, Lesen/Bearbeiten und Entfernen. Die jeweiligen typisierten API-Aufrufe und Zähler bleiben getrennt (`revision` für Task-Listen, `accessRevision` für Wissensfreigaben). Stabile Wiederholungsschlüssel, Konflikt-/Fehleranzeige und Neuladen bleiben erhalten. Der bisherige Task-Wrapper ist klein; nicht mehr verwendete Task-Mitglieder-CSS-Regeln wurden entfernt.

Wissensfreigaben erscheinen unter der Seitenüberschrift ausschließlich bei serverseitigem Verwaltungsrecht. Eine Freigabeänderung aktualisiert Rechte-/Mitgliederabfragen, ohne den lokalen Inhaltsentwurf oder dessen Revision neu zu initialisieren. Bestehende Aktionsrollen werden in der Oberfläche ausdrücklich erklärt; Entfernen eines zusätzlichen Zugriffs entzieht keine Aktionsmitgliedschaft.

LIVE Chrome/HTTPS mit zwei echten Sitzungen und PostgreSQL: Eigentümer gewährt Lesen → Kollegin sieht nur lesbaren Editor ohne Freigabebedienung → Eigentümer erlaubt Bearbeiten → Kollegin speichert in PWA → Eigentümer sieht denselben Inhalt → Entfernen ergibt für die Kollegin tatsächlich HTTP 404. Desktop-/Mobilaufnahmen und mobile Axe ohne serious/critical oder Überbreite. Bestehender vollständiger Task-Mitglieder-Browserlauf erneut bestanden: Lesen/Bearbeiten, Zuweisung, Kollegin erledigt, Herabstufen und Entfernen mit anschließendem 404.

Features-/Web-/PWA-Typprüfungen, beide Produktionsbuilds, neun Registrierungstests, no-test-doubles und Diffprüfung bestanden. Bestehende Chunkwarnungen bleiben unverändert. Detektor ohne Treffer. Unabhängige UI-Prüfung: `ship` unter der inzwischen erfüllten Task-Regressionsbedingung; keine erforderlichen Korrekturen oder dauerhaften Designänderungen. Minor limitation: Während Rechteänderungen sind die Controls gesperrt, ohne separate Speichern-Statusansage. Mobile Tastatur-/Screenreader-Nutzung ist damit nicht vollständig abgenommen.

Aktionsauswahl, Task-Anlage aus dem Editor, Materialien, vollständige Browser-Gates und übrige M2-/M3-Arbeit bleiben offen.

## M2 — Task-Anlage aus dem gemeinsamen Wissenseditor

„Aufgabe aus dieser Seite“ öffnet eine begrenzte Listenwahl und danach das bereits vorhandene Task-Formular mit Zuständigkeit, Epic, Fälligkeit und Zurückstellung. Ein konkreter Erstellungs-Callback verwendet den atomaren Wissensbefehl statt einer separaten Task-Anlage. Ungespeicherte Seitenänderungen müssen vorher gespeichert werden; während der Aufgabenanlage bleiben Seiteninhalt und Revision unverändert. Erfolg übernimmt die neue Seitenrevision und stabile Task-Referenz. Der Browser-Verlassensschutz berücksichtigt den offenen Aufgabenentwurf; ein Rechte-Refresh entfernt das offene Formular nicht. Schreibrechte werden weiterhin durch den tatsächlichen Befehl geprüft.

LIVE Chrome mit Produktionsbuilds, FastAPI und frischem PostgreSQL-Schema: Web-Seite speichern → Liste wählen → Aufgabe einer Kollegin zuweisen → Kollegin erledigt in PWA „Für mich“ → ursprüngliche Seite zeigt denselben erledigten Task. Separater tatsächlicher konkurrierender Seiten-Schreibzugriff: HTTP 409, eingegebener Aufgabentitel bleibt erhalten, keine Aufgabe erzeugt, Abbrechen und bestätigtes Neuladen zeigen neue Seitenversion. Der Konflikthinweis erklärt hierfür ausdrücklich die Seitenaktualisierung und das vorherige Kopieren der Aufgabenangaben. Das bestehende vollständige Task-Mitglieder-/Zuweisungs-Browserszenario besteht weiterhin.

Features-/Web-/PWA-Typprüfungen und beide Produktionsbuilds bestanden; bestehende Chunk-/Sourcemapwarnungen bleiben sichtbar. Mobile Axe ohne serious/critical und ohne horizontale Überbreite; Desktop-/Mobilaufnahmen durch unabhängige UI-Prüfung abgenommen. Deren konkrete Korrektur am Konflikthinweis ist umgesetzt und erneut freigegeben. Detektor ohne Treffer, no-test-doubles bestanden. Temporäre Browser-Harnesses ersetzen weiterhin nicht die ausstehende dauerhafte CI-Browserabnahme.

Die Listenwahl zeigt lesbare Listen; fehlendes Schreibrecht wird beim autorisierten Aufruf abgewiesen. Aktionsauswahl für Wissen, Materialfunktionen, vollständige Browser-Gates und übrige M1-/M2-/M3-Abnahme bleiben offen.

## M2 — Aktionskontext für Wissensseiten mit gemeinsamer Suche

Die vorhandene begrenzte Aktionssuche wird als konkreter Hook und Suchbedienung von Tasks und Wissen gemeinsam verwendet. Die bestehende API liefert aktuelle Aktionsmitgliedschaften und Verwaltungsrecht (`canCreateLists`); dessen serverseitige Regel stimmt mit der vorhandenen Wissens-Seitenanlage überein. Die Wissensoberfläche ergänzt Kontextwahl, Aktionsfilter und Kontextnamen in der Ergebnisliste. Eigenständige Seiten bleiben möglich und zunächst privat. Auswahl bleibt über Suchseiten hinweg erhalten; Fehler liefern keine veralteten Auswahlangebote. Jede tatsächliche Seitenanlage prüft aktuelle Rechte erneut. Keine neue Infrastruktur und kein zusätzlicher API-Vertrag.

LIVE Chrome mit beiden Produktionsbuilds und echter FastAPI/PostgreSQL: leere und passende Aktionssuche, Charity-Admin legt Aktionsseite an, aktuelles Mitglied findet sie in der PWA über den Aktionsfilter und öffnet sie nur lesbar. Für dieses Mitglied fehlt die aktionsgebundene Anlageoption; der direkte API-Versuch liefert tatsächlich 404. Bestehender Task-Aktionsbrowserlauf nach gemeinsamer Extraktion bestanden: Liste anlegen/filtern, Mitglied zuweisen, PWA erledigen, gleicher Status beim Eigentümer.

Features-/Web-/PWA-Typprüfungen, beide Builds, zehn Registrierungstests und no-test-doubles bestanden; bekannte Pydantic- und Buildwarnungen unverändert. Mobile Axe ohne serious/critical oder Überbreite, Desktop-/Mobilaufnahmen geprüft, Detektor ohne Treffer. Unabhängige UI-/Dokumentationsprüfung: ship, keine erforderlichen Korrekturen oder neuen Designregeln. Die temporären Browser-Harnesses sind weiterhin kein dauerhafter CI-Gate. Materialkontexte und -funktionen sowie übrige offene Planabnahmen bleiben erforderlich.

## M2 — Materialschema und genaue Versionsreferenzen

Migration `0040_material_versions` legt `material`, `material_version`, `material_member` und die wissenseigene Referenztabelle `knowledge_page_material` an. Materialien besitzen Titel, Eigentümer, optionalen Aktionskontext, Schreibrevision, separate Freigaberevision und aktuellen Versionskopf. Dateiversionen tragen Dateiname, Medientyp, Größe (für diesen Upload-Schnitt maximal 25 MiB), SHA-256 und vollständige bestehende S3-Position einschließlich unveränderlicher Storage-Version-ID. Ein verzögert geprüfter Fremdschlüssel verhindert einen Materialkopf ohne eigene Dateiversion. Die technische Speicherposition gehört eindeutig zu einer Materialversion.

Wissen besitzt seine Seitenverweise und bindet sie an eine konkrete Materialversion. Mehrere Seiten können denselben Inhalt referenzieren; eine neue Materialversion verändert bestehende Verweise nicht. Entfernen von Wissensseiten entfernt deren Verweise, keine Materialien oder Dateiversionen. Das Schema gewährt durch einen Verweis keinerlei Rechte; die kommende Fachoperation muss den Zielzugriff prüfen. Die anschließenden Service-Pfade schreiben neue Versionen statt vorhandene umzuschreiben; dieses Verhalten ist mit dem Schema allein noch nicht abgenommen.

Wiederverwendungsentscheidung nach Codeprüfung: `ObjectStorage`/`S3ObjectStorage` werden für private versionierte Bytes und Integritätsprüfung wiederverwendet. `GeneratedDocumentService` bleibt für erzeugte Rechnungsdokumente zuständig: dessen Pflichtbezug auf Rechnung/Commitment, Finanzberechtigung und Versand-Unveränderlichkeit passen nicht zu allgemeinen hochgeladenen Materialien. Es entstehen weder eine zweite Dateiablage noch kopierte Rechnungsobjekte. Material-Metadaten und Freigaben gehören dem neuen Fachmodul, konkrete Referenzen dem jeweils einbettenden Modul.

LIVE PostgreSQL auf leerem Schema: zwei Seiten auf derselben Dateiversion, neuer Versionskopf ohne Umhängen der Referenzen, Entfernung der Seiten ohne Dateiverlust und 21 ungültige Schreibversuche geprüft. Neue Migration zurückgenommen und erneut ausgeführt, Materialvertrag danach erneut bestanden; tatsächlicher Schema-Smoke erfolgreich. Dauerhaften Vertrag in Schema-Gate sowie Ruff/Mypy-Läufe aufgenommen. Ruff, Mypy, Migrationspolicy, Shell-Syntax, no-test-doubles und Diffprüfung bestanden. Kein S3-Upload wurde durch diesen Schema-Slice nachgewiesen; Fachoperationen, aktuelle Rechteauswertung, HTTP/UI, Upload-Wiederholung und vollständige Materialabnahme bleiben offen.

## M2 — Direkte Materialoperationen mit vorhandener S3-Ablage

`materials/api.py` veröffentlicht strikte Upload-Metadaten, neue Dateiversionen, begrenzte Materialsuche, Metadatenabfragen und autorisierten Download. Uploadbytes bleiben ein eigener Python-Parameter; Clients bestimmen weder Prüfsumme noch S3-Position. Dateinamen müssen einfache Basenames ohne Pfad-/Steuerzeichen sein, Medientypen parameterfrei; tatsächliche Bytes sind auf 1 Byte bis 25 MiB begrenzt. Befehle werden beim Service-Aufruf erneut validiert. Öffentliche Ausgaben enthalten keine Buckets, Objektschlüssel oder Storage-Version-IDs.

`AsyncpgMaterialRepository` verwendet den vorhandenen `ObjectStorage`-Port. Aktueller Konten-/Materialzugriff wird für Suche, Metadaten und Download geprüft; zusätzliche Versionen benötigen Schreibrecht und erwartete Materialrevision. Neue Versionen werden eingefügt, alte nicht umgeschrieben. Audit und Receipt werden mit den Metadaten atomar gespeichert. Request-Hash umfasst Metadaten und tatsächlichen Byte-Hash. Stabile Material-/Objektschlüssel verwenden den Befehlsschlüssel; `put_immutable` und byteidentisches Rücklesen bestätigen die gespeicherte Version. Replay prüft erneut aktuelle Rechte. Eine interne verbindungsgebundene Repository-Instanz erlaubt einen echten äußeren Transaktionsrahmen; öffentliche Fachsignaturen bleiben frei von Datenbankverbindungen.

LIVE mit PostgreSQL und der vorhandenen gepinnten RustFS-Version: zwei parallele gleiche Uploads liefern dasselbe Material; veränderte Bytes unter demselben Schlüssel führen zum Konflikt. Zwei parallele Versionsbefehle mit gleicher Ausgangsrevision ergeben einen Erfolg und einen Konflikt; ursprüngliche Bytes bleiben abrufbar. Private Suche/Metadaten/Download, expliziter Viewer, abgewiesener Viewer-Upload, Rechteentzug und gesperrtes Konto einschließlich Replay geprüft. Audit-/Versions-/Receiptanzahlen bestätigt. Ein echter äußerer DB-Rollback nach erfolgreichem S3-Upload entfernt den Materialzustand und Audit; erneuter Befehl übernimmt exakt dieselbe Storage-Version-ID und liefert dieselben Bytes. Keine I/O-Doubles.

Dauerhaften PostgreSQL-/S3-Servicevertrag ins Schema-Gate aufgenommen; dieses startet dafür den bestehenden RustFS-Dienst zusätzlich zur Testdatenbank. Der Vertrag wurde direkt gegen isolierte Instanzen ausgeführt; der vollständige Compose-Gate wurde in diesem Slice nicht erneut ausgeführt. 466 Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff/Mypy, no-test-doubles, Shell-Syntax und Diffprüfung bestanden.

Bootstrap/HTTP/Client/UI, Material-Freigabeverwaltung, vollständige Aktionsrechtematrix und Wissenseinbettung bleiben offen. Ein nach S3-Erfolg endgültig abgebrochener Upload kann ein privates, noch nicht referenziertes Speicherobjekt hinterlassen; Wiederaufnahme ist bewiesen, kontrollierte Bereinigung solcher nie wiederaufgenommenen Objekte bleibt für die Materialabnahme erforderlich. Der deklarierte Medientyp ist keine Inhaltsprüfung; HTTP muss Downloads als Anhänge und mit nosniff ausliefern.

## M2 — Material-HTTP und generierter Multipart-Client

Das Materialmodul registriert sechs HTTP-Operationen über Bootstrap: Anlage, zusätzliche Version, Materialliste, Materialmetadaten, Versionsmetadaten und Download. Produktions-Lifespan injiziert den bestehenden S3-Adapter. Uploads verwenden das bereits installierte Multipart-Paket; unbekannte und doppelte Formularfelder werden abgewiesen. Die Fach-API erhält Dateiname, tatsächliche Bytes und den auf type/subtype normalisierten Multipart-Medientyp. Parameter wie das von Bun ergänzte charset werden am Transport entfernt. Öffentliche Formfeldnamen sind camelCase und entsprechen dem generierten Vertrag.

Die bisher nur für Surveys verwendete Größenbegrenzung liegt jetzt unter `platform/http_body.py` und bekommt ihre Pfadgrenzen im Entrypoint. Survey-Pfade behalten 1 MiB. Materialanfragen sind vor dem Multipart-Parsing auf 25 MiB plus 64 KiB Metadaten begrenzt, einschließlich gestreamter Anfragen; die tatsächliche Datei bleibt auf 25 MiB begrenzt. Der alte Middleware-Pfad wurde entfernt. Downloads prüfen den aktuellen Zugriff und liefern Bytes als application/octet-stream-Anhang mit UTF-8-Dateiname, nosniff und no-store; keine S3-URL wird exponiert.

Der vorhandene Clientgenerator unterstützt für diesen konkreten Bedarf flache Multipart-Bodies mit Blob/File und FormData. Der Browser/Runtime setzt den Boundary-Header selbst. Binary-Downloads verwenden den bestehenden Blob-Pfad und das normale typisierte Fehlerprotokoll. Alle vorherigen OpenAPI-Pfade und Schemas wurden strukturell unverändert bestätigt.

LIVE mit Produktions-FastAPI, echtem PostgreSQL und RustFS: Sitzung/CSRF, Anlage, Replay, geänderte Bytes unter gleichem Schlüssel, zweite Version, Erhalt der ersten Bytes, Metadatensuche und geschützte Attachment-Header bestanden. Ungültige Dateinamen/Medientypen, leere Dateien, unbekannte/doppelte Formfelder sowie ein tatsächlicher 26-MiB-Stream werden abgewiesen. Survey-Limit nach Extraktion ebenfalls per echter Anfrage bestätigt. Der tatsächlich generierte TypeScript-Client wurde über lokalen HTTPS-Testserver ausgeführt: File-Upload/Replay, UTF-8-Name, neue Version, byteidentischer Blob-Download und ApiError(409) bestanden. Dieser Client-Harness ist temporär; der dauerhafte HTTP-Vertrag ist im Schema-Gate aufgenommen.

466 Unit-Tests mit neun bekannten Pydantic-Warnungen, Ruff/Mypy, API-Client-Typprüfung, no-test-doubles, Frontend-Transportgrenze und Diffprüfung bestanden. Vollständiger Compose-Gate in diesem Slice nicht wiederholt. Freigabeverwaltung, Navigation/UI, Aktionsmatrix, Materialreferenzen im Editor und kontrollierte Bereinigung nicht wiederaufgenommener Uploads bleiben offen.

## M2 — Materialfreigaben und gemeinsame Rechteberechnung

Öffentliche Operationen verwalten bestehende aktive Konten per E-Mail oder ID als viewer/editor beziehungsweise entfernen zusätzliche Rechte. E-Mail-Auflösung erfolgt erst nach aktueller Verwaltungsprüfung. Eigentümer sind geschützt, Aktionsmaterialien können nur innerhalb des aktuellen Aktionszugriffs geteilt werden. Der vorhandene separate `access_revision`-Zähler wird unter derselben Materialkopfsperre geprüft und mit Freigabe, Audit und Receipt atomar erhöht. Dateirevision und Versionskopf bleiben unverändert. Die gemeinsame Rechteberechnung liefert `canEdit`/`canManage` und wird ebenfalls von Schreib- und Verwaltungsoperationen verwendet; Leserecht wird davor erneut geprüft.

Vier HTTP-Operationen und generierter Client ergänzen Mitgliedersuche, ID-/E-Mail-Freigabe und Rechteauskunft. Der Upload-Receipt-Hash bleibt für bestehende Materialoperationen unverändert. Sämtliche bisherigen OpenAPI-Pfade und Schemas wurden strukturell unverändert bestätigt.

LIVE mit PostgreSQL/RustFS: E-Mail-Freigabe und Replay, Mitgliedersuche, Eigentümerschutz, abgewiesene Viewer-Verwaltung, zwei konkurrierende Freigabebefehle mit genau einem Konflikt, Editor lädt neue Version hoch, unabhängige Freigabe-/Dateirevision, Entzug sperrt Download. Bei Aktionsmaterial wird ein Außenstehender abgewiesen; nach aktiver Mitgliedschaft darf er explizit Editor werden. Abgelaufene Aktionsmitgliedschaft sperrt danach sowohl Eigentümer als auch Editor. Diese konkrete Aktionsprüfung ersetzt noch nicht die vollständige Rollen-/Such-/Replay-Matrix.

Produktions-HTTP-Vertrag bestätigt Rechteauskunft, E-Mail-Freigabe/Replay, Suche und Entfernen ohne Änderung der Dateirevision. Bestehender Upload-/Rollback-Servicevertrag erneut bestanden. Dauerhaften Mitgliedervertrag ins Schema-Gate aufgenommen. 466 Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff/Mypy, API-Client-Typprüfung, no-test-doubles, Frontend-Transportgrenze und Diffprüfung bestanden. Gesamter Compose-Gate in diesem Slice nicht wiederholt. Freigabeoberfläche, übrige Material-UI, vollständige Aktionsmatrix, Wissensreferenzen und Upload-Bereinigung bleiben offen.

## M2 — Gemeinsame Materialoberfläche in Web und PWA

Das Materialmodul registriert Navigation und verzögert geladene gemeinsame Seiten in beiden Shells. Die Oberfläche bietet private beziehungsweise aktionsbezogene Anlage, begrenzte Titelsuche und Aktionsfilter, Dateiversionen bis 25 MiB, gezielte Versionswahl und autorisierte Downloads. Aktionssuche und Freigabebedienung werden mit Aufgaben und Wissen geteilt. Aktuelle Rechte steuern Upload und Verwaltung; der Server prüft jeden Zugriff erneut. Fehlgeschlagene Uploads erhalten die Dateiauswahl und den Wiederholungsschlüssel; tatsächliche Eingabeänderungen erzeugen einen neuen Schlüssel.

LIVE mit echtem PostgreSQL, RustFS und Produktions-FastAPI über HTTPS: Web-Upload und Viewer-Freigabe per E-Mail; Kollegin findet das Material in der PWA und lädt identische Bytes herunter, ohne Verwaltungs- oder Uploadbedienung. Nach Editor-Freigabe lädt sie Version 2 hoch. Der Eigentümer kann Version 1 weiterhin mit ursprünglichen Bytes herunterladen. Nach Entzug liefert der Download für die Kollegin 404. Mobile Axe-Prüfung ohne schwere/kritische Befunde und ohne horizontalen Überlauf; Desktop und Mobilansicht visuell geprüft. Die gemeinsame Freigabebedienung wurde zusätzlich mit echten Aufgaben- und Wissensabläufen einschließlich Entzug erneut geprüft.

Features-/Web-/PWA-Typprüfungen und beide Produktionsbuilds bestanden. 466 Python-Unit-Tests (neun bekannte Pydantic-Warnungen), zehn Modulregistrierungstests, Ruff/Mypy, no-test-doubles und Diffprüfung bestanden. Unabhängige UI-Abschlussprüfung: keine erforderlichen Codekorrekturen. Die temporären Browsernachweise ersetzen noch keinen dauerhaften CI-Browser-Gate; gesamter Compose-Gate nicht erneut ausgeführt. Vollständige Material-Aktionsmatrix, versionsgebundene Wissenseinbettung und kontrollierte Bereinigung nicht wiederaufgenommener Uploads bleiben offen.

## M2 — Autorisierte Materialreferenzen in Wissensrevisionen

Der strikte Dokumentvertrag unterstützt `materialReference` mit ausschließlich `materialId` und einer positiven konkreten `version`. Dateinamen, URLs oder weitere geschützte Metadaten werden nicht im Dokument zwischengespeichert. Doppelte Referenzen werden für die revisionsbezogene Verknüpfung dedupliziert. Beim Erstellen und Ändern einer Seite prüft die öffentliche Materialoperation `get_version` den aktuellen Zugriff und die Existenz der genauen Version. Bootstrap bindet den Material-Service wie den Task-Service an dieselbe Transaktionsverbindung; keine fremden Repository-Imports im Wissensmodul und kein zusätzlicher Pool-Slot. Die vorhandene S3-Instanz wird vom Entrypoint weitergereicht.

Dauerhafter LIVE-Vertrag mit echtem PostgreSQL, RustFS und einem Ein-Verbindungs-Pool: ein Upload in zwei Seiten, neue Dateiversion ohne Änderung bestehender Referenzen, alte und neue Bytes getrennt abrufbar; lesbare Seite gewährt keine Materialrechte. Ohne Materialzugriff scheitern Anlage und Änderung, nach Viewer-Freigabe gelingt das Speichern. Fehlende Version und späterer Entzug lassen Seitenrevision, Referenzanzahl und Audit unverändert. Entfernen beider Seiten lässt die ursprüngliche Datei abrufbar. Produktions-FastAPI-Vertrag prüft zusätzlich HTTP-Anlage/Lesen mit Materialreferenz und vollständigen Rollback beim Verweis auf eine fehlende Version.

477 Unit-Tests mit neun bekannten Pydantic-Warnungen bestanden. Wissens-Service-, Task-aus-Seite-, Aktionsrechte- und Mitgliederverträge mit echten Datenbankoperationen erneut bestanden; Ruff/Mypy und no-test-doubles bestanden. Den neuen Materialreferenzvertrag ins Schema-Gate aufgenommen. Der vollständige Compose-Gate bleibt ausstehend. Editor-Darstellung und Auswahl der Materialreferenzen sind noch nicht umgesetzt: der vorhandene Editor blockiert Speichern bei nicht unterstützten Dokumentknoten, statt sie still zu entfernen. Dieser Backend-Slice ist keine vollständige Abnahme der Wissenseinbettung.

## M2 — Materialreferenzen im gemeinsamen Wissenseditor

Der Tiptap-Editor unterstützt feste Materialreferenzen und eine begrenzte Materialsuche mit Pagination und expliziter Versionswahl. Einfügen verändert zunächst den Seitenentwurf; das reguläre revisionierte Speichern prüft den Zielzugriff erneut. Die Darstellung fragt Dateinamen und Version aktuell über die Material-API ab, ohne diese Daten im Dokument zu speichern. Fehlender Zugriff zeigt einen neutralen Nicht-verfügbar-Zustand. Materialbereich und Wissensreferenz teilen denselben autorisierten Blob-Download. Auswahl und Darstellung werden unverändert von Web und PWA verwendet.

LIVE mit Produktions-FastAPI, PostgreSQL und RustFS über HTTPS: Version 1 trotz vorhandener Version 2 in Web und PWA auswählen; zwei Seiten referenzieren denselben Upload. Speichern, Neuladen und anschließendes Ändern des Titels erhalten die exakte Referenz. Download liefert die ursprünglichen Bytes. Seitenfreigabe allein zeigt keine Dateiinformationen; zusätzliche Materialfreigabe erlaubt Anzeige und Download, Entzug macht die Datei wieder nicht verfügbar. Bestehender Materialbereich mit Upload, Freigabe, neuer Version, altem Download und Entzug nach Wiederverwendung der Downloadfunktion erneut bestanden.

Mobile Axe-Prüfung ohne schwere/kritische Befunde. Ein gültiger Titel mit 180 ununterbrochenen Zeichen deckte einen Picker-Überlauf auf; scoped Umbruch und Breitenbegrenzung korrigieren ihn. Gesamter Ablauf danach erneut erfolgreich, ohne horizontalen Überlauf. Download nach abgeschlossenem Scrollen per tatsächlichem Hit-Test als unverdeckt bestätigt. Features-/Web-/PWA-Typprüfung, beide Produktionsbuilds (bestehende Chunk-/Sourcemapwarnungen), Modulregistrierungstests, no-test-doubles und Diffprüfung bestanden. Browser-Harnesses bleiben vorerst temporäre LIVE-Nachweise, kein dauerhafter CI-Gate. Vollständige Material-Aktionsmatrix, Upload-Bereinigung und übrige M0–M3-Abnahmen bleiben offen.

Unabhängige Abschlussprüfung nach Korrektur und neuen Aufnahmen: ship für diesen UI-Slice, keine verbleibenden wesentlichen Befunde. Separate Dokumentationsprüfung bestätigt eine lokale Erweiterung des bestehenden Designs ohne neue globale Designregeln.

## M2 — Vollständige Material-Aktionsrechtematrix

Dauerhafter Vertrag `tools/materials/action_contract.py` prüft zehn synthetische Identitäten mit echten aktuellen PostgreSQL-Rollen: Eigentümer und weitere Charity-Administration, Acquirer, Finance Reader, Driver, abgelaufene und zukünftige Mitgliedschaft, Verwaltung einer anderen Aktion, aktueller System-Admin sowie Außenstehender mit veralteter/behaupteter System-Admin-Rolle im Principal. Leserechte gelten für Material, genaue Versionsmetadaten, tatsächlichen S3-Download, Titelsuche und Aktionsfilter. Upload und Freigabeverwaltung bleiben auf die vorgesehenen aktuellen Rechte beschränkt. System-Administration gewährt keinen pauschalen Zugriff auf eigenständige Privatdateien.

Explizite Editoren können Versionen ergänzen, aber zusätzliche Mitgliederdaten umgehen die aktuelle Aktionsgrenze nicht. Herabstufung auf Viewer sperrt einen zuvor erfolgreichen Upload-Replay trotz fortbestehenden Leserechts. Späterer Entzug der Aktionsmitgliedschaft sperrt Eigentümer und Editor; Entfernung der globalen Rolle sperrt den zuvor berechtigten System-Admin. Wiederholte Anlage/Versionsbefehle werden erneut autorisiert. Originalbytes bleiben für berechtigte Rollen abrufbar. Der Vertrag verwendet echte private RustFS-Dateiversionen, keine I/O-Doubles.

Vertrag auf realem PostgreSQL/RustFS bestanden, auch bei Wiederholung mit unabhängig erzeugten Identitäten und Titeln. In den dauerhaften Schema-Testlauf aufgenommen. Ruff/Mypy, Shell-Syntax, no-test-doubles und Diffprüfung bestanden. Keine Änderung der Fachimplementierung erforderlich. Gesamt-Compose-Gate nicht erneut ausgeführt; Browser-Gates, kontrollierte Upload-Bereinigung und übrige M0–M3-Arbeiten bleiben offen.

## M2 — Kontrollierte Bereinigung abgebrochener Materialuploads

Uploader und Wartung verwenden dieselbe PostgreSQL-Advisory-Transaktionssperre pro Bucket/Objektschlüssel. Die Sperre bleibt bei einem äußeren Aufrufer bis zu dessen Commit/Rollback bestehen. Die neue administrative Fachoperation akzeptiert ausschließlich Material-/Upload-UUID und exakte Storage-Version; Bucket und Schlüsselpräfix sind serverseitig festgelegt. Sie prüft aktuelle aktive System-Administration und unter der Sperre das Fehlen einer `material_version`-Referenz. Vorhandene S3-Metadaten müssen zum Material gehören. Referenzierte Dateiversionen bleiben geschützt.

`tools/materials/cleanup.py` verwendet normale Laufzeitkonfiguration, einen Standard-Prüflauf und explizites `--apply`. Die administrative S3-Versionsansicht liefert die konkrete Kandidatenposition; es gibt keinen automatischen Bucket-Scan oder neue Hintergrundinfrastruktur. Der tatsächliche Löschversuch wird vor dem externen S3-Aufruf dauerhaft mit Begründung und Selektoren protokolliert. Ein separater Abschluss mit derselben Request-ID bestätigt das Ende. Bereits fehlende exakte Versionen erlauben sichere Wiederholung. Die Betriebsanleitung erläutert aktuelle Writer-Versionen, autoritative Datenbank, Auswahl, Prüflauf, Löschung und Prüfung unterbrochener Versuche.

LIVE-Vertrag mit PostgreSQL/RustFS: Die Wartung blockiert nachweislich an der tatsächlichen Advisory-Sperre eines laufenden Uploads; ihre Anforderung ist bereits dauerhaft sichtbar. Nach Upload-Commit wird die Löschung abgewiesen, nach echtem äußeren Rollback erfolgreich ausgeführt. Wiederholung und spätere Wiederaufnahme des ursprünglichen Uploads funktionieren. Prüflauf erhält Bytes, Nicht-Admin und entzogene globale Rolle werden abgewiesen. Der tatsächliche CLI-Prozess wurde im Prüflauf und mit `--apply` ausgeführt. Bestehender Material-Upload-/Replay-/Rollback-Vertrag und Wissensreferenzvertrag erneut bestanden.

487 Unit-Tests mit neun bekannten Pydantic-Warnungen, Ruff/Mypy, no-test-doubles, Shell-Syntax und Diffprüfung bestanden. Dauerhaften Bereinigungsvertrag in das Schema-Gate aufgenommen; gesamter Compose-Gate noch nicht erneut ausgeführt. Dieser Slice schließt die konkrete Bereinigungslücke, nicht die verbleibenden Browser-CI-, M1- und M3-Abnahmen.

## CI — Formatierung nach Materialregistrierung

Der aktuelle Remote-Lauf für `47e4f5d` meldete als konkreten Fehler in „Lint and types“ ausschließlich die Ruff-Formatierung von `tests/unit/test_identity_domain.py`. Die Datei wurde formatiert; keine Testsemantik geändert. Lokal die beiden vollständigen Ruff-Prüfumfänge und Formatprüfungen aus `tools/ci/lint-types.sh` ausgeführt (11 beziehungsweise 442 Dateien), Mypy für alle 379 dort ausgewählten Source-Dateien, vollständige dortige Prettier-Zielmenge und OpenAPI-/Client-Aktualitätscheck: bestanden. Das ersetzt keine vollständige Remote-CI-Abnahme. Der separate lokale isolierte Compose-Schema-Gate läuft zum Zeitpunkt dieses Korrektur-Slices noch; sein Ergebnis wird gesondert dokumentiert.

## Integration — Task-Pagination mit vorhandenem Testbestand

Der isolierte Compose-Gate auf dem Image von `47e4f5d` bestand Leeraufbau bis `0040`, Materialschema/-Service/-Freigaben/-Aktionsmatrix/-Bereinigung/-HTTP, Wissensschema/-Service/-Materialreferenzen/-HTTP/-Aktionsmatrix/-Task-Anlage/-Mitglieder sowie Task-Service/-HTTP. Anschließend scheiterte der Task-Aktionsvertrag an der Annahme, dass der globale Administrator insgesamt nur die beiden lokal angelegten Aktionen sieht. Die vorhergehenden Materialverträge hatten weitere berechtigte Aktionen hinterlassen. Damit sind weder der gesamte Gate noch der nachfolgende Legacy-Upgrade-Abschnitt bestanden.

Die Pagination-Abfrage verwendet jetzt den eindeutigen Titelpräfix ihrer eigenen zwei Aktionen. Ungefilterte Berechtigungsprüfungen bleiben unverändert. Der vollständige Task-Aktionsvertrag wurde mit einer zusätzlich angelegten fremden Aktion in echtem PostgreSQL erneut ausgeführt und bestand. Der abgebrochene Compose-Gate hat seine Container, Volumes und acht Netzwerke vollständig entfernt; dies wurde anhand seiner exakten Projektlabels bestätigt. Ein erneuter Gesamt-Gate bleibt erforderlich. Der Remote-Lint-/Typcheck für `f88bf76` ist inzwischen erfolgreich abgeschlossen.

## M3 — Additives Inbox-Schema

Migration `0041_inbox_cases` ergänzt Fälle mit begrenzten Eingangsfeldern, optionaler Aktion und Zuständigkeit, Abschlussnotiz und Wiederöffnung. Die Kontaktzuordnung besitzt eine unabhängige Revision, eine stabile Create-ID und eine verpflichtende Referenz auf den bestehenden Outbox-Auftrag. Task-Referenzen, exakte Materialversionen und interne Kommentare gehören zum Fall; das Entfernen eines Falls entfernt keine referenzierten Aufgaben oder Dateien.

`tools/inbox/schema_contract.py` prüft mit echtem PostgreSQL die Ausgangszustände, Abschluss/Wiederöffnung, unabhängige Kontaktänderungen und 23 abgewiesene Schreibvorgänge. Leeraufbau bis 0041, Downgrade auf 0040 und erneutes Upgrade wurden ausgeführt; der generische Schema-Smoke am aktuellen Head sowie der Inbox-Vertrag bestehen. Ein Smoke am absichtlich zurückgesetzten 0040 wurde wegen des erwarteten aktuellen Heads 0041 abgewiesen; dies ist kein Nachweis für einen Code-Rollback. Inbox-Tabellen und Vertrag sind in das bestehende Schema-Gate aufgenommen; lokale und CI-Lint-/Typprüfungen berücksichtigen das neue Werkzeug.

Ruff, Formatprüfung, Mypy, Migrationspolicy und Shell-Syntax bestanden. Der Schema-Vertrag und `tools/schema/smoke.py` wurden vor diesem Commit erneut gegen die tatsächliche Datenbank ausgeführt. Das Schema erzwingt noch keine Unveränderlichkeit des Eingangssnapshots und beweist keine atomare öffentliche Einreichung: Fachoperationen, aktuelle Zugriffsprüfung, HTTP, CRM-Worker und sämtliche Inbox-Oberflächen bleiben offen. Der vollständige Compose-/Legacy-Gate bleibt gesondert erforderlich.

## M3 — Atomarer Inbox-Eingang als direkte Fachoperation

`InboxService.submit` revalidiert auch direkt übergebene Modelle: begrenzte Namen, Betreff und Nachricht, gültige E-Mail oder begrenzte Telefonnummer, keine unzulässigen Steuerzeichen. Bootstrap verdrahtet die konkrete PostgreSQL-Implementierung. Eine Transaktion schreibt Fall, bestehende Outbox, Audit und vorhandenen Command-Receipt. Der Auftrag enthält nur die Fall-ID; weder Audit noch Receipt duplizieren den Eingangstext. Als öffentliche Bestätigung wird ausschließlich eine zufällige Referenz zurückgegeben, die kein Zugriffstoken ist. Aktionsbezogene neue Eingänge setzen eine aktuell aktive Veröffentlichung voraus. Bereits bestätigte identische Eingänge bleiben nach Veröffentlichungsende wiederholbar.

`tools/inbox/submission_contract.py` gegen tatsächliches PostgreSQL bestanden: parallele Einreichung ergibt genau einen Fall/Job, geänderte Eingaben unter demselben Schlüssel werden abgewiesen, neun manipulierte direkte Modelle scheitern an Validierung, geschlossene Veröffentlichung verweigert neue Eingänge. Eine echte zusätzliche Audit-Constraint erzwingt einen Speicherfehler nach Fall-/Job-Schreibvorgängen; keine Teilobjekte oder Receipts bleiben bestehen. Nach Entfernen der Constraint gelingt derselbe Befehl. Das Werkzeug entfernt seine synthetischen Daten und die Constraint. Kein Twenty- oder Mailadapter wird beim Eingang aufgerufen.

Ruff/Mypy, 27 Architektur-/Registrierungstests (neun bekannte Pydantic-Warnungen), no-test-doubles und Diffprüfung bestanden. Der laufende Compose-Gate prüft noch das zuvor gebaute Schema-Image; der neue Eingangsvertrag ist dort noch nicht verdrahtet. HTTP-Route und öffentliche Missbrauchsschutzmechanismen, registrierter Kontakt-Worker, Fallbearbeitung und Oberflächen bleiben offen; dieser Slice ist keine Freigabe einer öffentlichen Inbox.

## M3 — Autorisierte interne Fallbearbeitung

Direkte Inbox-Operationen erlauben begrenzte Suche, Lesen sowie revisionierte Zuständigkeit und Statusänderung. Aktuelle aktive System-Administration verwaltet alle Fälle; aktive Charity-Administration nur Fälle ihrer Aktion. Andere Personen sehen ausschließlich ausdrücklich zugewiesene Fälle, bei Aktionsbezug zusätzlich mit aktueller Aktionsmitgliedschaft. Eine gewöhnliche Aktionsmitgliedschaft oder ein behauptetes Principal-Rollenattribut genügt nicht. Nur Verwaltung ändert Zuständigkeiten; Kandidaten müssen aktiv und für die Aktion berechtigt sein. Allgemeine Fälle können durch System-Administration gezielt an aktive Personen delegiert werden.

Eingangsfelder und Aktionsbezug sind über die Änderungsoperation unveränderlich. Abschluss verlangt eine Notiz; Wiederöffnung entfernt den aktuellen Abschluss, erhält ihn aber im Audit. Falländerungen verändern die separate Kontaktrevision nicht. Receipts enthalten nur Fall-ID und die für Zuweisungs-Replay nötige Berechtigungsanforderung. Aktuelle Rechte werden auch bei Wiederholung geprüft; Verlust der Verwaltung sperrt Zuweisungs-Replay selbst bei erhaltenem Lesezugriff.

`tools/inbox/case_contract.py` mit echtem PostgreSQL bestanden: fünf Identitäten mit absichtlich behaupteten Admin-Rollen, zwei Aktionen und allgemeiner Fall; isolierte Suche, Zuweisung, Abschluss/Wiederöffnung, erhaltene Abschlussnotiz, genau ein Konflikt bei zwei parallelen Änderungen, unveränderter Eingang, unabhängiger CRM-Fehlerzustand, Mitgliedschaftsablauf, Rollenentzug, unberechtigte Kandidaten und Kontosperre. Eingangsvertrag erneut bestanden. 27 Architektur-/Registrierungstests (neun bekannte Pydantic-Warnungen), Ruff/Mypy und no-test-doubles bestanden. Öffentliche Schutzmechanismen, HTTP-/UI-Anbindung, Kommentare/Referenzoperationen und CRM-Worker bleiben offen. Der laufende Compose-Gate verwendet weiterhin das frühere Schema-Image; die beiden neuen direkten Verträge müssen nach seinem Abschluss in den Runner aufgenommen werden.

## M3 — Interne Inbox-HTTP-Anbindung

Das Modul registriert drei interne FastAPI-Routen zum Auflisten, Lesen und Ändern von Fällen. Der Produktions-Lifespan verdrahtet denselben Service wie direkte Modulaufrufe; bestehende Sitzungsauthentifizierung, CSRF-Middleware und Fehlerübersetzung bleiben maßgeblich. Erfolgreiche Antworten sind `no-store`. Interne Create-/Job-Korrelationen verlassen das Repository nicht. OpenAPI und TypeScript-Client wurden regeneriert. Öffentliche Einreichung ist noch nicht als HTTP-Endpunkt vorhanden; Navigation und UI folgen separat.

`tools/inbox/http_contract.py` mit Produktions-FastAPI-Lifespan und echtem PostgreSQL bestanden: anonym 401, fremder Fall 404 und leere Suche, Sitzung/CSRF, camelCase, unveränderlicher Eingang, strikte JSON-/Query-Grenzen, Abschluss/Replay/409, Entzug globaler Rechte und gesperrte Sitzung. 487 Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff/Format/Mypy, API-Client-Typecheck und no-test-doubles bestanden. Der separat laufende Compose-Gate hat den Leeraufbau samt bisherigen Modulverträgen bestanden und prüft noch den Legacy-Upgrade; die drei neuen Inbox-Service-/HTTP-Verträge werden nach dessen Ende in seinen Runner aufgenommen.

## Integration — Schema-Gate mit Altbestand bestanden

`sh tools/schema/test.sh .` auf dem bei `7fc66b0` gebauten Image bestand vollständig: Leeraufbau bis 0041, generischer Smoke, Task-/Wissens-/Material-/Inbox-Schema, alle eingebundenen Material-/Wissens-/Task-Service-/HTTP-/Berechtigungsverträge einschließlich Upload-Bereinigung, danach Migration von 0011 mit `tests/fixtures/schema/v0.sql` bis 0041 und Legacy-Smoke. Terminaler Exitcode 0; Projekt `leonaid-poc021-test-2137972478-71308` meldete die Entfernung seiner eigenen Ressourcen. Die Task-Pagination mit vorhandenem Bestand ist damit auch im Gesamt-Gate bestätigt.

Nach Abschluss wurden die drei neuen Inbox-Verträge (Einreichung, Fallbearbeitung, HTTP) in denselben Runner aufgenommen. Sie waren einzeln auf echtem PostgreSQL erfolgreich, sind aber nicht rückwirkend Teil des oben bestandenen Image-Laufs.

Bei Vorbereitung des CRM-Workers wurde die Eingangsvalidierung an den bereits vorhandenen `PersonData`-Vertrag angebunden: Telefonnummern müssen international angegeben sein. Die eigene schwächere Regex entfällt; formatierte internationale Eingaben bleiben als Eingangssnapshot erhalten, der CRM-Vertrag übernimmt die Normalisierung bei Verwendung. Der dauerhafte Eingangsvertrag verweigert jetzt zusätzlich eine nationale Nummer ohne Vorwahl und besteht erneut. Mypy, Ruff und Shell-Syntax bestanden. CRM-Verarbeitung bleibt offen.

## Integration — Navigationserwartung im Identity-Vertrag

Remote-CI auf `a9e2d5`: `E2E leaf / identity` scheiterte an „Akquisiteur-Navigation enthält falsche Bereiche“ (`103744057354`). Der bestehende Vertrag erwartete noch ausschließlich Survey-/Akquisebereiche und nach Rollenentzug nur die PWA-Übersicht. Tasks, Wissen und Materialien sind inzwischen für aktive Konten auch ohne Aktionsrolle verfügbar; ihre eigenen Datenberechtigungen bleiben maßgeblich. Die expliziten Mengenprüfungen berücksichtigen jetzt diese drei Module, ohne privilegierte Bereiche freizugeben. Der ebenfalls rote `E2E / invoices`-Job (`103745209589`) enthält nur die aggregierte Prüfung `RESULT=failure`, keinen separaten Invoice-Testfehler.

Korrigierte Mengen mit tatsächlicher PostgreSQL-Sitzung, `IdentityQueryService`, Modulregistrierung und dem HTTP-Antwortmodell vor/nach Entzug einer Acquirer-Mitgliedschaft geprüft. Privilegierte Bereiche bleiben ausgeschlossen. Ruff/Mypy und Diffprüfung bestanden. Der komplette Identity-Browser-Gate muss im folgenden CI-Lauf erneut bestehen; dieser Nachweis ersetzt ihn nicht. Alle Survey-Gruppen sowie Golden Journey, Lint/Types, Unit, Build und Schema-/Outbox-Integration waren im abgefragten Remote-Lauf erfolgreich; die gesamte CI-Abnahme bleibt wegen der E2E-Gruppe offen.

## M3 — Kontakt-Worker mit echtem Twenty-Recovery

Der bestehende Worker registriert `inbox.contact_link.v1` und verwendet den vorhandenen semantischen CRM-Port. Queue-Backoff übernimmt Wiederholungen; Laufzeitbegrenzung und Claim-Prüfungen schützen die lokale Verarbeitung. Der Twenty-Client wird beim Worker-Ende geschlossen. Compose ergänzt nur die vorhandene Twenty-Konfiguration am Worker, keine weiteren Dienste oder Netzwerke.

Vor einem Create wird die Absicht dauerhaft gespeichert. Wiederaufnahme liest zuerst die reservierte exakte Twenty-ID und prüft den Kontakt gegen den Eingangssnapshot. Ein belegter Treffer wird verknüpft; fehlender Nachweis nach begonnener Anlage oder abweichende Daten führen zu `needs_review`, ohne blindes zweites Create oder Überschreiben. Kontaktänderungen besitzen eine eigene Revision und verändern die Fallrevision nicht. Nur eine explizite HTTP-4xx-Ablehnung des Create ohne unklaren Ausgang erlaubt das Zurücksetzen der Absicht; ein Fehler beim Parsen einer Erfolgsantwort genügt dafür nicht.

`sh tools/twenty/gateway_test.sh .` im isolierten Projekt `leonaid-poc031-test-2137972478-78448` vollständig mit Exitcode 0 bestanden: bestehendes echtes CRUD/Batch/Pagination-Gate, tatsächlich gestopptes Twenty, bestätigter und weiterhin bearbeitbarer Inbox-Fall, Wiederanlauf und genau ein Kontakt. Ein transparenter TCP-Proxy leitete die tatsächliche erfolgreiche Twenty-POST-Antwort nicht zurück: Der Gateway-Timeout ließ eine dauerhafte Absicht zurück; Wiederholung fand die exakte ID und erzeugte keinen zweiten Kontakt. Weitere reale Prüfungen: vorhandener externer Commit, fehlender Kontakt bei begonnener Anlage, abweichender Kontakt ohne Überschreiben sowie veralteter Claim und erfolgreicher Ersatz-Worker. Container-, Volume- und Netzwerkabfragen mit exakt diesem Projektlabel waren nach Abschluss leer.

Zwei frühere Läufe scheiterten terminal: zunächst fehlte Mail-Konfiguration beim Aufbau des Produktionsworkers im Testcontainer; danach scheiterte der Timeout-Nachweis vor bestätigtem POST-Erfolg. Der Runner liefert nun synthetische Worker-Konfiguration; der Proxy erhält den tatsächlichen Upstream-Host und Szenarien eigene E-Mail-Adressen. Erst der oben genannte vollständig erfolgreiche Lauf ist der Recovery-Nachweis. Ruff, Formatprüfung und Mypy der sieben betroffenen Python-Worker-/Vertragsdateien bestanden. Manuelle Kontaktauflösung, öffentliche Oberflächen und interne Inbox-UI bleiben offen.

Der separate Schema-Lauf `leonaid-poc021-test-2137972478-74355` auf dem bei `a9e2d5` gebauten Image endete ebenfalls mit Exitcode 0: Leeraufbau bis 0041, eingebundene Inbox-Eingangs-/Fall-/HTTP-Verträge und bestehende Modulverträge sowie Upgrade von 0011 mit Altbestandsfixture und Legacy-Smoke. Der erst anschließend ergänzte öffentliche Inbox-Vertrag und der Kontakt-Worker sind nicht Teil dieses Schema-Image-Nachweises.

## M3 — Öffentlicher HTTP-Eingang mit dauerhaftem Missbrauchsschutz

Nach dem Worker-Slice `54f4d20` stellt FastAPI `POST /api/v1/public/inbox-cases` bereit. Die Route verwendet dieselbe atomare Fachoperation und bestätigt ausschließlich die Referenz mit `no-store`; es wird keine E-Mail erzeugt. Bestehende Origin-Prüfung und PostgreSQL-Rate-Limits werden wiederverwendet: fünf Versuche je Adresse in zehn Minuten, unabhängig von Cookie, User-Agent oder untrusted Forwarded-Header. Die Slash-Variante nutzt dieselbe Quote ohne Redirect und zusätzlichen Quotenverbrauch. Der Body ist auch beim Streaming auf 64 KiB begrenzt. OpenAPI und TypeScript-Client enthalten die neue Operation.

`PYTHONPATH=src python tools/inbox/public_contract.py` gegen das bestehende isolierte PostgreSQL und den Produktions-FastAPI-Lifespan bestanden: Referenzantwort, identisches Replay, ungültige E-Mail, geänderte Eingabe unter bestehendem Schlüssel, nicht vorhandene Aktion, verweigerte fremde Origin, keine öffentliche Fallabfrage, konkurrierende Requests an der Quotengrenze, fortbestehende Quote nach App-Neustart und tatsächlich gestreamter zu großer Body. Genau drei bestätigte Eingänge besitzen jeweils Receipt und Kontaktauftrag; eigene synthetische Daten werden entfernt. Der Vertrag ist im vorhandenen Schema-Runner verdrahtet, dessen neuer vollständiger Compose-Lauf noch aussteht. Ruff/Mypy und OpenAPI-Frischeprüfung bestanden. Public-/Campaign-Formulare, interne Inbox-Oberflächen und manuelle Kontaktklärung bleiben offen.

## M3 — Berechtigte Zuständige suchen

`InboxService.list_assignees` und `GET /api/v1/inbox-cases/{case_id}/assignees` liefern begrenzte Namenssuche mit stabiler Pagination, ausschließlich Benutzer-ID und Anzeigename. Nur aktuelle Fallverwaltung darf Konten suchen; reine Zuweisung genügt nicht. Die SQL-Regel wird auch beim Speichern einer Zuständigkeit verwendet: aktive Konten, bei Aktionsfällen aktuelle Mitgliedschaft oder Systemadministration. Direkte Aufrufe revalidieren Query-Modelle. Der TypeScript-Client wurde regeneriert; UI-Bedienung folgt separat.

Erweiterte bestehende `tools/inbox/case_contract.py` und `tools/inbox/http_contract.py` gegen echtes isoliertes PostgreSQL erfolgreich: fünf Konten, allgemeiner Fall und zwei Aktionen, Pagination, wörtliche Suche, unberechtigte Kandidatensuche, Kontosperre, Mitgliedschaftsablauf und Verwaltungsentzug. Produktions-FastAPI prüft 401/404, `no-store`, Antwortfelder und HTTP-Eingabegrenzen. Die erweiterten Dateien wurden erst nach Abschluss ihrer jeweiligen alten Testprozesse in den laufenden Schema-Runner übernommen; sie sind nicht rückwirkend Teil seines bei `20e4a96` gebauten Images.

487 Python-Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff/Format/Mypy, API-Client-Typecheck, OpenAPI-Frischeprüfung und no-test-doubles bestanden. Der gesamte lokale Frontend-Typecheck scheiterte an automatisch aus einem übergeordneten `node_modules` einbezogenen `@types/mdx`-Deklarationen mit fehlendem globalem JSX-Namespace. Der betroffene UI-Typecheck besteht mit `--typeRoots ./node_modules/@types`; keine Projektdatei oder externe Typdeklaration wurde dafür geändert. Remote-CI auf `20e4a96`: Build, Unit, Lint and types, Dependency pins und API contract erfolgreich; übrige Integrationsgates laufen noch. Diese Ergebnisse ersetzen nicht die CI auf dem neuen Commit oder die ausstehende Inbox-UI-Abnahme.

## Integration — Gemeinsame Testinstallation und Recovery-Archiv

Schema-Lauf `leonaid-poc021-test-2137972478-80429` scheiterte terminal im öffentlichen Inbox-Vertrag beim Produktions-Lifespan, nachdem Schema, Eingangsoperation, Fallbearbeitung und interner HTTP-Vertrag bestanden waren. Der öffentliche Vertrag setzte zufällige Installationsschlüssel; das vom vorherigen HTTP-Vertrag erhaltene Recovery-Archiv war mit dessen festen synthetischen Schlüsseln signiert. Mit einem tatsächlichen temporären Archiv und echtem PostgreSQL ist die Reihenfolge interner HTTP-Vertrag → öffentlicher Vertrag als `survey_erasure_archive_unavailable` reproduziert. Der öffentliche Vertrag allein bestand auch im gebauten Container-Image ohne das gemeinsame Archiv.

Der öffentliche Vertrag verwendet jetzt dieselben synthetischen Installationsschlüssel wie die übrigen HTTP-Verträge. Beide Verträge einschließlich App-Neustart bestehen danach nacheinander mit erhaltenem Archiv; die Produktionsprüfung wird unverändert ausgeführt. Ruff/Mypy bestanden. Der vollständige Schema-/Altbestands-Gate muss erneut laufen; der vorherige fehlgeschlagene Lauf zählt nicht als Gesamtnachweis.

## M3 — Interne Fallkommentare

Inbox bietet `add_comment` und `list_comments` sowie zwei interne HTTP-Routen. Aktuelle Fallrechte gelten auch für Kommentar-Replay; Klartext ist auf 4000 Zeichen begrenzt und wird bei direkten Aufrufen revalidiert. Die Liste zeigt neueste Einträge zuerst mit begrenzter Pagination. Kommentar, Audit und Receipt werden gemeinsam geschrieben. Audit und Receipt enthalten nur die Kommentar-ID; weder Fallstatus/-revision noch Kontaktstatus/-revision ändern sich. Die öffentliche Referenz eröffnet keinen Kommentarzugriff. Es entstehen keine Mail- oder Mention-Jobs.

Erweiterte bestehende Fall-/HTTP-Verträge gegen echtes PostgreSQL und den Produktions-FastAPI-Lifespan bestanden: paralleles identisches Absenden, geänderte Eingabe unter demselben Schlüssel, ungültige direkte Modelle, Pagination, fremder Zugriff und Lesen/Replay nach Rechteentzug. Eine tatsächliche zusätzliche Audit-Constraint löst einen Speicherfehler aus; weder Kommentar noch Receipt bleiben zurück, und derselbe Befehl gelingt nach Entfernen der Constraint. HTTP prüft Sitzung, CSRF, `no-store`, Autorzuordnung, Validierung und fehlende öffentliche Kommentarroute. Die Vertragsdateien werden erst nach dem jeweiligen alten Prozess im laufenden Schema-Gate ersetzt; Kommentare sind nicht Teil seines bei `5f6288e` gebauten Images.

487 Python-Unit-Tests mit neun bekannten Pydantic-Warnungen, Ruff/Format/Mypy, API-Client-Typecheck, OpenAPI-Frischeprüfung und no-test-doubles bestanden. Die generierten Operationen sind verfügbar; Kommentaroberfläche, Task-/Materialreferenzen und manuelle CRM-Klärung bleiben offen.

## Integration — Explizite Proxy-Konfiguration im öffentlichen Vertrag

Schema-Lauf `leonaid-poc021-test-2137972478-82474` endete erneut mit Exitcode 1 im öffentlichen Inbox-Vertrag. Der App-Start mit gemeinsamem Recovery-Archiv gelang diesmal; die übrigen Inbox-Verträge einschließlich Zuständigkeitsauswahl bestanden. Der öffentliche Vertrag übernahm jedoch `LEONAID_TRUST_PROXY_HEADERS=true` aus Compose, obwohl sein manipulierter Forwarded-Header-Test direkte Clients voraussetzte. Gezielt mit dieser Umgebungsvariable auf echtem PostgreSQL reproduziert: beide konkurrierenden Requests erhielten 201 statt eines erwarteten 429, weil der manipulierte Header als andere Adresse eingeordnet wurde.

Der Vertrag konfiguriert nun beide unterstützten Betriebsarten explizit und prüft sie nacheinander: direkte Clients mit ignorierten Forwarded-Headern sowie Proxy-Betrieb mit einer vom Proxy zuletzt angehängten maßgeblichen Adresse. Cookie, User-Agent, untrusted Kettenpräfix und Slash-Variante ändern die jeweilige Quote nicht. Beide vollständigen Durchläufe einschließlich Neustart bestehen auf echtem PostgreSQL auch bei aktivierter Umgebungsvariable. Produktionscode bleibt unverändert; Ruff/Format/Mypy bestanden. Der vollständige Schema-/Altbestands-Gate bleibt bis zum erneuten erfolgreichen Abschluss offen.

## M3 — Task-Verweise mit unabhängigen Fachrechten

Inbox kann bestehende Tasks verknüpfen, lösen und aktuell auflösen. Bootstrap bindet dafür dieselbe transaktionsgebundene Task-Fachoperation wie beim Wissensmodul ein. Inbox speichert ausschließlich den Verweis; Titel, Status und übrige Task-Daten kommen beim Lesen aus der autorisierten Task-Operation. Fehlende Task-Rechte ergeben einen Verweis mit `task: null`, ohne Task-Inhalt. Fallbearbeitende können einen solchen Verweis entfernen, ohne den Task zu verändern. Hinzufügen und dessen Replay verlangen aktuelle Task-Leserechte. Fallrechte werden bei jedem Zugriff geprüft.

Änderungen verwenden die Fallrevision und gemeinsame Transaktion für Referenz, Revision, Receipt und Audit; die Kontaktrevision bleibt unverändert. Gleiche bestehende Zuordnung unter einem neuen Schlüssel erzeugt keine weitere Revision. Höchstens 100 Tasks werden pro Fall verknüpft. HTTP-Routen und generierter TypeScript-Client sind enthalten.

`tools/inbox/task_contract.py` auf echtem PostgreSQL mit Ein-Verbindungs-Pool bestanden: zusammengesetzte Operation ohne zusätzliche Pool-Verbindung, paralleles Replay, laufende Task-Statusänderung, unabhängige Rechte, Freigabe/Entzug, Verweigerung von Replay nach Quellenentzug, Entfernen ohne Task-Änderung, veraltete Fallrevision und 100-Verweise-Grenze. Eine echte zusätzliche Audit-Constraint beweist Rollback von Referenz, Fallrevision und Receipt; derselbe Befehl gelingt danach über Produktions-FastAPI. HTTP prüft Sitzung, CSRF, `no-store`, strikte Eingaben sowie verweigertes Lesen/Replay nach Fallrechteentzug.

487 Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff/Format/Mypy, API-Client-Typecheck, OpenAPI-Generierung und no-test-doubles bestanden. Der neue Vertrag ist für den nächsten Schema-Lauf im bestehenden Runner ergänzt. Die laufende Schleife im bei `e2fc948` gebauten Schema-Gate hatte ihre ursprüngliche Vertragsliste bereits begonnen; Task-Verweise sind nicht Bestandteil dieses Image-Nachweises. Materialverweise, Inbox-Oberfläche und manuelle CRM-Klärung bleiben offen.

## Integration — Laufende Runner-Datei nicht verändern

Im Schema-Lauf `leonaid-poc021-test-2137972478-84344` bestanden alle bisherigen Inbox-Verträge, einschließlich Kommentare und beider öffentlicher Proxy-Betriebsarten. Anschließend meldete die Shell einen Syntaxfehler bei `done`: Die während des laufenden Prozesses verlängerte Vertragsliste veränderte die bereits geöffnete Runner-Datei. Die aktuelle Datei besteht `sh -n`; der Fehler betrifft die laufende Ausführung. Trotz Exitcode 0 und Cleanup-Erfolgsmeldung ist der Gesamtlauf wegen dieses eindeutigen Fehlers nicht bestanden. Künftige lokale Läufe starten aus einer unveränderten Kopie der Runner-Datei; neue Verträge zählen erst im dazu passenden Image-Lauf. Der gesamte Schema-/Altbestands-Gate wird erneut ausgeführt.

## M3 — Materialverweise auf feste Dateiversionen

Inbox speichert Material-ID und feste Version; Metadaten werden über die vorhandene Material-Fachoperation mit aktuellen Rechten aufgelöst. Ohne Materialrechte bleibt ein inhaltsloser Verweis. Ein neuer Upload verschiebt bestehende Verweise nicht. Hinzufügen verlangt auch beim Replay aktuelle Materialrechte; Entfernen eines unzugänglichen Verweises verändert die Datei nicht. Referenz, Fallrevision, Receipt und Audit teilen eine Transaktion. Die Kontaktrevision bleibt unverändert; pro Fall sind höchstens 100 Dateiverweise möglich.

Das vorhandene Material-Repository kann nun Metadaten ohne Objektspeicher-Zugangsdaten lesen. Die bisherigen Dateioperationen greifen weiterhin auf einen erforderlichen Storage-Port zu; ohne Konfiguration liefern sie `material_storage_unavailable`. Bootstrap bindet den transaktionsgebundenen Metadatenaufruf ein. Kein zusätzlicher Dienst, keine Dateikopie und kein alternativer Material-Datenbestand. HTTP-Routen und generierter Client sind enthalten.

`tools/inbox/material_contract.py` gegen echtes PostgreSQL und einen isolierten RustFS-Container bestanden: Ein-Verbindungs-Pool, paralleles Replay, zwei Fälle mit einer Datei, neue Dateiversion bei unverändertem Verweis, tatsächlicher Download alter/neuer Bytes, unabhängige Freigabe und Entzug, inhaltslose nicht zugängliche Verweise, verweigertes Quellen-Replay und Entfernen ohne Löschen der Datei. Eine tatsächliche Audit-Constraint beweist atomaren Rollback samt Fallrevision und Receipt; Wiederholung gelingt über Produktions-FastAPI. 101 tatsächlich gespeicherte Dateiversionen prüfen die Verweisgrenze. HTTP prüft Sitzung/CSRF, strikte positive Bigint-Versionen, `no-store` und Fallrechteentzug. Der Download ohne konfigurierten Storage-Port wird explizit abgewiesen.

Bestehende `tools/materials/http_contract.py` und `tools/knowledge/material_contract.py` mit echtem RustFS ebenfalls erfolgreich: Multipart, versionierte Bytes, Downloadheader, Größenlimit, Wissensverweise und unabhängige Dateilebensdauer. 487 Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff/Format/Mypy, API-Client-Typecheck und no-test-doubles bestanden. Der neue Vertrag wird im nächsten Schema-Lauf nach dem Start von RustFS ausgeführt; der bereits laufende immutable Runner verwendet weiterhin seinen vorherigen Image-Stand. Inbox-Bedienoberfläche und manuelle Kontaktklärung bleiben offen.

## Integration — Vollständiger Schema-Lauf mit Inbox-Taskverweisen

Der unveränderte Runner `/tmp/leonaid-schema-a392607.sh` im isolierten Projekt `leonaid-poc021-test-2137972478-86129` endete mit Exitcode 0. Das vollständige Log bestätigt Leeraufbau, Vorgänger-Upgrade, Constraints und Datenhalt sowie den abschließenden Schema-Vertrag. Alle projektgebundenen Testressourcen wurden entfernt. Die zuvor beobachteten öffentlichen Inbox-Fehler und der Fehler durch Änderung einer laufenden Runner-Datei traten nicht mehr auf.

Dieser Nachweis gilt für das bei `a392607` gebaute Image einschließlich Inbox-Kommentaren, beider Proxy-Betriebsarten und Taskverweisen. Die später hinzugefügten Inbox-Materialverweise und die derzeit entstehende manuelle Kontaktbestätigung sind nicht durch diesen Gesamtlauf abgedeckt; ihre eigenen Integrationsnachweise und ein abschließender aktueller Gesamtstand bleiben erforderlich.

## M3 — Manuelle Kontaktklärung über bestehende Fach- und Queue-APIs

Fallverwaltende können mit `list_contact_candidates` bestehende Twenty-Personen suchen und eine Auswahl mit `confirm_contact` ausdrücklich bestätigen. Die Suche verwendet standardmäßig die Namen des unveränderlichen Eingangs; abweichende Namen können angegeben werden. Die Bestätigung enthält Person-ID, Fingerprint des gelesenen Twenty-Datenstands, erwartete Kontaktrevision, Begründung und Idempotenzschlüssel. Vor dem Speichern liest der Dienst den Kontakt erneut und prüft aktuelle Verwaltungsrechte. Er legt keinen CRM-Kontakt an und überschreibt keine Stammdaten.

Die lokale Transaktion sperrt zuerst den Outbox-Auftrag und dann den Fall, entsprechend der Worker-Sperrreihenfolge. Nur ungelöste Zuordnungen mit ruhendem Auftrag können bestätigt werden. Kontaktzuordnung, Abschluss des offenen Auftrags, Audit und Receipt werden gemeinsam gespeichert; Fallstatus und Fallrevision bleiben unverändert. Kontaktrevision und aktueller Datenstand schützen vor veralteter Auswahl. Bootstrap verwendet denselben Twenty-Gateway wie die übrige Anwendung; es entsteht kein zusätzlicher Dienst.

HTTP und generierter Client enthalten Kandidatensuche und Bestätigung. Der erweiterte Produktions-FastAPI-Vertrag auf echtem PostgreSQL besteht: Sitzung, fremder Zugriff, CSRF, leere/zu lange Suchnamen, ungültige Bestätigung und tatsächlicher fehlgeschlagener Twenty-Verbindungsaufbau. CRM-Ausfall ergibt eine sichere 503-Antwort. Der Test deckte fehlendes `no-store` bei Inbox-Fehlerantworten auf; der gemeinsame Fehlerhandler schützt nun auch diese Antworten. 487 Unit-Tests (neun bekannte Pydantic-Warnungen), Ruff, Mypy, OpenAPI-Frischeprüfung, Client-Typecheck und no-test-doubles bestanden.

Der vollständige Twenty-Vertrag im isolierten Projekt `leonaid-poc031-test-2137972478-91104` besteht einschließlich tatsächlicher manueller Auswahl eines abweichenden Kontakts, konkurrierender Wiederholung, Rechteentzug und Audit-Constraint-Rollback. Bestehende CRUD-/Pagination-, Ausfall-/Wiederanlauf-, verlorene-Antwort- und Worker-Fencing-Prüfungen sind ebenfalls bestanden. Der HTTP-Ausfallvertrag wurde zusätzlich mit aktuellem Source-Stand ausgeführt; die tatsächliche erfolgreiche Bestätigung über HTTP und die Inbox-Oberfläche bleiben als folgende Integrationsschritte offen.

## M3 — Aktuelle Rechteauskunft für die Inbox-Oberfläche

`get_permissions` und `GET /api/v1/inbox-cases/{case_id}/permissions` liefern `canManage` für einen aktuell lesbaren Fall. Die Abfrage verwendet dieselbe `_MANAGE`-Regel wie die schreibenden Verwaltungsoperationen. Alle leseberechtigten Fallbearbeitenden können weiterhin Status, Kommentare und Referenzen bearbeiten; nur Fallverwaltende dürfen Zuständigkeit und Kontaktklärung verwalten. Die Auskunft erweitert keine Rechte und ersetzt keine Schreibprüfung.

Die bestehende PostgreSQL-Fallmatrix prüft globale Verwaltung, aktuelle Aktionsverwaltung, zugewiesene Bearbeitende ohne Verwaltungsrecht, fremde Fälle und den Entzug einer Aktionsmitgliedschaft. Der Produktions-FastAPI-Vertrag prüft Sitzung, fremden Zugriff, Ergebnis und `no-store`. Beide Verträge bestanden. Generierter Client, Ruff und Mypy sind aktualisiert/geprüft; die tatsächliche Nutzung folgt in der gemeinsamen Inbox-Oberfläche.

## M3 — Kontaktbestätigung über HTTP und konkurrierenden Worker

Der erweiterte Twenty-Vertrag `leonaid-poc031-test-2137972478-95891` endete mit Exitcode 0; alle eigenen Ressourcen wurden entfernt. Produktions-FastAPI liefert die echte Kandidatenvorschau und bestätigt die Zuordnung mit 200/no-store, gleichzeitig mit einem direkten Fachaufruf desselben Befehls. Es bleiben genau ein Auditabschluss, ein abgeschlossener Queue-Auftrag und eine erhöhte Kontaktrevision bei unveränderter Fallrevision.

Eine tatsächliche Twenty-Änderung nach der Vorschau invalidiert den Fingerprint. Ein über die vorhandene Queue erneut gestarteter und beanspruchter Auftrag verhindert manuelles Überholen. Der übrige reale Nachweis umfasst Audit-Constraint-Rollback, Rechteentzug, CRUD/Pagination, Ausfall/Wiederanlauf, verlorene Create-Antwort und Claim-Fencing.

Der erste HTTP-Lauf `leonaid-poc031-test-2137972478-93527` scheiterte beim Produktions-Lifespan am geerbten Recovery-Archiv vor Aufruf der Inbox-Route. Der Vertrag verwendet nun ein eigenes temporäres beschreibbares Archiv und führt dessen echte Veröffentlichung weiterhin aus; die Schutzprüfung wurde nicht deaktiviert. Mypy/Ruff bestanden. Die neue Inbox-Oberfläche und der laufende Browserstack sind nicht Bestandteil dieses Nachweises.


## Integration — Modul-Direktlinks im Produktions-Webserver

Der tatsächliche Compose-/Chrome-Lauf zeigte einen bisher durch die temporären Browser-Harnesses nicht erfassten Fehler: `static-server.mjs` lieferte für neue Modulrouten seine alte Ersatzoberfläche. Die SPA-Registrierung wurde dadurch gar nicht erreicht. Web und PWA liefern jetzt für Anwendungsrouten den gebauten SPA-Einstieg; Asset- und Offline-Behandlung bleiben ausdrücklich erhalten. Neue Module benötigen keine zweite Routenliste im Transport.

Beide Docker-Produktionsbuilds und `tools/testing/spa_routes.mjs https://localhost:18843` bestanden im eigenen Projekt `leonaid-shared-32c62f415463ad67`: Tasks/Wissen/Materialien/Inbox mit Listen- und Detailpfaden, unbekannter Pfad zum clientseitigen Routing, tatsächliche JS-/CSS-Antworten, no-store HTML und PWA-Offline-Dokument. Ein erster Aufruf während des noch laufenden Containerstarts lieferte 502; nach bestätigtem Healthy-Zustand bestand der vollständige Vertrag.

Chrome öffnete nach dem vom Nutzer ausdrücklich angeforderten macOS-Import der lokalen Caddy-Root-CA die HTTPS-Seite ohne Zertifikatswarnung. Mit einer echten synthetischen Sitzung zeigte Web die gespeicherte Aufgabenliste und die mobile PWA dieselbe Liste samt Aufgabe bei 390 px ohne horizontalen Seitenüberlauf. Screenshots: `/tmp/leonaid-module-routing-desktop.png` und `/tmp/leonaid-module-routing-mobile.png`. Die Testanmeldung setzte die zuvor tatsächlich in PostgreSQL angelegte Sitzung als Cookie; keine HTTP-Antworten oder Inhalte wurden ersetzt. Der Browser lief mit dem aktuellen Arbeitsbaum einschließlich noch nicht abgenommener Inbox-Navigation. Diese Bilder belegen die Produktions-Routenauslieferung, nicht die vollständige Inbox-Bedienabnahme.

Die Inbox-Oberfläche, öffentliche Formulare und übrigen offenen Gesamtgates bleiben offen. Zertifikat, Schlüssel, Sitzungen und Testdaten werden nicht committed.


## M3 — Gemeinsame Inbox-Oberfläche und kompakte Aktionen

Gemeinsame verzögert geladene Inbox-Liste/Fallbearbeitung für Web und PWA mit aktuellen Verwaltungsrechten, Status, Abschlussnotiz, internen Notizen, Twenty-Kontaktklärung sowie Task-/Materialverweisen. Der Materialpicker ist aus Wissen in die Materialfunktion verschoben und wird gemeinsam verwendet.

LIVE Chrome im eigenen Compose-Projekt `leonaid-shared-32c62f415463ad67`: neu → in Bearbeitung → abgeschlossen mit Notiz → wieder in Bearbeitung; interne Notiz speichern; echten Twenty-Kontakt suchen, auswählen und begründet zuordnen; Task verknüpfen/entfernen. Veraltete Revision erhält den Abschlussentwurf. Abgelehntes Neuladen erhält ihn; bestätigtes Neuladen verwirft ihn. Ein unverändertes, nicht speicherndes Formular übernimmt neue Fallrevisionen. Nach abgeschlossener eigener Referenzänderung funktioniert Speichern; während einer noch laufenden Referenzänderung begonnene Entwürfe behalten ihren Revisionsschutz.

Zweites zugewiesenes PWA-Konto: keine Zuständigkeitsverwaltung, interne Notiz speichern, verknüpfte Aufgabe in bestehender Task-Oberfläche erledigen und aktuellen Status im Fall lesen. Echte Sitzungen, FastAPI, PostgreSQL und Twenty; keine Antwort-Doubles. `tools/inbox/browser_seed.py` erzeugt synthetische Konten und einen absichtlich unklaren Kontaktauftrag im eigenen Stack bei angehaltenem Worker. Die private Sitzungsausgabe wird nicht committed.

Nutzerfeedback: 14-px-Labels, gemessene 36-px-Desktop-Buttons, 44 px bei tatsächlicher coarse-pointer-Emulation; neutrale Nebenaktionen und primäre Speicheraktionen. Führende dekorative Hugeicons bei erhaltenen Textlabels. Bei 390 px kein horizontaler Überlauf. Screenshots `/tmp/leonaid-inbox-compact-desktop.png` und `/tmp/leonaid-inbox-compact-mobile.png`; erste falsch skalierte mobile Aufnahme nach erneuter Viewport-Anwendung ersetzt. Unabhängiger Review: `ship` nur für Button-Überarbeitung/angrenzendes Layout. Dokumentationsprüfung bestätigt Erhalt des vorhandenen Systems ohne neue Design-Dateien. Detector einmal ausgeführt: keine Befunde.

Features-TypeScript, beide Produktionsbuilds, elf Modulregistrierungstests, 30 Identitäts-Unit-Tests, Ruff und no-test-doubles bestanden. Offen: Materialupload/-referenzen samt Wissenspicker-Regression, vollständige Rechte-/Konfliktmatrix, öffentliche Public-/Campaign-Formulare und Gesamtgates. Bereits vorhandene Material-Steuerelemente sind noch nicht durch diesen Browserlauf abgenommen.


## M3 — Gemeinsamer Materialpicker und unabhängige Referenzrechte

Der eigene laufende Produktionsstack `leonaid-shared-32c62f415463ad67` wurde erneut als gesund geprüft. Im frischen RustFS fehlte der Materialbucket; der erste echte HTTP-Upload lieferte deshalb 503. Der Browser-Fixture-Helper initialisiert jetzt vor dem Seed den vorhandenen privaten versionierten Bucket über `S3ObjectStorage.ensure_private_versioned_bucket`. Nach derselben Initialisierung bestand der Upload mit demselben Idempotenzschlüssel. Keine zweite Dateiablage oder Änderung der Produktberechtigungen.

Zwei synthetische Textversionen wurden über echte HTTPS-Multipart-Aufrufe angelegt. PWA-Inbox und Wissenseditor verwenden denselben Picker: Auswahl von Version 1 bei aktuellem Dateistand 2; Speichern; Web-Direktlink zeigt weiterhin Version 1. Der Wissensdownload wurde tatsächlich im Downloads-Verzeichnis gefunden und bytegenau mit der Ursprungsdatei verglichen. Die Browser-Download-Ereignisbeobachtung lief dabei in ein Timeout; sie ist keine Erfolgsquelle.

Die Inbox-Verwaltung ohne Materialfreigabe sieht nur „Material nicht verfügbar“. Explizite viewer-Freigabe über die echte Material-API zeigt Dateiname und Download-Button; HTTP-Download liefert exakt die alten Bytes. Nach Entzug liefert derselbe Download 404 und die noch offene Fallansicht blendet Dateiname/Download wieder aus. Verweis entfernen funktioniert weiterhin. Beide Dateiversionen bleiben bytegenau erhalten; der Wissensverweis bleibt bestehen. Die PWA verknüpft dieselbe Version anschließend erneut. Persistierte HTTP-Antworten bestätigen identische Material-ID/Version in Wissen und Inbox.

Bei 390 px zeigen die Materialaktionen keinen horizontalen Seitenüberlauf. Screenshots: `/tmp/leonaid-shared-material-knowledge.png`, `/tmp/leonaid-inbox-material-revoked.png`, `/tmp/leonaid-inbox-material-mobile.png`. Der erneute Inbox-Browserdownload erzeugte keinen zusätzlich nachgewiesenen lokalen Download und ist ausdrücklich nicht abgenommen; der HTTP-Byte-Nachweis ersetzt diesen Browserpunkt nicht. Der Dateiauswahldialog bleibt wegen fehlender Erweiterungsberechtigung offen. Öffentliche Formulare, vollständige Konflikt-/Rechtematrix und Gesamtgates bleiben offen.


## M3 — Öffentliches Anfrageformular auf der Club-Startseite

Öffentliches Inbox-Formular als gemeinsame Astro-Komponente für Public und Campaign vorbereitet. Die Club-Startseite verwendet keinen Aktionsbezug; aktive Aktionsseiten geben die Core-Aktions-ID mit. Archive/inaktive Seiten erhalten kein aktionsbezogenes Formular. Campaign- und Alias-Abnahme bleiben offen.

Der vorhandene generierte Client sendet direkt an die öffentliche Inbox-Route: keine zweite Server-Action, keine zusätzliche Queue, keine zusätzliche Abhängigkeit. Native Pflichtfelder und E-Mail/Telefon-Auswahl; Request-Limits/Autorisierung verbleiben in der vorhandenen API. Bei unklarem Ausgang bleiben Originalpayload und Idempotenzschlüssel auch über nachfolgende Quotenfehler erhalten. Nur eine definitive Ablehnung ohne vorherigen unklaren Ausgang entsperrt den Entwurf. Der vollständige Netzfehler-/Replay-Browservertrag ist noch offen.

Realer Public-Produktionsbuild im eigenen Compose-Stack, Chrome: fehlender Kontakt zeigt eine Meldung bei erhaltenen Eingaben; Desktop- und mobile Übermittlung erhalten Referenzen. PostgreSQL bestätigt für jede Referenz genau einen Fall und einen Auftrag inbox.contact_link.v1 mit Kontaktstatus pending bei angehaltenem Worker. Bestätigung zeigt keine Förderzusage und versendet keine E-Mail. 390 px ohne horizontalen Überlauf.

Public-Dockerbuild mit Typprüfung und Campaign-Astro-Typprüfung bestanden. Unabhängiger Review verlangte stärkere Eingaberänder, sichtbare Pflichtangaben und Kontakthinweis auch am E-Mail-Feld; umgesetzt mit bestehendem ink-muted-Token. Dokumentationsreview bestätigt bestehende Fonts/Farben/Abstände ohne neue Design-Dateien; lokale 6px-Radien bleiben ein komponentenlokales Detail. Abschlussreview: ship für die PublicInbox-Oberfläche und ihre Belege; alle ursprünglichen Reviewpunkte behoben. Ganzseitenaufnahme erzeugte ein Sprunglink-Artefakt und wurde durch zwei überlappende unveränderte mobile Viewport-Captures ersetzt. Campaign-/Alias- und vollständige Retry-Gates sind nicht Teil dieser Freigabe.

Screenshots: `/tmp/leonaid-public-inbox-desktop.png`, `/tmp/leonaid-public-inbox-mobile.png`, `/tmp/leonaid-public-inbox-mobile-bottom.png`, `/tmp/leonaid-public-inbox-success.png`.


## M3 — Aktionsanfragen unabhängig von Bestellungen

Die vorbereitete Einbindung verwendete irrtümlich `submissionsAllowed`, das bestehende Bestellformulare und deren Freigabe beschreibt. PublicAction und die nicht-Krapfentaxi-Campaign-Einbindung zeigen die Inbox nun bei `availability === "published"`; die bestehende Core-Publikationsprüfung und Inbox-Schreibprüfung bleiben maßgeblich. Archive erhalten keine neue aktionsbezogene Anfrage.

`tools/inbox/public_browser_seed.py` legt zwei isolierte synthetische Aktionen samt erforderlichem Begünstigten und Alias an: veröffentlicht ohne Bestellformular sowie abgelaufene Publikation. Der tatsächliche Repository-Helper wurde im eigenen API-Container erfolgreich ausgeführt. `tools/inbox/public_form_routes.py --base-url https://localhost:18843 --ca /tmp/leonaid-inbox-caddy-root.crt --fixture /tmp/leonaid-public-action-fresh-fixture.json` prüft echte HTML/API-Antworten. Die API bestätigt veröffentlichte Aktion bei `submissionsAllowed=false` und `orderForm=null`. Startseite und aktiver Alias enthalten genau ihr erwartetes Formular; Archiv und inaktiver Alias keines. Der Vertrag scheiterte vor der Korrektur am fehlenden aktiven Formular und bestand danach mit ursprünglichen und frisch erzeugten Fixtures. Ein erster unvollständiger temporärer Seed ohne Begünstigten führte zu 422/503 und wurde vervollständigt; der committed Helper enthält den Begünstigten.

Chrome öffnete den aktiven Alias ohne Bestellformular, sendete eine Anfrage und erhielt eine Referenz. PostgreSQL bestätigt genau einen Fall mit der richtigen Aktions-ID und einen Kontaktauftrag. Archiv und inaktiver Alias wurden separat im Browser geöffnet und enthalten jeweils null Inbox-Formulare. Screenshots: `/tmp/leonaid-inbox-action-form.png`, `/tmp/leonaid-inbox-action-success.png`, `/tmp/leonaid-inbox-action-inactive.png`.

Public-Docker-Produktionsbuild, Public-/Campaign-Astro-Typprüfung, Ruff und Formatierung bestanden. Campaign-/Weiterleitungs-Browserprüfung, öffentlicher Twenty-Ausfall-/Recovery-Ablauf und vollständige Retry-Prüfung bleiben offen. Dieser Slice ändert die Sichtbarkeitsbedingung; die zuvor geprüfte Formulargestaltung bleibt unverändert.


### CMS-Operator für die Campaign-Browserabnahme portabel ausführen

Der bestehende Storage-Operator scheiterte im lokalen macOS-Worktree am schreibgeschützt eingebundenen Host-`.venv`. Ein temporäres Linux-Venv mit `uv sync` war ebenfalls ungeeignet: `storage-data` ist absichtlich intern und erlaubt keinen Download von Python-Paketen. Der Operator baut deshalb dasselbe vorhandene Core-Dockerfile und verwendet dessen gesperrte Linux-Abhängigkeiten. Nur `tools/` wird schreibgeschützt eingebunden; kein Host-Venv überdeckt die Image-Abhängigkeiten. Die Netztrennung und dedizierten CMS-Zugangsdaten bleiben erhalten.

Im bestehenden isolierten Browserprojekt `leonaid-shared-32c62f415463ad67` bestanden Image-Build und echte RustFS-Provisionierung (`private bucket and scoped IAM user provisioned`). Das CMS wurde über seine echte Setup-Oberfläche durch den vorgesehenen synthetischen Core-Administrator eingerichtet; die bestehenden Campaign-Schema-/Binding-/Media-Installer liefen bei gestopptem CMS erfolgreich, anschließend wurde der CMS-Dienst wieder healthy. Öffentliche Campaign-Einreichung und Alias-Weiterleitung sind damit noch nicht abgenommen.


### Kanonische Campaign-Inbox im echten Browser

Die synthetische aktive Aktion wurde im nativen CMS als Entwurf angelegt und publiziert. Der interne CMS-Slug bleibt die feste Core-Aktions-ID. Beim ersten kanonischen Aufruf zeigte die Core-Validierung einen unvollständigen Testdatensatz: Es fehlte die verantwortliche Aktionsverwaltung. `public_browser_seed.py` legt diese nun als eigenes synthetisches aktives Konto mit Mitgliedschaft an. Ein frischer Seed und der erweiterte echte HTTP-Routenvertrag bestehen, einschließlich Core-Campaign-Auflösung unabhängig von einer Bestellfreigabe.

Auf `/campaigns/inbox-active-c4ee700b-2026/` wurde die Anfrage im Browser abgesendet. Die API lehnte zunächst die reservierte Testdomain `.invalid` mit 422 ab; der Entwurf blieb erhalten. Nach Korrektur auf `example.com` wurde Referenz `ae651cbe-6cfe-46b4-80b6-6805f64727ae` bestätigt. SQL zeigt genau einen Fall mit Aktion `c4ee700b-70b8-4ae6-8414-27b1bf7432b0`, Status `pending` und einem Kontaktauftrag. Der Worker bleibt angehalten; dies ersetzt den vollständigen Twenty-Ausfall-/Recovery-Browsergate nicht.

`public_form_routes.py --campaign` prüft zusätzlich echtes veröffentlichtes CMS-HTML und 308 vom slashlosen Pfad zur kanonischen Slash-URL. Startseite, Public-Alias, Archiv und inaktiver Alias sind weiterhin korrekt. Die separate Weiterleitung vom Public-Alias zur Campaign-URL bleibt offen. Screenshot: `/tmp/leonaid-inbox-campaign-success.png`, als PR-Kommentar angehängt.


### Campaign-Alias und tatsächlicher Twenty-Ausfall im Browser

Der primäre synthetische Alias `inbox-active-c4ee700b` wurde über den vorhandenen frisch authentifizierten System-Admin-Endpunkt auf Renderer `campaign` gesetzt. Der echte HTTP-Vertrag prüft mit `--campaign --campaign-alias` 302 für GET und HEAD; Chrome landet auf der veröffentlichten kanonischen Seite mit Anfrageformular. Auch die unveränderte Legacy-Variante wurde mit einem zweiten frischen Seed erneut geprüft.

Im ausschließlich eigenen Projekt `leonaid-shared-32c62f415463ad67` wurde Twenty tatsächlich gestoppt und der normale Worker gestartet. Chrome bestätigte die neue Anfrage mit Referenz `2de8431d-0ed6-4aea-9b0b-9f8868ca8eef`. Fall `9dad860f-0cf8-4a19-9609-0bbce9c53695` blieb trotz `crm_unavailable` bearbeitbar; Statusänderung auf `in_progress` wurde im Browser gespeichert, Revision 2. Nach fünf Versuchen lag der Kontaktauftrag in `dead_letter`.

Nach bestätigtem Twenty-Neustart wurde exakt Auftrag `4fb35a72-1a69-4e78-860e-129222c7f128` über den vorhandenen Admin-HTTP-Retry erneut freigegeben (`manualRetryCount=1`), ohne direkte Änderung der Jobdaten. Der normale Worker stellte die Kontaktzuordnung her. `tools/inbox/browser_receipt.py --linked` prüft echte PostgreSQL-/Twenty-Daten: genau ein Fall und Job zur Referenz, richtige Aktion, abgeschlossener Auftrag, exakte Kontaktkorrelation, ein Treffer für den synthetischen Namen und unveränderte Fallrevision/Status. Chrome zeigt danach „Kontakt zugeordnet“ und weiterhin „In Bearbeitung“. Der automatische Wiederanlauf vor Erreichen der Retry-Grenze und unklarer Browser-Netzausgang sind damit noch nicht abgenommen.

Screenshots im PR-Kommentar: öffentliche Bestätigung bei gestopptem Twenty, gespeicherte Fallbearbeitung während des Ausfalls und erfolgreiche Zuordnung nach Wiederholung. Keine E-Mail-Jobs entstanden laut Betriebsansicht; der allgemeine Nachweis der Versandfreiheit liegt weiterhin in den Eingangsverträgen.


### Öffentlicher Browser-Replay nach verlorenem HTTP-201-Erfolg

Die echte Campaign-Oberfläche sendete einen synthetischen Eingang an die Produktions-API. Im Browser wurde ausschließlich die Fetch-Antwort für `/api/v1/public/inbox-cases` nach Eingang des echten Status 201 angehalten und mit `ConnectionClosed` verworfen. Weder Anfrage noch API-Antwort wurden durch erfundene Daten ersetzt. Der Server hatte Fall `c43a5523-d550-4995-8203-770dfd547bb9` mit Referenz `2efb5c73-dfb0-4c37-881a-289740f05036` bereits gespeichert; dies wurde vor dem erneuten Senden per SQL festgestellt.

Chrome zeigte den unklaren Ausgang mit erhaltenen, gesperrten Feldern und aktivem „Erneut senden“. Der zweite im Browser abgesendete JSON-Befehl war vollständig identisch, einschließlich `idempotencyKey`. Die echte Wiederholungsantwort (201) wurde unverändert durchgelassen. Die Oberfläche bestätigte die ursprüngliche Referenz. Die anschließende SQL-Abfrage über die eindeutige synthetische E-Mail/Betreff-Kombination ergab einen Fall, einen Kontaktauftrag und eine Kontaktzuordnung.

Die nur für diesen API-Aufruf eingerichtete Browser-Interception wurde anschließend vollständig entfernt (`Fetch.enable` mit leerer Pattern-Liste). Screenshots von unklarem Ausgang und bestätigtem Replay wurden am PR angehängt. Dieser Nachweis deckt Antwortverlust nach Commit ab; zwischenzeitliche 429/422 nach unklarem Ausgang und automatische CRM-Erholung vor der Retry-Grenze bleiben eigene offene Prüfungen.


### Survey-Zugang aus der PWA wiederhergestellt

Die separate Browserabnahme fand eine reale Registrierungslücke: Der Survey-Beitrag lieferte nur `surface=web`; die Shell filtert Navigation nach Surface. Der aktive Testadministrator hatte deshalb in der PWA keinen Survey-Einstieg. Der Backend-Modulbeitrag liefert nun für Web und PWA denselben Link `/admin/surveys`. Die PWA registriert einen reinen Survey-Navigationsbeitrag ohne eigene Editorroute oder Editorimport.

40 Python-Identitäts-/Registrierungstests und 12 Frontend-Registrierungstests bestanden. Die Regression prüft beide Surface-Links und ausdrücklich das Fehlen einer zweiten PWA-Editorroute. PWA-Typprüfung, Ruff/Prettier sowie neue API-/PWA-Produktionsimages bestanden. Nach dem Deployment im eigenen Browserstack erschienen „Umfragen“ in der PWA und nach echtem Klick die vorhandene Survey-Webübersicht mit Suche und Neuanlage. Screenshots beider Zustände am Draft-PR.

Der parallel gestartete Survey-Integrations-/Exportlauf (Session 55844, Bericht `.artifacts/surveys-gate/results/d87d297714f74746998b0c3dae32a8c1.json`) bezieht sich auf den Ausgangsstand vor dieser Navigationskorrektur und ist noch nicht abgeschlossen. Seine Ergebnisse ersetzen weder die aktuelle Browserabnahme noch spätere Gesamt- und Recovery-Gates.


### Vollständige Survey-Exportjobmessung mit 5.000 Antworten

`tools/outbox/benchmark_export_jobs.py` erstellt eine synthetische Umfrage über die laufende Produktions-API, publiziert sie, hinterlegt 5.000 Antworten aus der vorhandenen Golden-Fixture und fordert die vier vorhandenen Exportprodukte an. Die normalen dauerhaften Worker führen die Jobs aus; der Runner wartet auf echte Verfügbarkeit und lädt die Dateien über die autorisierte Download-API. Er prüft Größe/Dateisignatur bzw. CSV-Zeilen und widerruft abschließend seine eigene Testsitzung. Kein synchroner Ersatzrenderer oder künstlicher Jobtyp.

Im eigenen Browserstack `leonaid-shared-32c62f415463ad67` gemessen (Sekunden ab Exportanforderung bis Verfügbarkeit / einschließlich Download):

| Produkt | Verfügbar | Heruntergeladen | Bytes |
| --- | ---: | ---: | ---: |
| Analyse-PDF | 0,270 | 0,280 | 34571 |
| Analyse-XLSX | 0,264 | 0,285 | 17793 |
| Antworten-CSV | 0,451 | 0,481 | 5431472 |
| Antworten-XLSX | 11,992 | 12,006 | 624023 |

Der laufende Worker bestätigt eine Lease von 300 Sekunden; die vorhandene Export-Handlergrenze beträgt damit 240 Sekunden. Dies sind lokale Einzelmessungen mit synthetischer Last, kein allgemeiner Durchsatzbenchmark. Alle vier Jobs wurden zusätzlich in PostgreSQL als `available` bestätigt. Der vorherige reine Renderer-Benchmark bleibt als engerer Vergleich erhalten.

Der größere Survey-Gate hat inzwischen `contracts` bestanden und arbeitet an `lifecycle`; weitere Integration-/Exportgruppen sind weiterhin offen.

## M3 — Verständliche Wiederholung nach unklarem Ausgang und Ablehnung

Das öffentliche Formular forderte nach einer verlorenen Antwort und anschließendem HTTP 422 zum Prüfen der Eingaben auf, obwohl es den Entwurf zum Schutz vor Doppelanlage absichtlich sperrt. Der Hinweis priorisiert nun den weiterhin unklaren Eingang und beschreibt die Wiederholung mit unveränderten Angaben.

LIVE im eigenen HTTPS-Produktionsstack: Anfrage mit synthetischer, serverseitig ungültiger E-Mail-Adresse senden; tatsächliche 422-Antwort per Browser-Verbindungsabbruch verwerfen; erneut senden und die zweite echte 422-Antwort passieren lassen. Beide JSON-Befehle einschließlich Idempotenzschlüssel waren identisch. Vor der Korrektur war die widersprüchliche Meldung reproduzierbar; nach Neubau und Deployment bleiben Entwurf und Wiederholung erhalten und die Meldung passt zum gesperrten Zustand. Keine Serverantwort wurde erfunden. Die temporäre Browser-Interception wurde entfernt. Screenshot: `/tmp/leonaid-inbox-uncertain-rejection.png`.

Validierung: `bun run --cwd apps/public check` (31 Dateien, keine Fehler/Warnungen), Prettier und Public-Docker-Produktionsbuild bestanden. Dieser Nachweis umfasst keinen erfolgreichen Commit und keine anschließende 429-Antwort; der erfolgreiche Commit mit verlorener Bestätigung ist separat dokumentiert.

## M2 — Unabhängige Termine und Web-/PWA-Speicherkonflikt

Echter Browserablauf in der privaten Liste `f019ab1a-ff78-4944-a50b-75e184850686` unter der synthetischen Anna-Akquise-Anmeldung: Aufgabe selbst zuweisen, Fälligkeit 22.09.2026 10:00 und Zurückstellung 16.09.2026 09:00 speichern. Die Aufgabe verschwindet aus der normalen offenen Ansicht und erscheint über Zurückgestellte anzeigen. Web und PWA laden anschließend gleichzeitig dieselbe Aufgabe zur Bearbeitung. Die PWA verschiebt ausschließlich die Zurückstellung auf 17.09.2026 09:00; die Fälligkeit bleibt unverändert. Der Webeditor versucht danach einen anderen Titel mit seinem älteren Stand zu speichern und zeigt einen Revisionskonflikt bei erhaltenem Titelentwurf. Nach bewusstem Schließen, Neuladen und Einblenden zeigt auch Web den ursprünglichen Titel und die beiden korrekten Termine.

Datumswerte wurden mit tatsächlichen Tastaturänderungen übernommen; reines automatisiertes Befüllen hatte zuvor nur den sichtbaren DOM-Wert verändert. Der Nachweis beruht auf dem erneut geladenen Serverstand, nicht auf diesen ungespeicherten Feldern. Screenshots visuell geprüft: `/tmp/leonaid-task-conflict-draft.png` und `/tmp/leonaid-task-independent-dates.png`. Keine Produktänderung notwendig. Die bestehende Anna-Akquise-Ansicht und Anmeldung bleiben erhalten. Vollständiger Schema-/Upgrade-Gate und übrige M2-Abnahmen laufen separat.

## M3 — Abnahme des atomaren öffentlichen Eingangs

Den übergeordneten Planpunkt für Snapshot, Fall, Kontaktauftrag und Referenzbestätigung geschlossen. Aktueller Schema-Gate (Session 19955, eigenes Projekt `leonaid-poc021-test-2137972478-27900`) hat `tools/inbox/submission_contract.py` erfolgreich ausgeführt: parallele identische Einreichung liefert dieselbe Referenz, geänderte Eingabe kollidiert, und ein tatsächlich verletztes Audit-Constraint nach Fall-/Job-Schreibvorgängen rollt Fall, Job, Audit und Receipt gemeinsam zurück; Wiederholung nach Beseitigung des Fehlers funktioniert.

Ergänzende Codeprüfung: `AsyncpgInboxRepository.submit` reserviert und bestätigt den Receipt innerhalb derselben PostgreSQL-Transaktion wie Snapshot und ausschließlich `inbox.contact_link.v1`. Die HTTP-Route wartet auf den Service; das Verlassen des Transaktionskontexts committet vor Rückgabe. Der Kontakt-Handler verwendet nur CRM und Datenbank, keinen Mailport. Zusammen mit den dokumentierten Produktionsbrowser-Nachweisen für öffentliche Bestätigung bei gestopptem Twenty und verlorene Antwort nach erfolgreichem Commit deckt dies den vollständigen Eingangs-Punkt ab. Der noch laufende Schema-Gesamtprozess und die separate CRM-Recovery-/Oberflächenabnahme werden dadurch nicht als abgeschlossen gewertet.

## M3 — Automatischer Wiederanlauf ohne manuellen Retry

Im eigenen Stack `leonaid-shared-32c62f415463ad67` Twenty tatsächlich gestoppt und über die produktive direkte Inbox-Fachoperation eine synthetische Anfrage angelegt. Der bereits laufende normale Worker zeigte nach Versuch 1 `contact_status=failed`, Job `pending` und `last_error_code=crm_unavailable`. Danach Worker angehalten, Twenty wieder gesund gestartet und denselben Workerprozess neu gestartet. Weder Jobstatus noch Zeitplan oder Versuchszähler wurden per SQL verändert; kein Admin-Retry wurde aufgerufen.

Die tatsächliche Datenbankprüfung nach Wiederanlauf bestätigt Referenz `1c517568-0483-4cf5-b49c-757da0e8d4ad`, Fall `8df87806-3b91-4d2e-97e6-b5c90bb81bf4`, denselben Kontaktauftrag mit `completed`, vier Versuchen und `manual_retry_count=0`. Kontaktstatus ist linked. Das echte Twenty liefert den Kontakt unter der vorab gespeicherten Create-ID, identisch zur zugeordneten Person; die Suche nach dem eindeutigen synthetischen Namen liefert genau einen Kontakt. Beide Dienste sind wieder healthy.

Ausführung über `/tmp/leonaid-inbox-browser-compose.py` mit `stop twenty-server`, direkter Fachoperation und SQL-Beobachtung im API-Container, `stop worker`, `up -d --no-deps --wait twenty-server`, `up -d --no-deps --wait worker`; Prüfskripte `/tmp/leonaid-inbox-auto-recovery.py` und `/tmp/leonaid-inbox-auto-verify.py`. Dieser Prozess-/Datenbanknachweis ergänzt die bereits dokumentierte öffentliche Browserbestätigung bei abgeschaltetem Twenty; er ist kein neuer Browsernachweis.

## M2/M3 — Vollständiger Schema- und Altbestands-Gate bestanden

`rtk proxy sh tools/schema/test.sh` ist mit Exit 0 beendet (Session 19955, eigenes Projekt `leonaid-poc021-test-2137972478-27900`). Der Runner prüfte den vollständigen leeren Aufbau bis 0041, anschließend alle eingetragenen Task-/Wissens-/Material-/Inbox-Schema-, Service-, Rechte-, Kompositions- und HTTP-Verträge mit echtem PostgreSQL beziehungsweise RustFS. Die zuvor reparierte Task-Aktionsmatrix bestand auch nach den fremden Material-Fixtures. Danach wurde eine frische Datenbank auf 0011 gebracht, der versionierte v0-Datenbestand importiert, bis Head migriert und der Legacy-Smoke erfolgreich geprüft. Abschließender Nachweis: `poc021-test: OK: Leeraufbau, Upgrade, Constraints und Datenhalt bewiesen` und vollständig entfernte eigene Ressourcen.

Diese Gesamtabnahme gilt für Backend/Schema des aktuellen Standes; die parallel neu ergänzte Frontend-Modulsuche benötigt ihre eigene Browserabnahme. Survey-Gesamt- und Remote-CI-Gates bleiben separat offen.

## M2 — Gemeinsame autorisierte Modulsuche

Die bei der Abnahme gefundene fehlende bereichsübergreifende Suche ergänzt: `UiModule.search` liefert über vorhandene API-Client-Aufrufe höchstens zehn Treffer mit geschlossenem Typ, stabiler ID, Titel, Kontext und Ziel. Aufgaben, Wissen und Materialien tragen ihre eigenen Abfragen bei. Eine gemeinsame aufklappbare Oberfläche wird von beiden Shells zusammengesetzt; Navigation bestimmt verfügbare Beiträge, jede Datenabfrage bleibt serverseitig autorisiert. Die Suche hat keine eigene Datenhaltung und keinen Suchdienst. Fehler je Bereich werden angezeigt; beim erneuten Abruf werden alte Ergebnisse nicht weiter dargestellt.

Aufgabenlinks mit `?task=<id>` laden genau die autorisierte Aufgabe auch außerhalb der normalen Offen-/Zurückstellungsfilter. Der gemeinsame Editor bewahrt die geladene Revision während der Bearbeitung; fremde Aufgaben beziehungsweise eine falsche Listenbindung zeigen keine Inhalte. Der bestehende Für-mich-Pfad fragt weiterhin denselben Taskbestand ab.

LIVE über Produktionsimages und HTTPS: je eine private Aufgabe, Wissensseite und tatsächlich hochgeladene Datei für zwei vorhandene synthetische Konten angelegt. Anna sucht denselben Titelpräfix in Web und PWA: jeweils genau die drei eigenen Treffer, keine fremden privaten Titel. Zurückgestellten Task aus Suchtreffer geöffnet, Materialziel im Web und Wissensziel in mobiler PWA geöffnet. Direkter fremder Tasklink bleibt gesperrt. Bei 390 px beträgt die Seitenbreite 390 px und der Suchbutton 44 px. Screenshots visuell geprüft: `/tmp/leonaid-module-search-web.png`, `/tmp/leonaid-module-search-mobile.png`. Fixture-IDs unter `/tmp/leonaid-module-search-fixture.json`; keine Zugangsdaten im Commit.

Prüfungen: Features-/Web-/PWA-Typen, zwölf Modulregistrierungstests, Frontend-API-Grenze, Prettier, Diffprüfung sowie beide Docker-Produktionsbuilds bestanden. Bestehende Anna-Anmeldung und Akquise-Navigation erhalten. Der separate Aggregat-Runner-Fix ist kein Teil dieses Commits.

## M1 — Aggregat-Gate ohne Host-Venv-Abhängigkeit

Der Survey-Gesamtlauf `d87d297714f74746998b0c3dae32a8c1` bestand contracts, lifecycle, lifecycle-concurrency, invitations und permissions (einschließlich 66 Browserprüfungen), scheiterte anschließend bei aggregates: uv versuchte die schreibgeschützte macOS-`.venv` im Linux-Container zu ersetzen. Dieser Lauf bleibt als fehlgeschlagen dokumentiert; die danach geplanten Prüfungen wurden nicht ausgeführt.

`tools/surveys/aggregate-engine.sh` installiert nun den vorhandenen eingefrorenen Produktions-Lock vor der Netzwerkisolation in `/proof/venv` und verwendet diese temporäre Linux-Umgebung für alle drei Prüfphasen. Checkout und Host-Venv bleiben schreibgeschützt, das Testnetz intern und ohne Hostports. Keine neue Produktabhängigkeit oder dauerhafte Infrastruktur.

`rtk proxy sh tools/surveys/aggregate-engine.sh` bestand mit Exit 0 (Session 87225, Projekt `surveys-engine-2137972478-34400`): echte HTTP-Aggregate gegen unabhängige Golden-Werte, expliziter Fehler bei gestopptem Dienst, identische korrekte Ergebnisse nach Wiederanlauf und vollständig geprüfte Bereinigung. Verifizieren/Ausfall/Neustart dauerten rund 35/32/34 Sekunden. Die übrigen Survey-/Exportprüfungen und vollständige Remote-CI-Abnahme bleiben offen.

## M2 — Task-Funktionsumfang zusammengeführt abgenommen

Den übergeordneten Task-Funktionspunkt nach Abgleich mit dem aktuellen Code abgenommen. `TaskFields` enthält genau einen optionalen Epic-Bezug, eine optionale persönliche Zuständigkeit und zwei unabhängige Zeitpunkte; `UpdateTask` erlaubt ausschließlich open/done und verlangt eine Revision. Epic-Eingaben enthalten keinen Elternbezug, zusätzliche Felder werden abgewiesen. Das Repository prüft Listen-/Personenrechte erneut, erzwingt die Epic-Zugehörigkeit und schreibt Fälligkeit und Zurückstellung getrennt. Die Sichtbarkeitsabfrage verwendet ausschließlich deferred_until und die Datenbankzeit.

Nachweise zusammengeführt: Der vollständig bestandene Schema-/Altbestands-Gate (Session 19955, dokumentiert unter „M2/M3 — Vollständiger Schema- und Altbestands-Gate bestanden“) führt Task-Schema-, Service-, HTTP- und Aktionsverträge aus. Diese prüfen unter anderem getrennte Zeitpunkte, Same-List-Epic, feste Zustände, Replay, Revision und Rechteentzug. Die Browsernachweise für Epic-Anlage/Umbenennung/Entfernung, Fremdzuweisung mit Abschluss in der PWA und den zuletzt bestandenen Zwei-Shell-Konflikt mit unveränderter Fälligkeit decken die Bedienpfade ab. Der gemeinsame Task-Editor implementiert diese Funktionen für beide Shells. Die früheren offenen Hinweise in einzelnen Zwischenständen beschreiben deren damalige Grenzen; dieser Abschluss betrifft den oben genannten Task-Funktionspunkt. Die übrigen M2- und Gesamtgates bleiben eigenständig offen.

Zusätzliche Akquise-Nachprüfung: Die bestehende Navigation ist unter der aktuellen synthetischen Anna-Anmeldung nach Neuladen sichtbar. Der 409 beim Bestellkontext hat den eindeutigen Code commitment_ordering_disabled: In der Aktion „Akquise Navigationstest“ sind Bestellungen nicht aktiviert. Die Sponsorenansicht lädt mit HTTP 200. Der allgemeine Verbindungshinweis der Bestellerfassung stellt diesen fachlichen Zustand noch unzutreffend dar; keine Aktivierung von Bestellungen oder Änderung von Berechtigungen zur Umgehung des Befunds. Screenshot der Rollen-Navigation am PR: https://github.com/BjoernSchotte/leonaid/pull/7#issuecomment-5655713291.

Der Nutzer bestätigt anschließend, dass die Navigation jetzt passt. Die Rückfrage nach der zuvor betroffenen Ansicht ist damit erledigt.

## M2 — Material-Speicherverantwortung zusammengeführt abgenommen

Den übergeordneten Materialpunkt nach aktuellem Codeabgleich abgenommen: Der FastAPI-Lifespan konstruiert eine gemeinsame S3ObjectStorage-Instanz und übergibt sie an GeneratedDocumentService, Survey-Exporte, Material-Service und Wissenskomposition. Das Material-Repository nutzt den bestehenden ObjectStorage-Vertrag einschließlich put_immutable; es gibt keine zweite Dateiablage. Material und material_version besitzen fachliche Metadaten, Versionskopf und die genaue S3-Version samt Prüfsumme. Downloads prüfen aktuelle Materialrechte sowie Größe, Medientyp und tatsächliche Prüfsumme. Wissensreferenzen speichern Material-ID und konkrete Version; sie kopieren weder Bytes noch geschützte Dateimetadaten.

Die Abnahme verbindet den vollständig bestandenen Schema-/Altbestands-Gate (Session 19955) mit den bereits dokumentierten tatsächlichen Web-/PWA-Uploads und Downloads, alter Version nach neuem Upload, einer Datei in zwei Seiten sowie unabhängigem Rechteentzug. Im Gate laufen die Material-Service-, Mitglieder-, Aktions-, HTTP- und Bereinigungsverträge mit PostgreSQL/RustFS. Der aktuell erneut gelesene Servicevertrag prüft insbesondere äußeren Rollback mit Wiederaufnahme, konkurrierenden Upload/Replay, Versionskonflikt und unveränderte alte Bytes. Damit ist der Speicher-/Versionspunkt erfüllt; die separate dauerhafte Browser-CI und übrigen Gesamtgates werden dadurch nicht als abgeschlossen erklärt. Keine Produktionsänderung in diesem Abnahmeschnitt.

## M1 — Survey-Analyse nach Runner-Korrektur bestanden

Der separate zentrale Runnerbericht `.artifacts/surveys-gate/results/6fd0593d0e914d83a685fa59ce79e275.json` bestätigt analysis mit Exit 0 nach 518,91 Sekunden auf Commit 2669205349c408381e29e7026638c009c40365b2. Session 10846 setzte anschließend mit request-limits fort und ist weiterhin aktiv; Payload-Limits und die vollständige Exportgruppe folgen in derselben sequenziellen Ausführung. Dieser Einzelcheck ersetzt den noch offenen Survey-Gesamtabschluss nicht.

## M2 — Wissensinhalt und Revisionsschutz zusammengeführt abgenommen

Den übergeordneten Wissens-Funktionspunkt nach erneutem Abgleich des öffentlichen Vertrags, Repositories und gemeinsamen Editors abgenommen. Seiten besitzen Titel, validiertes Tiptap-Dokument und revisionierte Snapshots. Änderungen prüfen expected_revision vor der nächsten Revision; der gemeinsame Editor behält bei HTTP 409 seinen lokalen Entwurf und ersetzt ihn nur nach bestätigtem, erfolgreichem Neuladen. Task-Knoten enthalten stabile IDs, Material-Knoten IDs und konkrete Versionen. Anzeige und Download verwenden die jeweiligen autorisierten Fach-APIs; das Speichern prüft Referenzen innerhalb derselben Datenbanktransaktion. Es wurde kein Yjs-Dienst eingeführt.

Nachweise: Vollständiger Schema-/Altbestands-Gate (Session 19955) einschließlich Wissens-Service-, HTTP-, Task-aus-Seite- und Materialreferenzverträgen; dokumentierte tatsächliche Web-/PWA-Roundtrips für Formatierung, konkurrierende Seitenänderung mit erhaltenem Entwurf, Task-Anlage/Zuweisung/Abschluss sowie feste Materialversion in zwei Seiten und unabhängigen Rechteentzug. Erneut lokal ausgeführt: `rtk proxy uv run --frozen pytest -q tests/unit/test_knowledge_document.py`, 41 Tests bestanden. Diese prüfen den begrenzten Dokumentvertrag einschließlich Referenzen; sie ersetzen die genannten Datenbank- und Browsernachweise nicht. Keine Produktionsänderung in diesem Abnahmeschnitt. Der separate gemeinsame Aktions-/Rechtepunkt, die vollständige mobile Bedienabnahme und die übrigen Gesamtgates bleiben offen.

## M1 — Erfolgreicher Fristenlauf in Operations sichtbar

Der vorhandene Worker-Readiness-Endpunkt ergänzt lastSuccessfulSweepAt aus derselben prozesslokalen Erfolgsmarke wie die Metrik. Die Operations-Abfrage übernimmt ausschließlich einen timezone-aware Zeitpunkt vom Worker; ältere Worker ohne Feld bleiben kompatibel und zeigen keinen behaupteten Erfolg. Der generierte Vertrag ergänzt ein optionales Feld an der Abhängigkeitsanzeige. Die bestehende Web-Operations-Kachel zeigt Zeitpunkt und die ausdrückliche Grenze „seit dem letzten Worker-Start“. Datenbank-Readiness erzeugt keine Sweep-Erfolgsmarke. Keine neue Tabelle, kein Dienst und keine persistente Verlaufsspeicherung.

LIVE im eigenen Produktionsstack leonaid-shared-32c62f415463ad67: API/Worker/Web neu gebaut und gestartet. Browser als bestehender Testadministrator zeigt tatsächlich erfolgreichen Fristenlauf 13.09.2026 22:05:18 Ortszeit. Worker über Compose vollständig gestoppt und Operations aktualisiert: Nicht erreichbar, kein alter Erfolgszeitpunkt. Danach denselben Worker wieder gestartet. Screenshots vom erreichbaren und gestoppten Zustand unter /tmp/leonaid-operations-sweep-ready.png und /tmp/leonaid-operations-sweep-stopped.png visuell geprüft. Die bereits ausgefallene Test-Mail-Abhängigkeit und vier zuvor absichtlich fehlgeschlagene Inbox-Aufträge sind sichtbar geblieben; sie wurden für diesen Nachweis nicht verändert.

Acht gezielte Worker-/Operations-Tests bestanden, darunter frischer Python-Prozess ohne Sweep-Erfolg und später tatsächlich gesetzte Erfolgsmarke. Ruff, Mypy der vier betroffenen Python-Implementierungen, Features-Typecheck, OpenAPI-/Client-Generierung, Prettier, Diffprüfung und Produktionsbuild bestanden. Der umfassende Operations-/Survey-Abschluss bleibt separat offen.

Der separate Survey-Runner hat auch request-limits bestanden: Bericht a66990d6ae7342f8b3c9db922da6c403, Exit 0, 337,029 Sekunden. Session 10846 führt payload-limits und danach die vollständige Exportgruppe weiter aus.

## M2 — Gemeinsame Aktionskontexte und unabhängige Objektberechtigungen abgenommen

Den übergeordneten Kontext-/Rechtepunkt nach aktuellem Code- und Nachweisabgleich abgenommen. Tasks, Wissen und Materialien verwenden dieselbe begrenzte Aktionsauswahl im Frontend; jede Anlage und jeder spätere Objektzugriff prüft die tatsächlichen Datenbankrechte erneut. Eigenständige Objekte erlauben Eigentümer und explizit berechtigte Konten; eine globale Verwaltungsrolle öffnet keine privaten Objekte. Aktionsobjekte verlangen aktuelle Aktionsmitgliedschaft oder aktuelle Systemadministration. Zusätzliche Objektfreigaben umgehen diese Grenze nicht. Darstellung, Suche, Referenzauflösung und Downloads verwenden die jeweilige Objektregel. Referenzierte IDs gewähren keine Rechte.

Die im vollständig bestandenen Schema-Gate (Session 19955) ausgeführten drei Aktionsverträge prüfen jeweils zehn Identitäten einschließlich fremder Aktion, abgelaufener/künftiger Mitgliedschaft, veralteter behaupteter Globalrolle, Entzug und Replay. Wissens-Service- und Materialreferenzverträge prüfen explizit, dass lesbare Seiten keinen Task-/Dateizugriff erteilen. Die vorhandenen Browsernachweise decken private Freigaben mit Rollenwechsel/Entzug, Aktionsanlage und Filter in Web/PWA sowie fremde private Objekte in der gemeinsamen Suche ab. Der aktuelle Source-Abgleich bestätigt die gemeinsame Auswahl und Freigabebedienung in allen drei Modulen. Keine Produktionsänderung für diesen Abnahmeschnitt. Die separate vollständige mobile Bedien- und Browser-CI-Abnahme bleibt offen.

## M1 — Payload-Limitprüfung bestanden

Session 10846 meldet payload-limits als bestanden. Der zentrale Bericht 4193166e5a114ce48d2efa8759797b04 bestätigt Exit 0 nach 345,991 Sekunden. Anschließend wurde die vollständige Exportgruppe gestartet (Bericht a241762639374f03ac8a5db5c68c23db, noch running). Keine erneute Ausführung wegen bloßer Wartezeit; der bestehende Prozess arbeitet weiter.

## M3 — Kontaktstatus und CRM-Recovery zusammengeführt abgenommen

Die beiden übergeordneten Punkte für Kontaktstatus und sichere CRM-Wiederaufnahme nach aktuellem Codeabgleich abgenommen. Liste und Fallansicht zeigen pending, failed, needs_review und linked; unvollständige Zuordnung sperrt die Fallbearbeitung nicht. Der Fall hält den unveränderlichen Eingangssnapshot. Der automatische Handler sucht ausschließlich die vorher gespeicherte Twenty-Create-ID und verlangt außerdem den erwarteten Datenstand. Er speichert die Create-Absicht vor externer I/O; bei unbewiesenem Ausgang oder abweichenden Daten stoppt er zur manuellen Klärung. Es gibt weder Namens-Merge noch automatisches Update eines vorhandenen Twenty-Kontakts. Die autorisierte manuelle Auswahl prüft Kontaktrevision und Vorschau-Fingerprint, verlangt eine Begründung und beendet den ruhenden Auftrag atomar.

Zusammengeführte Nachweise: vollständiger tatsächlicher Twenty-/PostgreSQL-Vertrag mit erfolgreichem Create und verworfener Antwort, exakter ID-Wiederaufnahme ohne Duplikat, unbewiesenem/mismatched Ergebnis, Claim-Fencing, konkurrierender HTTP-/Direktbestätigung, veränderter CRM-Vorschau und Audit-Rollback. Produktionsbrowser: fehlgeschlagene/unklare Zuordnung und bewusste Bestätigung eines echten Twenty-Kontakts; öffentliche Bestätigung und fortgesetzte Fallbearbeitung bei Twenty-Ausfall. Normaler Produktionsworker nach Twenty- und Worker-Neustart: ein Kontakt, abgeschlossener ursprünglicher Auftrag, manual_retry_count 0. Diese Ergebnisse sind in den vorausgehenden Twenty-, Inbox-UI- und automatischen Wiederanlaufabschnitten dokumentiert. Der aktuelle Handler und die Kontaktoberfläche stimmen weiterhin mit diesen Regeln überein.

Keine Produktionsänderung in diesem Abnahmeschnitt. Der umfassende Inbox-Surface-Punkt bleibt offen, insbesondere die noch benannten zusammengesetzten Formularfehler und Browser-Download-/Uploadnachweise. Auch Survey-, Rollback- und Gesamt-CI-Abnahmen bleiben eigenständige Anforderungen.
