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
