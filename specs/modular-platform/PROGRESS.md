# Modularisierung: Fortschritt und Nachweise

## M0.1 — Ausgangsstand und Survey-Inventar

Status: abgeschlossen am 13.09.2026. Ausgangscommit `b82ac45`; Slice-Commit ist der Commit, der diesen Abschnitt anlegt. Implementierung und LIVE-Abnahme von M0–M3 sind weiterhin offen.

Der per GitHub API gelesene Hauptbranch ist `2043b72b7c5453b37978f2a58436243dbc378a00` und entspricht der Spec-Basis. Der Worktree war sauber. Keine Migration, kein laufender Dienst und keine fachlichen Daten wurden verändert.

### Eigentum und Abhängigkeiten des ersten Moduls

| Bereich | Bestehender Pfad / Vertrag | Einordnung für Migration |
| --- | --- | --- |
| Definitionen und Lebenszyklus | `domain/surveys/`, `application/surveys/`, `adapters/postgres/surveys.py` | Survey-Modul; `SurveyService` delegiert heute an einen Persistence-Port |
| Transport | `entrypoints/fastapi/surveys.py` | Survey-Router einschließlich Pydantic-Eingaben; Sitzung, CSRF und Body-Grenzen erhalten |
| Identität | `domain/identity.py`, `domain/policies.py` | Gemeinsame Identität und Aktionszugriffsprüfung; keine neue Identitätskopie |
| Analyse/Antworten | `application/surveys/{analysis,analysis_snapshot,response_selection}.py`, entsprechende PostgreSQL-Adapter | Survey-eigen; Analyse-/Antwortauswahl nicht in globale Plattform verschieben |
| Exporte | `application/surveys/exports.py`, `adapters/postgres/survey_exports.py` | Survey-eigene Jobs mit gemeinsamem Storage, Queue und Typst-Adapter |
| Löschung/Recovery | `adapters/postgres/survey_{deletion,retention,recovery,checkpoint_publisher}.py` | Fachliche Lösch- und Wiederherstellungsregeln bleiben Surveys; bestehendes Archiv erhalten |
| Einladungen | Survey-Repository und `adapters/mail/survey_smtp.py` | Fachliche Einladungen mit gemeinsamem sicheren Mailtransport |
| Verdrahtung | `entrypoints/fastapi/platform.py`, `entrypoints/worker/{outbox,platform}.py` | Modulregistrierung/Komposition nach Bootstrap; Prozessstart kompatibel halten |
| Frontend | `apps/web/src/surveys*.tsx`, `packages/surveys/`, bestehender API-Client | Web-Einstieg modularisieren, Renderer/Client weiterverwenden; PWA verweist bereits auf Web-Survey-Einstieg |

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

| Producer/Persistenz | Verhalten ohne Zeitpunkt | Verhalten mit Zeitpunkt |
| --- | --- | --- |
| ActionProgress / `AsyncpgTransactionalOutboxRepository.append` | Datenbank-Transaktionszeit wie bisheriger Default | Zeitpunkt atomar beim Append |
| Einladungen und Ersatzeinladungen / `AsyncpgInvitationRepository` | bisheriges `occurred_at` | eigener Zeitpunkt; `created_at` bleibt `occurred_at` |
| E-Mail-Wechsel / `AsyncpgEmailChangeRepository` | bisheriges `occurred_at` | eigener Zeitpunkt; `created_at` bleibt `occurred_at` |
| Login-Mail / `AsyncpgSessionRepository` | Datenbank-Transaktionszeit wie bisheriger Default | eigener Zeitpunkt; `created_at` unverändert |

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

| Produkt | Median | Einzelmessungen in Sekunden | Ausgabegröße |
| --- | ---: | --- | ---: |
| Aggregat-PDF | 0,034 s | 0,046 / 0,0287 / 0,034 | 34.591 Bytes |
| Aggregat-XLSX | 0,0225 s | 0,0254 / 0,0216 / 0,0225 | 17.795 Bytes |
| 5.000 Antworten als CSV | 0,0978 s | 0,1096 / 0,0978 / 0,0938 | 5.433.474 Bytes |
| 5.000 Antworten als XLSX | 7,1703 s | 7,0186 / 7,1703 / 7,2747 | 625.775 Bytes |

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
