# Aufgabenverwaltung: kompakte Listen und fokussierte Bearbeitung

Status: Umsetzungsspec, noch nicht implementiert. Beauftragt am 14.09.2026.
Ausgangsstand: `6f2123d` auf Draft-PR #7. Der Wissenseditor ist separat in
[`knowledge-editor`](../knowledge-editor/PLAN.md) dokumentiert.

## Ziel und Grenzen

LeonAid erhält eine aufgabenorientierte Desktop- und PWA-Oberfläche, inspiriert
von der bereitgestellten Things-Abbildung: kompakte Aufgabenzeilen, ruhige
Abschnitte, direktes Abhaken und Details auf Anforderung. Die gemeinsame deutsche
Produktoberfläche und ihre berechtigungsabhängige AppShell bleiben Grundlage.
Auch ältere Mitglieder sollen Aufgaben gut lesen und sicher treffen können,
ohne dass große farbige Buttons den Inhalt verdrängen.

Die erste Ausbaustufe umfasst Layout, Schnellerfassung, Bearbeitung, Filter,
Gruppierung und kleine Erweiterungen der vorhandenen Fach-API. Darauf folgen
persönliche Tagesplanung, Drag-and-drop und zusätzliche Aufgabenfunktionen als
eigene Slices mit separater Abnahme.
Kein neuer Dienst, Queue-System, UI-Framework oder generisches Plugin-System.
Die bestehenden Revisionen, Idempotency-Receipts und Rechteprüfungen gelten weiter.

In S1–S4 noch nicht enthalten: persönliche Tagesplanung, Kalenderintegration,
Erinnerungen, Wiederholungen, Tags/Prioritäten, Checklisten, Drag-and-drop und
Massenbearbeitung. Diese folgen in der zweiten Ausbaustufe. Nicht Bestandteil
beider Stufen sind Offline-Schreibwarteschlangen, neue Realtime-Infrastruktur
oder ein weiterer Umbau des Wissenseditors und anderer Fachmodule.

## Verifizierter Ausgangsstand

| Bereich | Bestand | Zu schließender Gap |
| --- | --- | --- |
| Aufgabenliste | Titel, volle Beschreibung, Status-/Datumsblock, Bearbeiten-Button | Zeilen sind hoch; Zuständigkeit und Kontext fehlen in der Übersicht. |
| Erledigen | Bearbeitungsformular, Statusauswahl, Speichern | Eine alltägliche Aktion benötigt mehrere Schritte. |
| Mobile | Unter 760 px steht die Listen-Spalte vor der Aufgaben-Spalte. | Verwaltung verdrängt die eigentliche Arbeit. |
| Bearbeiten | Langes Formular oberhalb der Liste, inklusive Epic-Verwaltung | Liste verschiebt sich; seltene Felder dominieren. |
| Organisation | Listen, Aktionsbezug und listenbezogene Epics existieren. | Epics sind im Editor auswählbar, aber keine sichtbaren Listenabschnitte. |
| Filter | Für mich/alle, offen/erledigt, Suche, zurückgestellte einschließen | Terminansichten und ausschließlich zurückgestellte Aufgaben fehlen. |
| Datenabfrage | Rechtegeprüft, nach Erstellzeit/ID sortiert, Offset-Pagination | Gruppierung und Terminfilter müssen vor Pagination erfolgen. |
| Navigation | Einzelaufgabe über `?task=<id>`; übrige Filter in React-State | Filter und Listenposition gehen beim Navigieren/Neuladen verloren. |

Quellen im Repository:

- [`tasks.tsx`](../../packages/features/src/tasks/tasks.tsx)
- [`tasks.css`](../../packages/features/src/tasks/tasks.css)
- [`task-editor.tsx`](../../packages/features/src/tasks/task-editor.tsx)
- [`epic-picker.tsx`](../../packages/features/src/tasks/epic-picker.tsx)
- [`api.py`](../../src/leonaid/modules/tasks/api.py) und
  [`repository.py`](../../src/leonaid/modules/tasks/repository.py)
- [`PRODUCT.md`](../../packages/features/PRODUCT.md)

Die Referenz liefert die visuelle Richtung, kein zusätzliches Fachmodell.
Things blendet optionale Aufgabendetails erst bei Bedarf ein und verwendet
Überschriften zur Unterteilung von Projekten
([Produktbeschreibung](https://culturedcode.com/things/features/)).
Things trennt außerdem Arbeitsbeginn und Deadline
([Terminmodell](https://culturedcode.com/things/support/articles/2803579/)).
LeonAids `deferredUntil` bleibt eine Wiedervorlage; es wird nicht als persönliche
Planung für „Heute bearbeiten“ umgedeutet. S5 ergänzt hierfür einen eigenen,
nutzerbezogenen Planungszustand.

## Verbindliches Bedienkonzept

### 1. Aufgabenfläche und Navigation

- Desktop ab 1100 px: kompakte Modulnavigation und breite Aufgabenliste.
  Aufgabendetails öffnen rechts, sofern für die Liste mindestens 360 px bleiben;
  andernfalls als eigene Detailansicht. Keine dauerhaft leere Detailspalte.
- Unter 1100 px: kompakter Listen-/Ansichtswechsel im Kopf statt einer permanenten
  zweiten Navigation. Die AppShell behält ihre bisherigen Einträge und Rechte.
- PWA: Aufgaben direkt unter einem knappen Kopf; Listenanlage, Listenmitglieder
  und Abschnittsverwaltung stehen nicht vor der Liste. Listenwechsel öffnet eine
  fokussierte Auswahl, Verwaltung das Kontextmenü des aktuellen Objekts.
- Eine klar erkennbare Aktion „Neue Aufgabe“ mit Plus-Icon. Auf Touch gut
  erreichbar oberhalb der vorhandenen unteren Navigation, ohne Inhalt zu
  verdecken; entsprechende Inhaltsabstände und Safe Areas berücksichtigen.
- „Neue Liste“ öffnet ein Formular auf Anforderung. Mitgliedschaft und Zugriff
  bleiben über „Freigaben“ auffindbar, außerhalb des täglichen Aufgabenablaufs.
- Auswahl, Suche, Ansicht und Sortierung stehen in der URL. Die bestehende
  `?task=<id>`-Verlinkung bleibt gültig. Zurück schließt Details und stellt Filter,
  geladene Listenposition und Fokus wieder her; direkte Links erhalten einen
  verlässlichen Rückweg zur zugehörigen Liste.

### 2. Kompakte Aufgabenzeilen

Zeilenaufbau: Abschluss-Checkbox, Titel, dezente Metadaten, Kontextmenü.
Metadaten zeigen Zuständigkeit und Fälligkeit; übergreifende Ansichten zusätzlich
Liste/Aktion. Zurückgestellte Aufgaben nennen den Wiedervorlagezeitpunkt.
Beschreibungen werden in der Liste höchstens durch ein beschriftetes Icon
angedeutet. Keine vollständigen Beschreibungsblöcke oder wiederholten „Status“-
Labels. Überfälligkeit ist durch Text und Farbe erkennbar.

- Richtwerte: Text 16 px; Metadaten 14 px; Icons 18–20 px. Bestehende Tokens und
  freie Hugeicons verwenden. Keine Verkleinerung aller globalen Buttons.
- Desktop-Zeilen typischerweise 44–52 px, Touch-Zeilen etwa 56–64 px; bei langen
  Titeln oder größerer Schrift wachsen sie. Kein Abschneiden wesentlicher Inhalte
  durch feste Höhe und kein horizontaler Seitenscroll.
- Touch-Aktionen mindestens 44 × 44 CSS-px Trefferfläche. Die sichtbare Checkbox
  beziehungsweise das Icon darf kleiner sein; eine große Farbfläche ist unnötig.
- Titel/Zeile öffnet Details; Checkbox ändert ausschließlich den Status.
  Keine verschachtelten interaktiven Elemente, klare zugängliche Namen.
- Kontextmenü enthält passende Aktionen wie Details, Zurückstellen und Freigaben
  der Liste. Nicht verfügbare Fachoperationen werden nicht als Attrappen angeboten.
  Auf Touch sind Aktionen ohne Hover erreichbar.
- Vorhandene Daten bleiben während einer Aktualisierung sichtbar; Ladefehler,
  leere Liste und leeres Suchergebnis erhalten unterscheidbare Zustände.

### 3. Direktes Abhaken und Rückgängig

Der vorhandene `updateTask`-Aufruf bleibt der Schreibweg. Titel, Beschreibung,
Zuständigkeit, Epic, Fälligkeit und Wiedervorlage werden unverändert mitgeschickt;
nur `status` ändert sich. Die Mutation enthält die bekannte `expectedRevision`
und einen Idempotency-Key. Pro Aufgabe ist nur eine Statusmutation gleichzeitig
zulässig. Optional optimistische Anzeige muss bei Fehlern zurückgenommen werden.

Nach Erfolg wird die neue Revision übernommen. „Rückgängig“ stellt den vorherigen
Status mit dieser Revision und einem neuen Key wieder her. Eine zwischenzeitliche
Änderung darf nicht überschrieben werden. Bei unklarem Netzwerkausgang erfolgt
ein identischer Retry mit demselben Key; kein blindes zweites Toggle.
Bei Konflikt bleibt die Aufgabe sichtbar und der Nutzer erhält eine verständliche
Aktualisierungsaktion. Serverrechte entscheiden auch bei veralteter UI.
Die Rückgängig-Meldung ergänzt die dauerhaft erreichbare Wiederöffnung in
„Erledigt“; sie ist nicht der einzige Weg zurück.

### 4. Schnellerfassung und Details

- Schnellerfassung beginnt mit Titel und sichtbar bestätigtem Listenbezug.
  Innerhalb einer Liste ist diese vorausgewählt; übergreifend muss eine
  bearbeitbare Liste gewählt werden. Es entsteht keine versteckte neue Inbox.
- In „Für mich“ ist die eigene Person sichtbar vorausgewählt, sofern zuweisbar;
  sonst bleibt die Person unzugewiesen. Alle Defaults sind vor Speichern sichtbar.
- Zuständigkeit, Termin und Abschnitt sind bei Bedarf ergänzbar. Enter speichert
  die einzeilige Schnellerfassung, Escape schließt einen leeren Entwurf. Weitere
  Felder und vollständige Beschreibung liegen in der Detailansicht.
- Details zeigen Titel und Beschreibung zuerst, weitere Eigenschaften kompakt
  darunter. Personen-/Epic-Suche öffnet auf Anforderung; Anlegen/Umbenennen eines
  Abschnitts ist eine eigene Aktion, kein ständig sichtbarer Teil jedes Entwurfs.
- „Abschnitt“ ist die deutsche UI-Bezeichnung für das vorhandene listenbezogene
  Epic. Keine neue Hierarchiestufe oder Migration der fachlichen Identitäten.
- Speichern/Abbrechen bleiben eindeutig. Fehler und 409-Konflikte erhalten den
  Entwurf. Verlassen eines geänderten Entwurfs benötigt einen Verwerfschutz;
  Browser-Zurück, Escape und Schließen dürfen Änderungen nicht still verlieren.
- Desktop und PWA verwenden dieselben Formular-/Mutationskomponenten. Mobile
  Details sind eine eigene Ansicht; Bildschirmtastatur darf Speichern und Felder
  nicht hinter der unteren AppShell-Navigation verdecken.

### 5. Ansichten, Termine und Abschnitte

„Für mich“ versus „Alle zugänglichen“ ist ein unabhängiger Zuständigkeitsfilter,
innerhalb einer gewählten Liste weiterhin auf diese Liste begrenzt. Der Link zu
allen Aufgaben muss tatsächlich die entsprechende Ansicht öffnen.

| Ansicht | Exakte Bedeutung |
| --- | --- |
| Offen | Offene, aktuell nicht zurückgestellte Aufgaben |
| Heute fällig | Offene Aufgaben mit Fälligkeit innerhalb des lokalen heutigen Kalendertags, einschließlich zurückgestellter Aufgaben; deren Wiedervorlage bleibt sichtbar. |
| Demnächst fällig | Offene Aufgaben ab lokal morgen bis einschließlich des siebten folgenden Kalendertags, einschließlich zurückgestellter Aufgaben |
| Zurückgestellt | Offene Aufgaben mit `deferredUntil > now()` |
| Erledigt | Erledigte Aufgaben, unabhängig von Wiedervorlage |

Überfällige Aufgaben bleiben in „Offen“ erkennbar und bei Fälligkeitssortierung
oben. „Heute fällig“ wird nicht fälschlich als persönliche Tagesplanung bezeichnet.
Fälligkeit und Wiedervorlage bleiben getrennt; keine implizite Änderung des
Fälligkeitsdatums beim Zurückstellen.

- Tagesgrenzen aus der lokalen Zeitzone ableiten, als UTC-Intervall `[von, bis)`
  an die API senden. Sommerzeitwechsel nicht als feste 24-Stunden-Tage rechnen.
  Zeitzone im Terminpicker sichtbar machen; Datumswerte behalten ihre Zeitsemantik.
- Sortierung: Erstellreihenfolge (kompatibler Standard), Fälligkeit aufsteigend
  (ohne Fälligkeit zuletzt), Abschnitte innerhalb einer einzelnen Liste.
  Jeder Modus erhält stabile Tie-Breaker über Erstellzeit/ID.
- Abschnittsmodus ordnet nach Epic-Titel/ID, darunter nach Erstellzeit/ID;
  „Ohne Abschnitt“ zuletzt. Überschriften sind einklappbar. Keine frei verschiebbare
  Reihenfolge in S1–S4 und keine irreführenden Gesamtzähler aus nur einer Ergebnisseite.
- „Weitere laden“ erscheint nur, wenn weitere Ergebnisse vorliegen. Geladene
  Seiten werden angehängt; über Seitengrenzen fortgesetzte Abschnitte bleiben
  zusammenhängend. Filter-/Sortieränderungen und relevante Mutationen setzen
  Pagination konsistent zurück. Bestehende API-Limits bleiben sichtbar begrenzt.

## Technische Umsetzung und Verträge

Für S1–S4 gilt: Die Implementierung bleibt in `packages/features/src/tasks/` und
`src/leonaid/modules/tasks/`. Kleine gemeinsame Komponenten für Zeile,
Detailansicht und Navigation nur bei tatsächlicher Wiederverwendung extrahieren.
Bestehende AppShell, UI-Tokens, Query-Cache und API-Client nutzen.

Erforderliche additive API-Erweiterungen:

1. Listenprojektion für Aufgaben mit Anzeigenamen für Liste/Aktion, Person und
   Epic sowie `canEdit`; für auswählbare Aufgabenlisten ebenfalls `canEdit`.
   Rechte werden aus derselben Policy wie beim Schreiben abgeleitet. Labels in
   einem begrenzten Join/Bulk-Leseweg auflösen, keine Einzelabfrage pro Zeile.
   Keine Personensuche oder neuen Zugriffsrechte durch die Projektion eröffnen.
2. `TaskQuery`: optionale UTC-Fälligkeitsgrenzen `dueFrom`/`dueBefore`, Sortiermodus
   und Wiedervorlagefilter `active | deferred | all`. Grenzen validieren, inklusive
   `dueFrom < dueBefore`, sofern beide gesetzt sind. Bisherige Aufrufer behalten
   ihre Semantik: ohne neuen Filter bestimmt weiterhin `includeDeferred` das
   Verhalten. Widersprüchliche explizite alte/neue Filter werden zurückgewiesen.
3. Rechte, Suche, Zuständigkeit, Status, Termine, Wiedervorlage und Sortierung
   vollständig im Repository **vor** `LIMIT/OFFSET` auswerten. Keine Terminansicht
   und keine globale Gruppierung durch Filtern der ersten 50 Aufgaben im Browser.
   NULL-Fälligkeiten sind aus Terminansichten ausgeschlossen.
4. Schreibverträge bleiben unverändert. Kein separater Statusdienst oder
   duplizierter Rechtepfad. API-Client/OpenAPI über den vorhandenen Generator
   aktualisieren; alte direkte Fachaufrufe und Task-/Wissensverweise absichern.

Für S1–S4 ist keine Schemaänderung erforderlich; die zweite Ausbaustufe erhält
gezielte Migrationen für ihre tatsächlich benötigten Daten. Neue Indizes
nur bei nachvollziehbarem Bedarf aus realen Abfrageplänen ergänzen. Keine
Cache-/Suchinfrastruktur und keine vollständige Listenmaterialisierung einführen.

## Zweite Ausbaustufe: Planung und zusätzliche Funktionen

Diese Stufe beginnt erst nach der Abnahme von S1–S4. Neue Funktionen übernehmen
kompakte Zeilen und progressive Detailansichten; sie dürfen die Oberfläche nicht
wieder in ein dauerhaft sichtbares Formular verwandeln. Neue Daten/Operationen
liegen im vorhandenen Tasks-Modul, persönliche Daten sind dem aktuellen Actor
zugeordnet. Gemeinsame Änderungen benötigen weiterhin Schreibrechte an der Liste.

### Persönliche Tagesplanung

- „Heute“ bezeichnet ab S5 die persönliche Arbeitsplanung; „Heute fällig“ bleibt
  als eigene fachliche Terminansicht verfügbar. `dueAt`, `deferredUntil` und
  `plannedOn` sind getrennte Werte mit getrennten Bedienelementen.
- Nutzer können zugängliche offene Aufgaben für heute oder einen späteren Tag
  einplanen, auf „Irgendwann“ setzen oder die persönliche Planung entfernen.
  Das ändert weder Zuweisung noch Deadline, gemeinsamen Status oder Wiedervorlage.
- Minimaler Datensatz pro Nutzer/Aufgabe: Planungsdatum als lokales Kalenderdatum
  oder expliziter Zustand „Irgendwann“, Revision; ab S6 zusätzlich Reihenfolge.
  Keine Zeile bedeutet ungeplant. Einzigartigkeit über Nutzer/Aufgabe. Die
  Zeitzone für „heute“ wird explizit bestimmt; Kalenderdaten werden nicht als
  UTC-Mitternachtszeitpunkte gespeichert.
- „Heute“ enthält heute oder früher eingeplante, noch offene Aufgaben. Nicht
  erledigte Planung bleibt sichtbar, bis sie abgeschlossen oder umgeplant wird;
  das ursprüngliche Planungsdatum wird nicht automatisch überschrieben.
  „Geplant“ gruppiert zukünftige persönliche Termine nach Tag. „Irgendwann“ ist
  eine persönliche Sammlung ohne Kalenderdatum.
- Mir zugewiesene fällige Aufgaben, die noch nicht im heutigen Plan angezeigt
  werden, erscheinen in „Heute“ als
  getrennt beschrifteter Hinweisbereich „Heute fällig / Überfällig“, ohne dadurch
  einen Planungsdatensatz anzulegen. Aufgaben werden nicht doppelt angezeigt.
  Die Terminregeln von S3 gelten unverändert.
- Bewusst persönlich eingeplante Aufgaben bleiben trotz gemeinsamer Wiedervorlage
  im persönlichen Plan sichtbar und tragen deren Hinweis. Das Umplanen löscht
  die gemeinsame Wiedervorlage nicht stillschweigend.
- Auch Leser können eigene Planung für zugängliche Aufgaben pflegen; das ist
  keine Berechtigung, die Aufgabe abzuhaken oder zu ändern. Persönliche Pläne
  anderer Nutzer werden weder in Teamansichten noch in API-Projektionen gezeigt.
  Nach Rechteentzug verschwindet die Aufgabe auch aus dem persönlichen Plan.
- Eigene Fachoperationen zum Setzen/Entfernen der Planung und zum Lesen der
  persönlichen Ansichten; Actor aus der Sitzung, kein frei wählbarer Eigentümer.
  Revisionen, Idempotenz und serverseitige Filter/Pagination bleiben erforderlich.

### Drag-and-drop und Reihenfolge

- Zwei klar getrennte Kontexte: persönliche Reihenfolge im eigenen Tagesplan und
  gemeinsame Reihenfolge/Abschnittszuordnung innerhalb einer bearbeitbaren Liste.
  Die persönliche Reihenfolge wirkt sich nie auf Kollegen aus.
- Listenansichten erhalten einen expliziten Sortiermodus „Manuell“. Bei Sortierung
  nach Fälligkeit oder Erstellzeit wird keine frei verschiebbare Reihenfolge
  vorgetäuscht. Abschnittswechsel innerhalb derselben Liste sind möglich;
  Verschieben zwischen Listen bleibt zunächst außerhalb dieses Slices.
- Ein Move-Befehl bezeichnet Aufgabe, Zielabschnitt beziehungsweise Planungstag
  und einen vorhandenen Nachbarn (`before` oder `after`) beziehungsweise explizit
  den Anfang/das Ende eines Ziels, auch wenn es leer ist; keine vom Client
  behauptete vollständige Liste. Der Server bestimmt die globale Position,
  prüft Ziel/Nachbar/Rechte und serialisiert konkurrierende Änderungen pro
  gemeinsamer Liste oder persönlichem Tagesplan mit einer Ordnungsrevision.
- Einfache serververwaltete ganzzahlige Positionen mit begrenzter Neunummerierung;
  keine CRDTs oder generische Ranking-Bibliothek. Bestehende Aufgaben erhalten
  deterministische Anfangspositionen in ihrer bisherigen Erstellreihenfolge.
- Bei gefilterten Ansichten bleibt eine Bewegung relativ zum benannten Nachbarn;
  unsichtbare Aufgaben dürfen nicht verloren gehen oder implizit umsortiert
  werden. Seitengrenzen ändern die Identität des Ziels nicht.
- Desktop per Griff, Touch per bewusstem Griff/Long-press mit weiter funktionierendem
  Scrollen. Gleichwertige Menü-/Tastaturaktionen „Nach oben/unten“, „In Abschnitt“
  und „Für Tag planen“. Fokus und Screenreader-Rückmeldung folgen dem Ergebnis.
- Fehler/409 nehmen optimistische Bewegungen zurück und bieten Aktualisierung;
  Status, Deadline, Referenzen und persönliche Fremddaten bleiben unverändert.

### Weiterer Funktionsausbau

Die folgenden Slices sind eingeplant, werden aber einzeln geliefert. Sie nutzen
weiterhin das optimierte Layout und erhalten jeweils ihre eigene Vertrags- und
Browserabnahme. Kein gemeinsamer großer „Advanced Settings“-Block.

- **Priorität, Tags und Checklisten:** optionale einfache Priorität und
  listenbezogene Tags für gemeinsames Filtern; standardmäßig keine zusätzliche
  Metadatenflut. Checklisten sind benannte Schritte innerhalb einer Aufgabe mit
  stabilen IDs und Erledigt-Zustand, keine rekursive Unteraufgabenhierarchie.
  Autorisierung erfolgt über die Aufgabe, Fortschritt nur bei vorhandenen
  Schritten anzeigen. Alle Änderungen behalten Revisionen und Idempotenz.
- **Wiederholungen:** begrenzte Regeln für täglich, wöchentlich und monatlich,
  Intervall und Ende; feste Kalenderfolge und Wiederholung nach Abschluss werden
  explizit unterschieden. Ein nicht vorhandener Monatstag fällt auf den letzten
  Tag des Monats, ohne den ursprünglichen Ankertag zu verändern. Verpasste feste
  Vorkommen werden nach Ausfall in begrenzten Batches nachgeholt. Zeitzone gehört
  zur Serie; bei Abschlussfolgen gibt es höchstens einen Nachfolger pro Vorkommen. Pro Vorkommen genau eine Aufgabe durch eindeutigen Serien-/Terminbezug;
  keine Mutation erledigter Historie. Serie pausieren/beenden, Änderungen gelten
  standardmäßig für zukünftige Vorkommen. Persönliche Planung erzeugt keine Serie.
- **Erinnerungen:** persönliche Opt-in-Erinnerung mit explizitem Zeitpunkt und
  vorhandenem Benachrichtigungskanal; kein impliziter E-Mail-Versand. Die bestehende
  PostgreSQL-Outbox/Worker-Infrastruktur übernimmt Zeitsteuerung, begrenzte Retries
  und Backoff. Vor Zustellung Rechte, Status und aktuelle Konfiguration erneut
  prüfen. Bearbeiten/Erledigen/Rechteentzug verhindert veraltete Zustellungen.
  Idempotente Zustellung beziehungsweise Wiederabgleich bei unklarem Ausgang.
- **Kalender und Mehrfachaktionen:** zuerst ein widerrufbarer persönlicher,
  nur lesender Kalenderfeed für geplante/fällige Aufgaben, keine bidirektionale
  Fremdkalender-Synchronisation. Token-URLs sind Geheimnisse, werden nicht geloggt
  oder in Screenshots veröffentlicht; jeder Abruf respektiert aktuelle Rechte.
  Mehrfachaktionen beschränken sich zunächst auf Abschließen, Zurückstellen und
  eigene Planung. Explizite Auswahl statt unklarer „alle“-Semantik bei Pagination;
  jedes Ergebnis meldet Erfolg/Konflikt/fehlende Rechte ohne fremde Updates zu
  überschreiben. Begrenzte Batches verwenden bestehende Fachoperationen.

## Umsetzungsslices

Jeder Slice endet mit gezielten Tests, realem Desktop-/PWA-Browsernachweis,
visueller Prüfung, Commit und Push auf Draft-PR #7. Screenshots als Anhänge eines
PR-Kommentars veröffentlichen; keine gerenderten Mockups als Implementierungsbeweis.
Abhängige Slices beginnen erst nach erfolgreicher Abnahme ihres Vorgängers.

- [ ] **S1 – Aufgabenliste und Navigation:** responsive Aufgabenfläche, kompakte
  Zeilen, Metadaten-/Rechteprojektion, Listenverwaltung auf Anforderung, direktes
  Abhaken und Rückgängig. Vorhandene Filter zunächst fachlich unverändert.
- [ ] **S2 – Erfassen und Bearbeiten:** Schnellerfassung, fokussierte Details,
  optionale Eigenschaften, Abschnittsverwaltung, URL-/Zurück-/Fokusverhalten und
  Entwurfschutz. Bestehende Kontextverweise vollständig erhalten.
- [ ] **S3 – Ansichten und Struktur:** serverseitige Termin-/Wiedervorlagefilter,
  stabile Sortierung und Abschnittsgruppierung mit korrekter Pagination.
- [ ] **S4 – Abnahme der UX-Grundlage:** gemeinsame Abläufe, Grenzfälle und Rechte in Web/PWA,
  vollständige bestehende Modulregression, Screenshot-Beweise und CI. Voraussetzung
  für den Beginn der nachfolgenden Ausbaustufe.
- [ ] **S5 – Persönliche Planung:** eigene Zustände/Operationen und Ansichten
  Heute/Geplant/Irgendwann, ohne Deadline oder Teamzuordnung zu verändern.
- [ ] **S6 – Drag-and-drop:** persönliche und gemeinsame manuelle Reihenfolge,
  Abschnittswechsel, Tastatur-/Menüalternativen und Konfliktbehandlung.
- [ ] **S7 – Aufgabenstruktur:** Priorität, Tags und einfache Checklisten mit
  gezielten Filtern und zurückhaltender Darstellung.
- [ ] **S8 – Wiederholungen:** begrenzter Serienvertrag, idempotente Vorkommen,
  Pausieren/Beenden und echte Worker-/Kalendergrenzfalltests.
- [ ] **S9 – Erinnerungen:** persönliches Opt-in, vorhandener Zustellkanal,
  Outbox-Zeitsteuerung, Rechteprüfung und Wiederholungs-/Ausfallnachweise.
- [ ] **S10 – Kalender und Mehrfachaktionen:** zunächst Kalenderfeed, anschließend
  begrenzte Mehrfachaktionen als getrennte Teillieferungen mit eigener Abnahme.
- [ ] **S11 – Gesamtabnahme des Ausbaus:** Migrationen, Zusammenspiel aller Ansichten,
  persönliche Isolation, mobile Bedienung, Worker-Verhalten und vollständige CI.

## Abnahmekriterien

### Browser und Darstellung

- Desktop bei 1440 × 900 sowie 1024 × 768, Touch-PWA bei 390 × 844 und schmalem
  320-px-Viewport. 200 % Zoom beziehungsweise entsprechend reduzierte Breite,
  lange deutsche Titel, 0/1/viele Aufgaben, unzugewiesene Personen und fehlende
  Termine prüfen. Kein horizontaler Seitenscroll, kein abgeschnittener Fokus.
- Mobile: Erste Aufgaben stehen vor Listenverwaltung; Detailansicht und Tastatur
  verdecken keine erforderliche Aktion. Touch-Trefferflächen nachmessen.
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
