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
