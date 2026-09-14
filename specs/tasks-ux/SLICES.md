# Aufgaben-UX: Implementation Plan pro Slice

> Implementierung beauftragt: Die Pakete werden mit Superpowers schrittweise
> ausgeführt. Verifizierter Fortschritt und offene Einzelabnahmen stehen in
> [PROGRESS.md](PROGRESS.md); ein Plan-Häkchen ersetzt keinen Nachweis.

**Ziel:** Erst eine kompakte Desktop-/PWA-Aufgabenverwaltung liefern, anschließend
persönliche Planung und zusätzliche Funktionen mit nachprüfbaren Einzelabnahmen.

**Architektur:** Bestehendes Tasks-Modul im modularen Monolithen, gemeinsame
React-Oberfläche und FastAPI-Fachoperationen. PostgreSQL hält Rechte, Revisionen,
Idempotenz und neue Zustände; zeitgesteuerte Arbeit verwendet die vorhandene Outbox.

**Tech Stack:** TypeScript/React, vorhandener Query-Cache und UI-Tokens, Python/FastAPI,
PostgreSQL/Alembic, Playwright, bestehender Worker/SMTP-Transport. Keine neuen Dienste.

**Spec:** [PLAN.md](PLAN.md). **Globale Regeln/Kommandos:** [ACCEPTANCE.md](ACCEPTANCE.md).
Die Struktur folgt dem offiziellen Superpowers-Skill
[writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md):
kleine prüfbare Lieferpakete, Dateizuordnung, explizite Schnittstellen und Selbstprüfung.
Dies sind Slice-Verträge zur Spec, keine vorab fertig geschriebenen Produktpatches.

## Globale Grenzen und Leseregeln

- Deutsche gemeinsame Web/PWA-Oberfläche, AppShell-Rechte erhalten, Touch-Ziele
  mindestens 44 × 44 CSS-px. Ergänzender Nutzerauftrag vom 14.09.2026:
  gemeinsame Textbuttons auf Desktop auf 40 px Mindesthöhe verdichten, Touch
  mindestens 44 px; normale Leseschrift und Icon-Trefferflächen erhalten.
- Keine zusätzlichen Dienste, keine Offline-Schreibwarteschlange, keine neue
  Realtime-Infrastruktur. Bestehende freie Hugeicons und Design-Tokens verwenden.
- Jede neue schreibende Operation: Actor aus Sitzung, aktuelle Rechteprüfung,
  erwartete Revision und Idempotency-Key. HTTP und direkte Fachaufrufe teilen die
  Implementierung. Bei Konflikt keine teilweise persistierte Änderung.
- `Task` bezeichnet den vorhandenen Rückgabetyp von `getTask`; `TaskList` die
  bestehende Liste. Neue Namen unten sind geplante additive Verträge, keine
  Behauptung, dass entsprechende Methoden oder Dateien schon existieren.
- „Backend“ meint die vorhandenen Dateien `src/leonaid/modules/tasks/api.py`,
  `repository.py`, `routes.py`; „Client“ meint die Generierung von
  `packages/api-client/src/generated.ts`, keine manuellen Änderungen daran.
- Neue Tabellen erhalten additive Migrationen in `migrations/versions/`. Die
  Revisions-ID aus dem dann aktuellen Alembic-Head erzeugen; keine heute reservierte
  Nummer gegen parallele Migrationen durchsetzen. Rücknahme erhält diese Daten.
- „Tasks-UI/CSS“ meint `packages/features/src/tasks/tasks.tsx` und `tasks.css`;
  „Task-Details“ meint `packages/features/src/tasks/task-editor.tsx`.
  Workerregistrierung liegt in `src/leonaid/bootstrap/worker.py`; der Collector
  in `src/leonaid/bootstrap/registry.py` wird weiterverwendet, nicht dupliziert.
- Nachweise und Prüfkommandos K1–K5/W sind in ACCEPTANCE.md definiert. Der jeweilige
  Prüfauftrag gehört zum Slice; neu genannte Tests müssen im vorhandenen Runner
  registriert werden. Kein Erfolg allein durch Existenz einer Testdatei.
- S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10a → S10b → S11.
  Jede Kriteriums-ID muss vor dem Nachfolger einen bestandenen Beleg haben.

## S1 – Aufgabenliste, Navigation und direktes Abhaken

**Voraussetzung:** Ausgangsstand und vorhandene Tasks-/Wissen-Browserfälle geprüft.
**Lieferumfang:** kompakte Zeilen, mobile Liste zuerst, Verwaltungsmenüs,
Metadaten, direktes Abhaken/Rückgängig. Terminsemantik bleibt unverändert.
**Dateien:** ändern `packages/features/src/tasks/tasks.tsx`, `tasks.css`, Backend,
Client, `packages/ui/src/styles/globals.css` (gemeinsame Button-Dichte),
`tools/tasks/service_contract.py`, `http_contract.py`,
`tests/e2e/modules-tasks.spec.mjs`; kleine Zeilenkomponente nur bei Bedarf extrahieren.
**Schnittstelle:** `TaskSummary = Task + {listTitle: string, actionTitle: string|null,
assigneeName: string|null, epicTitle: string|null, canEdit: boolean}` in der
Listenprojektion. `TaskList` erhält `canEdit`. `updateTask` bleibt unverändert.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S1-A1 | 12 Aufgaben, 390 × 844, Listenverwaltung geschlossen | Erste Aufgabenzeile ohne Scrollen sichtbar; kein Listenanlageformular davor. Bei 320 px kein horizontaler Scroll; Touch-Checkbox mindestens 44 × 44 px. |
| S1-A2 | Aufgabe mit allen bestehenden Feldern, abhaken und Rückgängig | Nach jedem Speichern/Reload nur Status und Revision geändert. Ein ursprünglicher und ein Undo-Receipt; kein zweiter Schreibvorgang durch schnellen Doppelklick. |
| S1-A3 | A hakt ab, B ändert Titel, A macht rückgängig | 409; Bs Titel und Status bleiben erhalten. Fehlermeldung/Neu laden sichtbar. Kein blindes Überschreiben mit alten Feldern. |
| S1-A4 | Leser, Bearbeiter und fremde Liste; danach Rechteentzug | `canEdit` stimmt mit Schreibprüfung überein. Leser ohne Schreibcontrols, fremde Labels nicht sichtbar, veralteter Bearbeiterzugriff serverseitig gesperrt. |
| S1-A5 | 1 und 50 Aufgaben laden | Labels ohne zusätzliche HTTP-Abfrage pro Zeile; SQL-Leseanzahl wächst nicht mit der Zeilenzahl. Unzugewiesen hat keinen erfundenen Personennamen. |
| S1-A6 | Tastatur, 240-Zeichen-Titel, leere Suche, langsame Aktualisierung | Alle Aktionen fokussierbar; Checkbox öffnet nicht Details. Titel wächst, vorhandene Daten verschwinden beim Refetch nicht. Leerzustände unterscheidbar. |
| S1-A7 | Gemeinsame Buttons in Aufgaben, Wissen und Materialien auf Desktop/PWA | Einzeilige Icon/Text-Anordnung, Textbuttons desktop 40–44 px und auf Touch 44–48 px bei kurzen Labels; lange Labels wachsen ohne Abschneiden. Ruhigere Gewichtung und Innenabstände, sichtbarer Fokus und unveränderte Bedienbarkeit. |

**Arbeitsschritte:**
- [x] S1-A2/A3 als echte Service-/HTTP-Nachweise und S1-A1 als Browserfall ergänzen;
  vor Implementierung die fehlende direkte Statusaktion beziehungsweise Projektion belegen.
- [x] Projektion/Policy und Zeilen-/Navigationsdarstellung gemeinsam implementieren.
- [x] K1, K2, K3 ausführen; Screenshot `s1-desktop-list.png`, `s1-pwa-list.png`
  und sichtbaren Rückgängig-Zustand prüfen, pushen, K5 abwarten.
**Rücknahmegrenze:** UI-Revert, additive Lesefelder können bleiben. Aufgabeninhalte
und Rechte dürfen bei Rücknahme nicht konvertiert werden. Kein S2 bei offenem A1–A7.

## S2 – Schnellerfassung, Details und Rücknavigation

**Voraussetzung:** S1 einschließlich Rechteprojektion und Statusmutation grün.
**Lieferumfang:** kompakte Erfassung, Details rechts oder eigene Ansicht,
Eigenschaften auf Anforderung, Verwerfschutz und URL-/Fokuszustand.
Ergänzender Nutzerauftrag: aktueller Listenname und die Icon-Aktionen
„Liste wechseln“/„Zugriff verwalten“ in einer kompakten Kopfzeile; Zugriff nur
mit Verwaltungsrecht. Icons mit Tooltip bei Hover/Fokus, zugänglichem Namen,
`aria-expanded`/`aria-controls` und mindestens 44 × 44 px Trefferfläche.
Geöffnete Bereiche erhalten sichtbare Überschriften; auf Touch ist keine
Funktion vom Tooltip abhängig. Bei langen Listennamen wachsen oder kürzen
sich nur die Namen, die beiden Aktionen bleiben erreichbar.
**Dateien:** ändern `tasks.tsx`, `task-editor.tsx`, `epic-picker.tsx`,
`assignee-picker.tsx`, `tasks.css`, `tests/e2e/modules-tasks.spec.mjs`,
`tests/e2e/knowledge-editor.spec.mjs`; neu `tests/e2e/tasks-details.spec.mjs`,
registrieren in `tools/testing/modular_browser.sh`.
**Schnittstelle:** vorhandene Create-/Update-Task- und Epic-Aufrufe. URL-Zustand
`scope=mine|all`, `view=open|done`, `search`, `task`; fehlende Parameter bewahren
bisherige Defaults. Scroll/Fokus in History-State, keine Task-Texte in der URL.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S2-A1 | Aktuelle Liste, „Für mich“, Titel eingeben und Enter | Genau eine Aufgabe in der sichtbaren Liste; eigene Person nur wenn zuweisbar sichtbar vorausgewählt. Leerer Titel erzeugt keine Aufgabe. |
| S2-A2 | Übergreifende Ansicht ohne ausgewählte Liste | Erfassung verlangt eine bearbeitbare Liste. Kein unsichtbarer Default, keine automatisch erzeugte Inbox. Leser kann keine Aufgabe anlegen. |
| S2-A3 | Detail öffnen bei 1440, 1024 und 390 px | Nebenansicht nur bei mindestens 360 px verbleibender Listenbreite; sonst eigene Ansicht. Beschreibung zuerst, Such-/Verwaltungsformulare nicht permanent geöffnet. Listenwechsel und berechtigtes Zugriffsmenü als Icon-Aktionen in einer Kopfzeile; Tooltip auch bei Tastaturfokus, klare Namen/Öffnungszustände, keine Überlagerung bei 320 px/langem Listennamen. |
| S2-A4 | Suchfilter, zweite geladene Seite, Detail, Browser-Zurück und Reload | Filter/Ansicht bleiben gleich, Rückkehr zeigt vorherige Zeile/Fokus. Direkter `?task=`-Link funktioniert und hat Rückweg ohne fremde Historie. |
| S2-A5 | Entwurf ändern; Escape, Schließen, Browser-Zurück; anschließend 409 | Änderungen gehen nicht still verloren; Abbrechen der Verwerfsentscheidung erhält den Entwurf. 409/Netzfehler lassen Felder editierbar und Werte erhalten. |
| S2-A6 | PWA mit geöffneter Bildschirmtastatur; Aufgabe aus Wissensseite öffnen | Speichern erreichbar, kein Feld hinter der AppShell verdeckt; bestehende Referenz öffnet genau die Aufgabe. Test in echtem mobilen Browser zusätzlich zur Viewport-Emulation. |

**Arbeitsschritte:**
- [x] S2-A4/A5 mit realen Navigationsschritten als zunächst fehlschlagende Fälle ergänzen.
- [x] Gemeinsamen Editor in responsive Detailansicht einbinden, URL/History und
  Verwerfschutz vervollständigen; keine zweite Mutationsimplementierung.
- [x] K1/K3; bei Änderung von API-Verhalten zusätzlich K2. Desktop-/PWA-Details
  und Schnellerfassung aufnehmen; Tastaturbeleg mit Plattform nennen. Push/K5.
**Rücknahmegrenze:** UI zurücknehmen; URLs mit `?task=` bleiben auflösbar. Kein
Browser-State darf Voraussetzung zum Lesen persistierter Aufgaben werden.

## S3 – Terminansichten, Sortierung und Abschnitte

**Voraussetzung:** S2 mit erhaltenem Navigationszustand bestanden.
**Lieferumfang:** exakt definierte Ansichten aus PLAN, gruppierte Listen,
serverseitige Filter und korrektes Nachladen.
**Dateien:** Backend/Client, `tasks.tsx`, `tasks.css`,
`tools/tasks/service_contract.py`, `http_contract.py`; neu
`tests/e2e/tasks-views.spec.mjs`, im Modulrunner registrieren.
**Schnittstelle:** additive `TaskQuery`-Felder `dueFrom`, `dueBefore` (UTC),
`deferredState=active|deferred|all`, `sort=created|due|section`. Alte Parameter
bleiben kompatibel; `section` ist nur mit `listId` gültig (sonst 422).
URL übernimmt `view=open|due-today|due-next|deferred|done` und `sort`.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S3-A1 | Mindestens 120 Aufgaben, gesuchte Treffer erst nach Position 50 | Termin-/Status-/Scope-/Suchfilter liefern exakt die vollständige erwartete ID-Menge über alle Seiten; keine bloße Filterung geladener Zeilen. |
| S3-A2 | Lokaler Tag 29.03.2026 und 25.10.2026, Europe/Berlin | UTC-Intervalle 28.03.23:00 bis 29.03.22:00 und 24.10.22:00 bis 25.10.23:00. Untere Grenze enthalten, obere ausgeschlossen, NULL-Datum ausgeschlossen. |
| S3-A3 | Fällig heute und bis morgen zurückgestellt | In „Heute fällig“ enthalten, in „Offen“ ausgeschlossen, in „Zurückgestellt“ enthalten. Beide Zeitwerte unverändert nach Ansichtswechsel. |
| S3-A4 | Gleiche Fälligkeit, gleiche Epic-Titel, ohne Epic, Gruppe über Seite 50 | Stabile ID-Reihenfolge, kein Duplikat, genau eine zusammenhängende Überschrift pro Abschnitt; ohne Abschnitt zuletzt. Keine als Gesamtmenge ausgegebene Seitenzahl. |
| S3-A5 | Alte Anfrage nur `includeDeferred`; widersprüchliche neue Anfrage | Alter Client liefert dieselbe Menge wie zuvor; explizit widersprüchliche Filter und invertiertes Datum liefern 422. |
| S3-A6 | Filter/Sortierung ändern nach Nachladen | Pagination zurückgesetzt, fremde alte Seiten verschwinden; Zurücknavigation stellt denselben Filter wieder her. „Weitere laden“ fehlt am Ende. |

**Arbeitsschritte:**
- [x] S3-A1/A2/A5 als Vertragsfälle vor API-Erweiterung ausführen und fehlendes
  Filterverhalten belegen; erwartete IDs unabhängig von der Produktabfrage festlegen.
- [x] Query-Validierung, SQL vor Pagination, Client und Ansichten implementieren.
- [x] K1/K2/K3, gruppierte Desktop-Liste und mobile Terminansicht aufnehmen;
  Resultatmatrix mit Grenzen/IDs dokumentieren, pushen, K5.
**Rücknahmegrenze:** alter Standard bleibt `created`; neue Lesefilter können bleiben.
Keine Datumswerte zur Herstellung einer Ansicht umschreiben.

## S4 – Abnahme der UX-Grundlage

**Voraussetzung:** alle Kriterien S1–S3 bestanden; kein neuer Funktionsumfang.
**Dateien:** bestehende Tasks-/Wissen-Browserfälle, neue Fälle aus S2/S3,
`specs/tasks-ux/PROGRESS.md`; Produktdateien nur für nachgewiesene Regressionen.
**Schnittstelle:** unveränderte Fachoperationen plus additive Lesemodelle aus S1/S3.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S4-A1 | Desktop, Tablet, 390/320 px und 200 % Zoom | Matrix aus ACCEPTANCE vollständig bestanden; keine abgeschnittenen Inhalte/Aktionen, Touch-Ziele gemessen. |
| S4-A2 | Anlegen → zuweisen → verschieben in Abschnitt → zurückstellen → finden → erledigen → wiederöffnen | Durchgängiger Ablauf auf Web/PWA; „in Abschnitt“ hier über den Editor, noch kein Drag-and-drop. Fälligkeit und Referenzen bleiben erhalten. |
| S4-A3 | Eigentümer, Bearbeiter, Leser, Rechteentzug, Konflikt | Rechtefälle aus S1/S2 plus bestehende Wissens-/Inbox-Verweise bestanden; kein Umgehen durch Direktlink. |
| S4-A4 | Abschluss-Commit gepusht | K1–K5 einschließlich gesamter CI grün; PROGRESS enthält pro S1–S4-Kriterium Commit/Beleg und PR-Anhänge. |

**Arbeitsschritte:**
- [x] Offene Nachweiszellen ermitteln, Fälle durchführen, konkrete Fehler korrigieren.
- [x] K1/K3/K4 auf dem Abschlussstand; Desktop-/PWA-Hauptablauf visuell dokumentieren.
- [x] S4 erst nach vollständigem Ergebnis abhaken; dann kann S5 beginnen.
**Rücknahmegrenze:** bis hier keine fachliche Datenmigration. Bestehende Aufgaben
müssen mit der vorherigen UI weiterhin les-/bearbeitbar sein.

## S5 – Persönliche Tagesplanung

**Voraussetzung:** S4 abgeschlossen; Teamtermine und persönliche Planung klar getrennt.
**Dateien:** Backend/Client, additive Migration, `tasks.tsx`, `task-editor.tsx`;
neu `src/leonaid/modules/tasks/planning.py`, `tools/tasks/planning_contract.py`,
`tests/e2e/tasks-planning.spec.mjs`; K2-/K3-Runner erweitern.
**Schnittstelle:** `PersonalPlan {taskId, state: scheduled|someday|unplanned,
plannedOn: YYYY-MM-DD|null, revision}`; unplanned hat kein Datum. Beim ersten
Schreiben `expectedRevision=0`, danach aktuelle Revision. Entfernen setzt
unplanned als Revisionsträger, statt durch Löschen alte Revisionen wieder gültig
zu machen. `setTaskPlan(taskId, {state, plannedOn, expectedRevision,
idempotencyKey})`; `listTaskPlans({view:today|planned|someday, timeZone, offset,limit})`.
Server validiert IANA-Zeitzone und leitet today aus aktueller Zeit ab. Keine User-ID
im Auftrag, Actor ausschließlich aus Sitzung. `task_personal_plan` eindeutig pro
Actor/Aufgabe; keine Spaltenänderung an gemeinsamer Deadline oder Zuweisung.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S5-A1 | A und B planen dieselbe Aufgabe für verschiedene Tage | A sieht nur As, B nur Bs Plan. Task-Revision, Deadline, Assignee und Wiedervorlage bleiben unverändert. |
| S5-A2 | Gestern geplant und offen; erledigen, wiederöffnen | Offen in Heute übernommen, ursprüngliches Datum erhalten. Erledigt verschwindet; Wiederöffnen zeigt den erhaltenen Plan erneut. |
| S5-A3 | Dieselbe Aufgabe geplant und heute fällig, andere fällige eigene Aufgabe ungeplant | Erste genau einmal im Plan, zweite genau einmal im Fälligkeitshinweis. Kein automatisch erzeugter Planungsdatensatz. |
| S5-A4 | Leser plant, versucht abzuhaken; danach verliert er Zugriff | Planung zulässig, gemeinsame Mutation gesperrt; nach Entzug kein Lesen/Replay der Planung mit Task-Daten. |
| S5-A5 | Plan löschen und mit veralteter Revision neu schreiben; identischer Retry | Revisionsträger verhindert ABA-Konflikt; veralteter Auftrag 409, identischer Retry liefert genau einen Effekt. |
| S5-A6 | Ungültige Zeitzone, scheduled ohne Datum, someday mit Datum | 422 ohne Schreibvorgang. Zeitzonenwechsel verändert Heute-Zuordnung, nicht das gespeicherte Kalenderdatum. |

**Arbeitsschritte:**
- [x] S5-A1/A4/A5 als echte Mehrnutzer-/Transaktionsfälle ergänzen und ausführen.
- [x] Migration, persönliche Operationen und UI gemeinsam liefern; historische
  Aufgaben bleiben ohne Plan und erhalten keine automatische Planung.
- [x] K1–K4, Migration über befüllten Altbestand prüfen; persönliche Desktop-/PWA-
  Ansichten aufnehmen, pushen/K5.
**Rücknahmegrenze:** persönliche Tabelle erhalten, neue Oberfläche/Operationen
zurücknehmen. Alte Task-Schreibaufträge dürfen persönliche Zustände nicht löschen.

## S6 – Drag-and-drop und manuelle Reihenfolge

**Voraussetzung:** S5 einschließlich persönlicher Revisionen grün.
**Dateien:** Backend/Client, `planning.py`, neue `ordering.py` im Tasks-Modul,
additive Migration, Tasks-UI/CSS; neu `tools/tasks/ordering_contract.py`,
`tests/e2e/tasks-ordering.spec.mjs`, Runner-Anbindung.
**Schnittstelle:** `moveTask({taskId, context:list|personal, targetEpicId?,
targetDate?, placement:{before:id}|{after:id}|{edge:start|end},
expectedTaskRevision?, expectedPlanRevision?, expectedOrderRevision,
idempotencyKey})` liefert neue Ordnungsrevision und die geänderte Task- beziehungsweise
Planrevision. Listenkontext verlangt Taskrevision, persönlicher Kontext Planrevision;
persönliches Umordnen ohne `targetDate` erhält das vorhandene Planungsdatum. Zielparameter sind kontextabhängig und gegenseitig validiert.
Gemeinsame Ordnung wird pro Liste, persönliche Ordnung pro Nutzer serialisiert;
so sind tagübergreifende persönliche Moves atomar. `sort=manual` ab S6.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S6-A1 | 120 Aufgaben, Nachbar über Seitengrenze, mehrere unsichtbare Aufgaben | Move verändert nur die Position der gewählten Aufgabe und gegebenenfalls deren Abschnitt. IDs/Menge unverändert; kein Verlust nicht geladener Zeilen. |
| S6-A2 | Move in leeren Abschnitt/an Anfang/Ende; falscher oder verschwundener Nachbar | Gültiges Ziel persistiert exakt; ungültiges Ziel liefert 409, fremdes Ziel keine Daten. Kein Teil-Move. |
| S6-A3 | Zwei gleichzeitige Moves mit derselben Ordnungsrevision | Genau einer erfolgreich, einer 409. Gleicher Idempotency-Key replayt denselben Move. Nach Reload stabile Ordnung. |
| S6-A4 | A ordnet eigenen Plan, B lädt Teamliste/eigenen Plan; Leser ordnet Teamliste | Persönlicher Move beeinflusst B nicht. Leser darf nur persönliche Ordnung ändern. Deadline/Status/Referenzen unverändert. |
| S6-A5 | Maus, Touch-Griff, Tastatur-/Menüalternative | Dieselbe Endreihenfolge über alle Eingabewege. Touch-Scroll funktioniert außerhalb des Griffs; Fokus bleibt am verschobenen Eintrag. |
| S6-A6 | Sortierung nach Fälligkeit statt Manuell | Kein aktiver gemeinsamer Drag-Griff; Benutzer kann explizit in manuelle Sortierung wechseln. Alte Aufgaben behalten initial ihre bisherige Reihenfolge. |

**Arbeitsschritte:**
- [ ] A1–A3 zuerst gegen echte Transaktionen prüfen; deterministischen Altbestand
  für Backfill und konkurrierende Moves vorbereiten.
- [ ] Server-Move und Backfill, dann Pointer-/Tastatur-UI auf derselben Operation.
- [ ] K1–K4; Desktop-/PWA-Vorher/Nachher und Tastaturnachweis dokumentieren, Push/K5.
**Rücknahmegrenze:** Positionsdaten erhalten, UI wieder auf created sortieren.
Ordnungsrevisionen dürfen nicht mit einem Revert zurückgesetzt werden.

## S7 – Priorität, Tags und Checklisten

**Voraussetzung:** S6 grün; kompakte Darstellung und Detailbearbeitung bleiben erhalten.
**Dateien:** Backend/Client, additive Migration, `task-editor.tsx`, Tasks-Zeilen/CSS;
neu `tools/tasks/structure_contract.py`, `tests/e2e/tasks-structure.spec.mjs`, Runner.
**Schnittstelle:** additive `Task`-Lesefelder `priority:none|high`, `tags:[{id,title}]`,
`checklist:[{id,text,done}]`. Neue Operation `setTaskStructure(taskId,
{priority,tagIds,checklist,expectedRevision,idempotencyKey})` teilt Task-Revision.
Tags gehören einer Liste: `createTaskTag(listId,{title,idempotencyKey})`, Titel
1–40 Zeichen, normalisierte Namen eindeutig. Maximal 20 Tags und 100 Schritte
je Aufgabe, Schrittext 1–500 Zeichen. Bestehendes updateTask lässt neue Struktur
unverändert. Kein automatisches Erledigen der Aufgabe bei voller Checkliste.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S7-A1 | Neue Aufgabe ohne Zusatzdaten | Keine leeren Badges/Checklistenblöcke; Verhalten und Dichte von S1/S2 bleiben erhalten. |
| S7-A2 | Priorität, zwei Tags, drei Schritte speichern/reloaden | Alle Werte/IDs erhalten; 2 erledigte Schritte zeigen 2/3. 3/3 setzt nicht automatisch Task-Status done. |
| S7-A3 | Tag einer fremden Liste, doppelte Schritt-ID, leere Texte, Mengenlimit | Auftrag ohne Teiländerung abgelehnt; kein fremder Tagname im Fehler. |
| S7-A4 | Strukturänderung parallel zu bestehendem Task-Editor; alter Client speichert | Revision verhindert Überschreiben; alter Client ohne neue Felder löscht keine Struktur. |
| S7-A5 | Tag-/Prioritätsfilter über 120 Aufgaben | Serverseitige Filter vor Pagination, exakt erwartete IDs. Leser kann Struktur nur lesen. |

**Arbeitsschritte:**
- [ ] A3/A4 als Contract-Nachweise, A1/A2 als Browserfälle hinzufügen.
- [ ] Additive Daten/Operationen und zurückhaltende Details liefern; Filterfelder
  `priority` und `tagId` dem bestehenden TaskQuery ergänzen.
- [ ] K1–K4, Altclient-/Migrationstest; Desktop-Zeile und mobile Details, Push/K5.
**Rücknahmegrenze:** Zusatzdaten bewahren. Alte UI darf ignorieren, aber nicht löschen.

## S8 – Wiederholungen

**Voraussetzung:** S7 bestanden; bestehende Outbox-/Worker-Verträge gelesen.
**Dateien:** Backend/Client, neue `src/leonaid/modules/tasks/recurrence.py`, Tasks-
Jobregistrierung im vorhandenen Modul-Bootstrap, additive Migration;
neu `tests/unit/test_task_recurrence.py`, `tools/tasks/recurrence_contract.py`,
`tests/e2e/tasks-recurrence.spec.mjs`; bestehende K2-/K3-Runner verdrahten.
**Schnittstelle:** `TaskSeries {id,listId,mode:calendar|after_completion,
frequency:daily|weekly|monthly,interval:1..365,anchorLocalDate,timeZone,
untilDate:null|date,paused,revision}`. Template kopiert Titel, Beschreibung, Zuordnung, Priorität und Tags;
Checklisten erhalten neue IDs und offene Schritte, niemals persönliche Pläne oder
Erinnerungen. Eine Deadline wird aus `dueOffsetDays:0..365|null` und optionaler
lokaler Uhrzeit relativ zum Vorkommen erzeugt, nicht als altes absolutes Datum
kopiert. Ohne Uhrzeit gilt 23:59 lokal; DST-Lücke nimmt den ersten gültigen Zeitpunkt
danach, doppelte Uhrzeit das frühere UTC-Vorkommen. `createTaskSeries`, `updateTaskSeries` mit den
üblichen Schreibmetadaten. `untilDate` inklusive; genau ein Nachfolger pro
abgeschlossenem Vorkommen. Kalendertermine sind Tagesdaten, monatlicher Anker
bleibt erhalten. Serienvorkommen eindeutig über `(seriesId, occurrenceKey)`.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S8-A1 | Monatlich ab 31.01.2026, Intervall 1, bis 31.03. | Exakt 31.01., 28.02., 31.03.; kein 28.03., kein Aprilvorkommen. |
| S8-A2 | Täglich in Europe/Berlin über März/Oktober-Zeitwechsel | Pro lokalem Kalendertag genau ein Vorkommen, keine 24h-Drift; invalides IANA/Intervall/Ende abgelehnt. |
| S8-A3 | Zwei Worker verarbeiten Termin; Prozessabbruch nach Commit vor Ack | Unique-Key und Receipt verhindern zweite Aufgabe. Retry liefert bestehendes Vorkommen, keine zusätzliche Auditwirkung. |
| S8-A4 | After-completion: zweimal derselbe Abschluss, anschließend Wiederöffnen | Genau ein Nachfolger; erneutes Abschließen desselben Vorkommens erzeugt keinen weiteren. Offene Vorgänger erzeugen nichts. |
| S8-A5 | Serie pausieren/ändern/beenden, bereits erzeugte Aufgaben existieren | Vorhandene Aufgaben/Historie unverändert; zukünftige Jobs folgen neuer Serienrevision, pausierte/beendete Serie erzeugt nichts. |
| S8-A6 | Ausfall mit 250 verpassten Terminen; Bearbeitungsrecht entzogen | Catch-up maximal 50 Vorkommen pro Claim, Fortsetzung dauerhaft gespeichert. Nach Rechteentzug pausiert weitere Erzeugung; keine unberechtigte Arbeit. |
| S8-A7 | Template mit erledigten Schritten und Fälligkeitsabstand +2 Tage | Neues Vorkommen offen, neue offene Schritt-IDs; Fälligkeit relativ zum neuen Vorkommen. Persönliche Pläne/Reminder werden nicht kopiert. |
| S8-A8 | Deadline 02:30 lokal am 29.03. bzw. 25.10.2026, Europe/Berlin | DST-Lücke wird 03:00 lokal; doppelte Uhrzeit wird 02:30 mit UTC+02:00. Jeweils genau ein Fälligkeitszeitpunkt. |

**Arbeitsschritte:**
- [ ] Kalenderfälle in K4 zuerst schreiben und ausführen; Konkurrenz-/Crashfall
  in K2/W mit echten Workersignalen und Datenbankgrenzen ergänzen.
- [ ] Domainregel, Serienpersistenz und bestehenden Worker verdrahten, dann UI.
- [ ] K1–K4/W, Serienkonfiguration und entstandene Aufgaben auf Web/PWA aufnehmen,
  Versuch-/Vorkommenszählung im Beleg, Push/K5.
**Rücknahmegrenze:** Serien vor Entfernen ihrer Handler pausieren. Existierende
Vorkommen und Serienhistorie behalten; kein Revert durch Löschen von Aufgaben.

## S9 – Persönliche Erinnerungen

**Voraussetzung:** S8/Worker-Gate grün. Bestehender SMTP-Transport und Mailpit im
isolierten Teststack; kein neuer Benachrichtigungsdienst.
**Dateien:** Backend/Client, neue `src/leonaid/modules/tasks/reminders.py`, additive
Migration, Task-Details, bestehende Workerregistrierung; verwenden
`src/leonaid/adapters/mail/transport.py`; neu `tools/tasks/reminder_contract.py`,
`tests/e2e/tasks-reminders.spec.mjs`, Runner-Anbindung.
**Schnittstelle:** `TaskReminder {id,taskId,remindAt:UTC,channel:email,revision,
status:pending|sending|sent|unknown|cancelled|failed}`. Eigene Operationen
`setTaskReminder({taskId,remindAt,channel,emailOptIn,expectedRevision,idempotencyKey})`
und `cancelTaskReminder({id,expectedRevision,idempotencyKey})`, Actorgebunden.
Explizites E-Mail-Opt-in (`emailOptIn=true`, sonst 422),
initial eine aktive Erinnerung pro Actor/Aufgabe; maximal 365 Tage im Voraus.
Retry nur bei nachweislich nicht angenommener Nachricht, maximal fünf Versuche
mit Backoff 1/5/30/120 Minuten nach den vier Fehlschlägen. Gleichbleibende Message-ID
zur Diagnose, keine Behauptung einer SMTP-Deduplikation. Unklare Annahme oder Crash
nach Sendebeginn ergibt unknown; kein automatischer Zweitversand.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S9-A1 | Kein Opt-in, Erinnerung setzen; danach ausdrücklich aktivieren | Ohne Einwilligung kein Versandauftrag; nach Opt-in genau ein pending-Datensatz plus Outbox-Eintrag in einer Transaktion. |
| S9-A2 | Zeitpunkt erreicht, zwei Claims und identischer Retry | Ein bestätigter Zustellvorgang in Mailpit, Zustand sent. Kein Inhalt/Token im Diagnosebeleg. |
| S9-A3 | Termin geändert/storniert, Aufgabe erledigt oder Zugriff vor Claim entzogen | Veraltete Revisionen versenden nicht; aktuelle Berechtigung/Status unmittelbar vor Zustellversuch geprüft. |
| S9-A4 | Sicherer Fehler vor Annahme, danach wieder erreichbar | Persistierte Versuche/next-at stimmen mit Backoff überein; nach fünf erfolglosen Versuchen failed, keine Endlosschleife. |
| S9-A5 | Verbindung nach möglicher SMTP-Annahme verloren oder Worker stirbt nach Sendebeginn | unknown bleibt sichtbar, kein automatischer Retry. Bewusstes erneutes Senden warnt vor möglichem Duplikat und verwendet einen neuen Auftrag. |
| S9-A6 | A/B und Leser, vergangener Zeitpunkt, naive Zeit ohne Zone | Nur eigener Reminder les-/änderbar; Leser mit Task-Leserecht darf sich erinnern. Ungültige Zeit 422; Entzug unterbindet auch Replay. |

**Arbeitsschritte:**
- [ ] A3–A5 über reale Zustell-/Persistenzgrenzen nachweisen; keinen Mock-HTTP-
  Erfolg als Beweis für SMTP verwenden. Unklare Zustellung als eigenen Fall führen.
- [ ] Reminder, Outbox und vorhandenen Transport verbinden, UI-Opt-in/Status liefern.
- [ ] K1–K4/W; Web/PWA-Opt-in und unknown-/failed-Zustand aufnehmen, Zustelllog
  ohne Geheimnisse zuordnen, Push/K5.
**Rücknahmegrenze:** pending-Jobs pausieren/canceln, Zustellhistorie und unknown
bewahren. Bereits versendete E-Mail ist nicht rücknehmbar. Rechteänderungen nach
SMTP-Annahme können die schon versendete Nachricht nicht zurückholen.

## S10a – Persönlicher Kalenderfeed

**Voraussetzung:** S9 abgeschlossen; persönlicher Read-Scope aus S5 verwendbar.
**Dateien:** Backend/Client, neu `src/leonaid/modules/tasks/calendar_feed.py`,
additive Migration für widerrufbare Feed-Zugänge, Tasks-Einstellungen;
neu `tools/tasks/calendar_contract.py`, `tests/e2e/tasks-calendar.spec.mjs`, Runner.
**Schnittstelle:** `registerTaskCalendarFeed({token,expectedRevision,idempotencyKey})`
liefert Feed-ID/Revision; `revokeTaskCalendarFeed({expectedRevision,idempotencyKey})`.
Der authentifizierte Browser erzeugt vor Registrierung 32 kryptographisch zufällige
Bytes und hält Token/URL bis zum Abschluss nur im Speicher. Backend und Receipts
persistieren nur Digest/Metadaten, keine Token-URL. Der Fingerprint des Auftrags
verwendet den Digest. Identischer Retry registriert dasselbe Token; bei Verlust
der lokalen URL kann der Nutzer den Feed widerrufen und neu erstellen. Ein aktiver
Feed pro Actor, Ersetzung widerruft den alten atomar. Initiale Revision 0,
Widerruf/Ersetzung behalten einen Revisionsträger. Feed ist nur lesendes iCalendar,
pro Task/Typ stabile UID; ganztägige Planung und zeitgenaue Deadline getrennt
beschriftet. ETag berücksichtigt auch Zugriffsrevisionen; Cache-Control: no-store.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S10a-A1 | Geplant und fällig; Feed zweimal abrufen | Valides iCalendar, stabile eindeutige UIDs, korrekte All-day-/UTC-Werte und Textescaping; keine Reminder oder Pläne anderer Nutzer. |
| S10a-A2 | Task-Recht entzogen, erneut mit altem ETag abrufen | Widerrufene Aufgabe fehlt; kein veraltetes 304 mit vertraulichem Inhalt. |
| S10a-A3 | Feed widerrufen und alte Token-URL abrufen | Sofort generische 404; neuer Feed hat neues Token. Token weder im Server-/Proxylog noch in PR-Aufnahmen. |
| S10a-A4 | UI-Link kopieren, Konfiguration und Widerruf per Tastatur/PWA | Handlung verständlich, Token nur bei Erstellung sichtbar; Widerruf auch nach Reload erreichbar. |

**Arbeitsschritte:**
- [ ] A1–A3 zuerst im echten HTTP-Vertrag und mit unabhängiger iCalendar-Prüfung.
- [ ] Feed-Readmodel, Digest/Widerruf und Logging-Ausnahme implementieren, UI ergänzen.
- [ ] K1/K2/K3, Web/PWA-Konfiguration nach ausgeblendeter Token-Ausgabe aufnehmen;
  Logprüfung dokumentieren, Push/K5.
**Rücknahmegrenze:** Feeds widerrufen; externe Kalenderkopien lassen sich nicht
zurückrufen. UI erklärt das vor Freigabe. Keine bidirektionale Synchronisation.

## S10b – Begrenzte Mehrfachaktionen

**Voraussetzung:** S10a separat abgenommen; Status-/Planungsoperationen bestehen.
**Dateien:** Tasks-UI/CSS, bei serverseitigem Batch Backend/Client;
neu `tools/tasks/batch_contract.py`, `tests/e2e/tasks-batch.spec.mjs`, Runner.
**Schnittstelle:** explizite Auswahl maximal 50 Task-IDs. Aktionen done, defer oder
set-plan nutzen vorhandene Fachoperationen mit Revision/Key je Eintrag, maximal
vier gleichzeitige Requests. Kein generischer neuer Batchdienst nötig.
Ergebnis je ID `succeeded|conflict|forbidden|unknown`; erneuter Versuch verwendet
nur fehlgeschlagene/unklare Aufträge, bei unknown denselben Key und Inhalt.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S10b-A1 | 120 Ergebnisse, 3 explizit ausgewählt, „Abschließen“ | Nur die drei IDs ändern sich. „Alle“ bezeichnet sichtbar die geladene Auswahl, keine unsichtbare globale Menge; Auswahlzahl vor Auslösen erkennbar. |
| S10b-A2 | 1 Erfolg, 1 konkurrierende Änderung, 1 Rechteentzug | Getrennte Ergebnisse, fremde Felder unverändert. Wiederholung führt erfolgreichen Auftrag nicht erneut aus. |
| S10b-A3 | Verbindung bei einem Auftrag nach Commit verloren | unknown separat, identischer Retry liefert Receipt; kein doppelter Vorgang. Maximal vier laufende Requests. |
| S10b-A4 | Filterwechsel, 51. Auswahl, Escape, mobile Auswahlleiste | Filterwechsel beendet/verlangt sichtbare Klärung der Auswahl; Limit wird vor Auftrag durchgesetzt. Auswahlleiste verdeckt keine letzte Zeile/Navigation. |

**Arbeitsschritte:**
- [ ] A1–A3 mit echten Operationen/Receipts vorbereiten und Fehlerausgänge prüfen.
- [ ] Auswahl und begrenzte Ausführung verbinden; keine neue API wenn die
  vorhandenen Fachoperationen denselben Vertrag erfüllen.
- [ ] K1/K2/K3; Desktop-/PWA-Auswahl und gemischtes Resultat aufnehmen, Push/K5.
**Rücknahmegrenze:** UI entfernbar; bereits ausgeführte Einzeländerungen behalten.
Eine Batchaktion ist keine behauptete globale Transaktion oder globale Rücknahme.

## S11 – Gesamtabnahme des Ausbaus

**Voraussetzung:** S5–S10b mit allen Kriterien und eigenen Belegen bestanden.
**Dateien:** sämtliche hier zugeordneten Tests/Runner, PROGRESS; Produktdateien nur
zur Behebung konkret dokumentierter Fehler. Kein neuer Featureumfang.
**Schnittstelle:** Kompatibilität aller früheren Task-/Wissens-/Inbox-Verträge und
sämtlicher neuer persönlicher/Worker-Operationen.

| ID | Gegeben / Aktion | Erwartetes, prüfbares Ergebnis |
| --- | --- | --- |
| S11-A1 | Befüllter Altbestand, alle Migrationen, alte/neue Clients | Alte Aufgaben vollständig erhalten; alte Updates löschen keine neuen Daten. Eine eindeutige Alembic-Spitze, Upgrade wiederholbar. |
| S11-A2 | Zwei Nutzer, Liste/Plan, Drag, Serie, Erinnerung, Feed und Batch zusammen | Keine persönliche Datenvermischung, gültige Rechte an jedem Zugriff, keine verlorenen Aufgaben/Termine; Fälle S5–S10b auf Abschlussstand bestanden. |
| S11-A3 | Worker-Ausfall, Neustart, unbekannte Zustellung, Pause und Rücknahme | Serien-/Erinnerungsregeln erhalten; kontrollierte Rücknahme auf vorhandenem Datenbestand dokumentiert, keine Down-Migration mit Datenverlust. |
| S11-A4 | Desktop-/Touch-/Tastaturmatrix und bestehende Module | K3 samt bestehenden Wissen-/Material-/Inbox-Fällen sowie reale mobile Tastaturprüfung grün; keine neue Button-/Formularflut. |
| S11-A5 | Abschluss-Commit, Belegtabelle und PR | K1–K5/W vollständig erfolgreich; jede Kriteriums-ID mit Beleg, keine offenen Plattformtests oder als Erfolg deklarierte Pending-Checks. |

**Arbeitsschritte:**
- [ ] Kriterienmatrix auf Vollständigkeit prüfen, konkrete offene Fälle ausführen.
- [ ] Upgrade, Rücknahmeprobe, integrierte Journeys und K1–K5/W abschließen.
- [ ] PROGRESS mit endgültigen Commit-/Screenshot-/CI-Links abschließen; erst dann S11 abhaken.
**Rücknahmegrenze:** Migrationen/Daten erhalten, neue Jobs kontrolliert pausieren,
Feedzugänge widerrufen. Bereits zugestellte Nachrichten/externe Kopien bleiben
außerhalb technisch möglicher Rücknahme.

## Deckungsprüfung dieser Spec

| Anforderung aus PLAN | Zuständiger Slice |
| --- | --- |
| Kompakte Zeilen, AppShell, Rechteprojektion, Abhaken/Undo | S1 |
| Schnellerfassung, progressive Details, Abschnitte verwalten, Navigation/Entwurf | S2 |
| Filter, Termine, Zeitzone, Gruppierung/Pagination | S3 |
| Plattform-/Modulregression und Gate vor Funktionsausbau | S4 |
| Persönliche Tagesplanung und Isolation | S5 |
| Manuelle Ordnung, Drag-and-drop, alternative Bedienung | S6 |
| Priorität, Tags, Checklisten | S7 |
| Serien und Vorkommen | S8 |
| Erinnerungen, Opt-in, Backoff und unklare Zustellung | S9 |
| Kalenderfeed und Widerruf | S10a |
| Explizite Mehrfachaktionen und Teilergebnisse | S10b |
| Migration, Rücknahme und gemeinsamer Abschluss | S11 |

Selbstprüfung vor Spec-Push: Produktumfang vollständig zugeordnet, jede ID eindeutig,
Abhängigkeiten ohne Zyklus, benannte Verträge zwischen Slices konsistent, keine
als bereits vorhanden ausgegebenen zukünftigen Tests, keine unbelegten Pass-Angaben.
