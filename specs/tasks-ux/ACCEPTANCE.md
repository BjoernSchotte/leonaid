# Aufgaben-UX: gemeinsame Abnahme und Nachweise

Diese Regeln gelten zusätzlich zu jedem einzelnen Slice in [SLICES.md](SLICES.md).
Produktumfang: [PLAN.md](PLAN.md). Umsetzungsstand und tatsächlich bestandene
Prüfungen stehen in [PROGRESS.md](PROGRESS.md). Testpfade mit „neu“ werden im
zugehörigen Slice angelegt; ihre Nennung allein ist kein Abnahmenachweis.

## Einheitlicher Abschlussvertrag

Ein Slice ist abgeschlossen, wenn seine nummerierten Kriterien bestanden sind,
die tatsächlich geänderten Pfade geprüft wurden, die Browseraufnahmen betrachtet
und am angeforderten Draft-PR angehängt sind und seine Commit-CI grün ist.
Ein erfolgreicher Vorgänger, Screenshot oder Build ersetzt keine fachliche Prüfung.
Bei S4/S11 muss die gesamte Commit-CI einschließlich bestehender Regressionen grün
sein. Bei anderen Slices gelten alle vom PR verlangten Checks; Infrastrukturfehler
werden diagnostiziert und wiederholt, nicht als bestanden umbenannt.

- Vor Beginn: Vorgänger-Commit/Abnahme lesen; vorhandene Verträge und Migration-Head
  prüfen. Bestehende fremde Änderungen erhalten. Kein Implementierungsstart durch
  diese Dokumentationsänderung.
- Zuerst einen konkreten fehlenden Verhaltensnachweis ergänzen und ausführen.
  Er muss wegen des benannten fehlenden Verhaltens scheitern, nicht wegen Syntax,
  fehlender Umgebung oder eines fehlgeschlagenen Service-Starts.
- Kleinste durchgängige Änderung implementieren, denselben Nachweis grün bekommen,
  dann die dem Slice zugeordneten Prüfungen und Browserfälle abschließen.
- Pro Kriterium Ergebnis und Beleg speichern. Fehlende Umgebung/Plattform wird als
  offen dokumentiert. Keine stillen Skips, kein Abschalten einer Regression.
- Commit und Push nach abgeschlossener lokaler Abnahme; CI-Ergebnis danach dem
  gleichen Commit zuordnen. Der Nachfolgeslice startet erst nach seinem Gate.
- Abnahmeliste und Nachweise in `specs/tasks-ux/PROGRESS.md` führen; diese Datei erst
  beim ersten Implementierungsslice anlegen. Screenshots bleiben PR-Anhänge,
  Cookies, Tokens und Traces mit Sitzungsdaten bleiben lokal.

## Wiederverwendbare Prüfkommandos

Vom Repository-Root ausführen. Dies sind vorhandene Runner, keine bereits in
zukünftige Funktionen integrierten Tests. Neue Dateien eines Slices müssen in
`tools/schema/test.sh` beziehungsweise `tools/testing/modular_browser.sh` aufgenommen
werden, bevor dessen Gate als bestanden gelten kann. Keine neue Testplattform.

**K1 – Types, Format und Dokumentverträge:**

```sh
rtk proxy sh tools/ci/lint-types.sh
rtk proxy python3 tools/ci/no_test_doubles.py
rtk git diff --check
```

Erwartet: jeweils Exit 0; generierter Client entspricht der API, keine Test-Doubles.
K1 verwendet die gepinnten Toolchains. Nach UI/API-Änderungen ergänzend das bestehende
Build-Gate; das CI-Build darf nicht durch einen lokalen Typecheck ersetzt werden.

**K2 – echte Datenbank-/HTTP-/Fachoperationen:**

```sh
rtk proxy sh tools/schema/test.sh
```

Erwartet: Exit 0 einschließlich der vorhandenen Tasks-Schema-, Service-, HTTP-
und Aktionsverträge. Neue Vertragsdateien laufen im selben isolierten Stack und
prüfen echte Postgres-Transaktionen; Migrationsprüfung gehört zu K2.

**K3 – Web/PWA und Modulregression:**

```sh
rtk proxy env -u LEONAID_TEST_STACK -u LEONAID_CI_FIXTURE python3 tools/testing/shared_stack.py core tools/testing/modular_browser.sh
```

Erwartet: Exit 0, sämtliche registrierten Fälle bestanden, eigener Stack entfernt.
Keine Nutzung eines zufällig laufenden Benutzerstacks. Ein selektiver Fehlerlauf
ist zur Diagnose erlaubt, ersetzt aber nicht K3 zum Slice-Abschluss.

**K4 – deterministische Domainfälle und Migrationen:**

```sh
rtk proxy ./leonaid test-unit
```

Erwartet: Exit 0; im jeweiligen Slice neu definierte Domainfälle enthalten.
Kalenderfunktionen erhalten explizite Datum-/Zeitzonenparameter. Sie benötigen
keinen austauschbaren Test-Server oder gemockte Persistenz.

**K5 – gepushter Commit:**

```sh
rtk proxy gh pr view 7 --json headRefOid,isDraft
rtk proxy gh pr checks 7
```

Erwartet: Head ist der geprüfte Commit, Draft bleibt bestehen, erforderliche Checks
sind erfolgreich. Pending ist kein Erfolg. S4/S11 ordnen auch zusätzliche
Migrations-/Workerbelege explizit dem Abschluss-Commit zu.

**W – Worker-/Zustellbeleg:** ab S8 die dort benannten Vertragsprogramme über K2
verdrahten; vorhandenen Worker und dessen echte Outbox verwenden. S9 nutzt Mailpit
im isolierten Stack. Logs belegen Job-ID, Statusfolge, Anzahl und Zeitpunkte der
Versuche ohne Nachrichteninhalt oder Zugangsdaten. Keine Zeitmessung durch lange
Sleeps: fällige synthetische Jobs anlegen, Sperren/Claims und Persistenz beobachten.

## Nachweis pro Kriterium

In PROGRESS.md pro Slice eine Tabelle mit `Kriterium | Commit | Prüfung/Testfall |
Erwartung | Ergebnis | Beleg`. Ergebnis ist `bestanden`, `fehlgeschlagen` oder
`offen`, nie pauschal „getestet“. Zum Beispiel muss `S1-A3` die zwei konkurrierenden
Sitzungen, den 409 und die danach unveränderten Felder belegen. Die PR-Kommentare
nennen die abgebildeten Kriterien und die tatsächlichen Desktop-/Touch-Viewports.

### Kleines ausführbares Muster für den Layoutnachweis

Im bestehenden Playwright-Fall nach realem Login und Task-Anlage ergänzen;
`page` ist die echte Browserseite. Dieser Code ersetzt nicht die übrigen Kriterien.

```js
await expect(page.getByRole('checkbox', { name: 'Aufgabe abschließen: Probe' })).toBeVisible();
const box = await page.getByRole('checkbox', { name: 'Aufgabe abschließen: Probe' }).boundingBox();
expect(box.width).toBeGreaterThanOrEqual(44);
expect(box.height).toBeGreaterThanOrEqual(44);
expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
```

Die Checkbox darf eine kleinere sichtbare Markierung haben. Der DOM-Trefferbereich
muss im Touch-Kontext die gemessene Größe besitzen.

## Globale Kriterien


### Browser und Darstellung

- Desktop bei 1440 × 900 sowie 1024 × 768, Touch-PWA bei 390 × 844 und schmalem
  320-px-Viewport. 200 % Zoom beziehungsweise entsprechend reduzierte Breite,
  lange deutsche Titel, 0/1/viele Aufgaben, unzugewiesene Personen und fehlende
  Termine prüfen. Kein horizontaler Seitenscroll, kein abgeschnittener Fokus.
- Mobile: Erste Aufgaben stehen vor Listenverwaltung; Detailansicht und Tastatur
  verdecken keine erforderliche Aktion. Touch-Trefferflächen nachmessen.
- Gemeinsame Textbuttons: Desktop-Mindesthöhe 40 px, Touch mindestens 44 × 44 px;
  Icon/Text nebeneinander und lange Beschriftungen ohne Abschneiden. Aufgaben,
  Wissen und Materialien als tatsächliche Verbraucher prüfen.
- Native Checkbox-/Button-/Formularsemantik, sichtbarer Fokus und verständliche
  Namen. Alle Aktionen ohne Maus ausführbar. Kein ausschließlich farblicher Status
  und keine ausschließlich per Hover oder Wischgeste zugängliche Funktion.
- Echte Abläufe: anlegen, Details öffnen, ändern, abhaken, rückgängig machen,
  zurückstellen, wiederfinden, suchen, Ansicht wechseln, Browser-Zurück, Neuladen,
  Direktlink und Aufgabe aus einer Wissensseite öffnen.
- Aufnahmen je Slice zeigen die veränderten Zustände, mindestens Desktop-Liste
  und PWA-Liste; bei S2 zusätzlich Details, bei S3 Abschnitte/Terminansicht.

### Daten und Rechte

- Zwei echte Sitzungen: konkurrierende Änderungen und Status-Rückgängig ergeben
  einen verständlichen Konflikt statt verlorener Felder. Identischer Retry
  erzeugt keine zweite Operation. Erfolg, Fehler und unklarer Ausgang getrennt.
- Eigentümer/Bearbeiter/Leser, aktionsgebundene und eigenständige Liste sowie
  Rechteentzug nach dem Laden. Leser sehen keine Controls zum Ändern gemeinsamer
  Aufgaben; entsprechende direkte API-Aufrufe bleiben gesperrt. Eigene Planung
  ab S5 ist davon ausdrücklich getrennt. Fremde Listen/Personen/Referenzen werden nicht
  durch Labels, Suche oder Navigation offengelegt.
- Aufgaben jenseits der ersten Ergebnisseite, gleiche Fälligkeiten/Epic-Titel,
  NULL-Werte, Abschnitt über Seitengrenze und mindestens 120 synthetische Aufgaben.
  Exakte Ergebnismenge, keine Duplikate bei unverändertem Datenbestand.
- Lokale Mitternacht, Sommer-/Winterzeitwechsel und fällige zugleich
  zurückgestellte Aufgabe. Abhaken/Zurückstellen verändert Fälligkeit nicht.
- Bestehende Wissens-/Inbox-Verweise und Aufgabenanlage aus Wissen weiter testen.
  Keine gemockten Serverantworten als Ersatz für diese Integrationsnachweise.

### Zusätzliche Abnahme für S5–S11

- Zwei Nutzer planen dieselbe Aufgabe an verschiedenen Tagen und sortieren sie
  unterschiedlich. Kein Einfluss auf den anderen Plan oder die gemeinsame
  Fälligkeit/Zuständigkeit. Leser planen persönlich, können aber nicht gemeinsam
  umsortieren oder abhaken. Rechteentzug entfernt alle persönlichen Sichtpfade.
- Heute/übernommene offene Planung/Irgendwann und Zeitzonenwechsel; keine doppelten
  Einträge zwischen Plan und Fälligkeitshinweisen. Erledigen und Wiederöffnen
  zeigen einen konsistenten Plan ohne stilles Löschen persönlicher Daten.
- Drag-and-drop und gleichwertige Tastatur-/Menübedienung auf Desktop/Touch,
  Bewegung über Abschnitte/geladene Seiten, Filter, konkurrierende Moves und
  fehlender Nachbar. Alle Aufgaben bleiben genau einmal vorhanden.
- Wiederholungen bei Monatsende und Sommerzeit, parallele Worker, Crash nach
  Commit, Retry und Serienpause. Genau ein Vorkommen pro vorgesehenem Termin.
- Erinnerungen nach Änderung, Erledigen und Rechteentzug unterdrücken; Retries
  und unklare Zustellung ohne unkontrollierte Duplikate nachweisen. Zeitsteuerung
  mit realen Persistenz-/Workergrenzen testen, nicht durch Browser-Mockantworten.
- Kalenderfeed nach Tokenwiderruf/Rechteentzug; Mehrfachaktion mit gemischten
  Erfolgen/Konflikten. Dokumentierte Datenmigration von bestehenden Aufgaben und
  fachlich nachvollziehbare Rücknahme pro neuem Slice.

### Abschluss und Rücknahme

Bestehende Type-/Lint-/Contract-Gates sowie Modulbrowserlauf verwenden und gezielt
erweitern. Abnahme dokumentiert Commit, Befehle, Ergebnis und Screenshot-Kommentar;
laufende CI wird nicht als bestanden gemeldet. Kein Teststack mit anderen lokalen
Installationen vermischen. Nur selbst erzeugte Ressourcen zurücknehmen.

Für S1–S4 bleiben Datenmodell und Schreibverträge unverändert; die UI kann auf den
vorherigen Stand zurückgenommen werden. Additive Lesefelder/-filter dürfen dabei
zunächst bestehen bleiben; persistierte Aufgaben und Zuordnungen werden nicht
gelöscht oder konvertiert. Ein Revert erfordert den üblichen Vertrags- und
Modulregressionstest, keinen Reset von Volumes oder Nutzerdaten.

Für S5–S11 Migrationen additiv anlegen und neue Daten bei UI-Rücknahme erhalten.
Neue Serien/Erinnerungsjobs vor Rücknahme ihrer Verarbeitung kontrolliert pausieren;
keine hängenden Zustellungen und kein stiller Verlust persönlicher Planung.
Alte Anwendungen dürfen neue Attribute ignorieren, aber nicht überschreiben.
Destruktive Down-Migrationen sind kein regulärer Rollback. Der jeweilige Slice
muss seine konkrete Kompatibilitätsgrenze und den Rücknahmeweg dokumentieren.
