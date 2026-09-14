# Aufgaben-UX: Implementierung und Abnahme

Stand: S1 bis S5 sind mit vollständig grüner PR-CI abgeschlossen. S6–S11 bleiben
offen.
Ausgangsstand: `0a084c88ac5ddd73faf112d3d6abc767ab2d6c6f` auf Draft-PR #7.
Die CI dieses Ausgangsstands war beim Implementierungsbeginn vollständig grün
(`gh pr checks 7 --json name,state`, keine offenen/fehlgeschlagenen Checks).

Reihenfolge: S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10a → S10b → S11.
Pro abgeschlossenem Slice eigener Push auf denselben Draft-PR. Screenshots an
wichtigen UI-Übergängen; alle fachlichen Kriterien brauchen unabhängig davon
passende Verifikation. Fehlende Plattformnachweise bleiben ausdrücklich offen.

## Einzelabnahmen

| Kriterium | Commit | Prüfung/Testfall | Erwartung | Ergebnis | Beleg |
| --- | --- | --- | --- | --- | --- |
| S1-A1 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | Web/PWA: zwölf Aufgaben, 390/320 px, Zeilen- und Trefferflächenmessung | Erste Zeile sichtbar, kein Überlauf, Trefferfläche ≥44 px | bestanden | `modules-tasks.spec.mjs`, finaler K3-Lauf: 12/12; Desktop/PWA-Screenshots |
| S1-A2 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | Service/HTTP/Browser: Abschluss, Undo, Doppelklick, Receipts | Nur Status/Revision geändert, keine doppelten Effekte | bestanden | K2 und K3 erfolgreich |
| S1-A3 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | Zwei Akteure: Titeländerung vor Undo | 409 ohne Überschreiben, sichtbarer Konflikt und Neuladen | bestanden | Service-, HTTP- und Browservertrag |
| S1-A4 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | Leser, Bearbeiter, Fremdzugriff, Rechteentzug und Receipt-Replay | Aktuelle Rechte in Projektion und Mutation; Leser ohne Bearbeitungsaktionen | bestanden | Aufgaben-/Aktionsverträge und Web/PWA |
| S1-A5 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | SQL query_logger mit 1/50 Aufgaben; Browser zählt Requests | Konstante SQL-Leseanzahl, keine Einzelabfragen für Zeilenlabels | bestanden | K2 und K3 erfolgreich |
| S1-A6 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | Tastatur/Undo/Fokus, langer Titel, leere Suche, langsames Refetch | Bedienung ohne Fokusverlust oder verschwindende Bestandszeilen | bestanden | Beide S1-Browserfälle erfolgreich |
| S1-A7 | `faea4c800d4aa466a3f229384fe937ec9a8d48f3` | Aufgaben/Wissen/Materialien Web/PWA, Inbox, 780-px-Abmelden, langes Materiallabel bei 320 px | Desktop 40 px, Touch/Iconflächen ≥44 px, Icons inline, kein Abschneiden | bestanden | K3-Verbraucherfälle, PR-CI und Screenshots erfolgreich |
| S2-A1 | `2ee6610f30f4417b60e573f4ce83ecfd4fb77566` | Web/PWA: Schnellanlage per Enter und Button, leerer Titel, Zuweisung „Für mich“ | Genau eine Aufgabe, keine Mutation bei Leerwert, eigene Person nur wenn zulässig | bestanden | `tasks-details.spec.mjs`, vollständiger K3-Lauf: 16/16 |
| S2-A2 | `2ee6610f30f4417b60e573f4ce83ecfd4fb77566` | Ausgewählte und übergreifende Ansicht, Leserrolle | Liste nur im übergreifenden Kontext erforderlich; Leser ohne Anlageformular | bestanden | Browserfälle für Liste, Aggregat und Leser |
| S2-A3 | `2ee6610f30f4417b60e573f4ce83ecfd4fb77566` | 1440/1024/390 px, langer Listenname, Icon-Aktionen und Schnellanlage | Ruhige Kopfzeile; aktueller Listenname nicht redundant im Formular; Detail split/eigene Ansicht; ≥44-px-Ziele | bestanden | Geometrieassertionen und visuell geprüfte Screenshots |
| S2-A4 | `2ee6610f30f4417b60e573f4ce83ecfd4fb77566` | Filter, Suche, Direktlink, Reload, Browser-Zurück und Fokus | URL-Zustand und Rückkehrposition bleiben erhalten | bestanden | reale Navigationsschritte in `tasks-details.spec.mjs` |
| S2-A5 | `2ee6610f30f4417b60e573f4ce83ecfd4fb77566` | Geänderter Entwurf, Escape/Zurück/Abbrechen und simulierter konkurrierender Stand | Kein stiller Verlust; Konflikt lässt Entwurf editierbar und erhält Werte | bestanden | Browserdialog-, Fokus- und Konfliktfälle |
| S2-A6 | `2ee6610f30f4417b60e573f4ce83ecfd4fb77566` | PWA 390 px sowie echtes Safari unter iOS 26.5 mit geöffneter Tastatur | Aktionen bleiben erreichbar; Detail verdeckt nichts; Wissensreferenz öffnet die Aufgabe | bestanden | `s2-app-390-detail-actions.png`, `s2-ios-safari-keyboard.png`, K3 16/16 |
| S3-A1 | `bef87bcfd50785b525037cc95215facb62d0aac8` | 125 Service- und 122 Browser-Aufgaben, Suchtreffer jenseits Seite 50 | Filter greifen vor Pagination; vollständige ID-Menge wird nachgeladen | bestanden | Servicevertrag und `tasks-views.spec.mjs`, K2/K3 und PR-CI grün |
| S3-A2 | `bef87bcfd50785b525037cc95215facb62d0aac8` | Berlin-Frühjahrs-/Herbstwechsel mit exakten Grenzwerten | `[2026-03-28T23:00Z, 2026-03-29T22:00Z)` und `[2026-10-24T22:00Z, 2026-10-25T23:00Z)` inklusive/exklusive Grenze | bestanden | echter PostgreSQL-Servicevertrag in K2 |
| S3-A3 | `bef87bcfd50785b525037cc95215facb62d0aac8` | Heute fällige, bis morgen zurückgestellte Aufgabe | In Heute und Zurückgestellt, nicht in Offen; beide Zeiten unverändert | bestanden | Servicevertrag und Web/PWA-Browseransichten |
| S3-A4 | `bef87bcfd50785b525037cc95215facb62d0aac8` | Gleiche Fälligkeit, doppelte Abschnittstitel, ohne Abschnitt, drei Seiten | Stabile Reihenfolge, 125 eindeutige IDs, je eine zusammenhängende Überschrift, ohne Abschnitt zuletzt | bestanden | PostgreSQL-Vertrag; Browser lädt 121 aktive Zeilen und drei Gruppen |
| S3-A5 | `bef87bcfd50785b525037cc95215facb62d0aac8` | Legacy- und fehlerhafte Query-Kombinationen über Service/FastAPI | `includeDeferred` kompatibel; Widersprüche, naive/invertierte Grenzen und Abschnitt ohne Liste liefern 422 | bestanden | vollständiger K2-Service-/HTTP-Lauf |
| S3-A6 | `bef87bcfd50785b525037cc95215facb62d0aac8` | Nachladen, Filter-/Sortierwechsel, Detail und Browser-Zurück | Alte Seiten verschwinden; URL-Zustand kehrt zurück; Ladebutton fehlt am Ende | bestanden | `tasks-views.spec.mjs`, vollständiger K3-Lauf: 17/17 und PR-CI |
| S4-A1 | `f8d4a85cb8ba171663f7c6fae19e64030c4a53a8` | Web/PWA bei 1440, 1024, 720, 390 und 320 px; lange Namen, Tooltips, Fokus sowie Button-/Touch-Geometrie | Kein horizontaler Überlauf oder Abschneiden; 720 px bildet den 200-%-Desktopfall ab; Desktopziele 40–44 px, Touchziele mindestens 44 px | bestanden | Geometrieassertionen in `modules-tasks.spec.mjs`/`tasks-details.spec.mjs`, K3 19/19 und visuell geprüfte Matrix |
| S4-A2 | `f8d4a85cb8ba171663f7c6fae19e64030c4a53a8` | Web/PWA: anlegen → zuweisen → Abschnitt anlegen/zuordnen → zurückstellen → suchen → erledigen → wiederöffnen | Aufgabe wieder offen und im Abschnitt; Fälligkeit bitgleich erhalten, Wiedervorlage entfernt; keine verlorene Referenz | bestanden | beide vollständigen Hauptabläufe in `modules-tasks.spec.mjs`, abschließender echter API-Read und Screenshots |
| S4-A3 | `f8d4a85cb8ba171663f7c6fae19e64030c4a53a8` | Eigentümer/Bearbeiter/Leser, 409, Rechteentzug, Direktlink und bestehende Wissens-/Inbox-/Materialverweise | Keine Mutation oder Detailauflösung nach Entzug; fremde Daten nicht sichtbar; bestehende Verweise bleiben funktionsfähig | bestanden | Web/PWA-Rechtefall plus unveränderte Modulregressionen im vollständigen K3-Lauf |
| S4-A4 | `f8d4a85cb8ba171663f7c6fae19e64030c4a53a8` | K1, K3, K4, Push, Screenshot-Kommentar und vollständige PR-CI einschließlich K2 | Alle lokalen Gates und anschließend alle PR-Jobs grün; Draft bleibt erhalten | bestanden | K1, K3 19/19, K4 507/507 und 68/68 PR-Checks grün; Screenshot-Kommentar `https://github.com/BjoernSchotte/leonaid/pull/7#issuecomment-5668340706` |
| S5-A1 | `5821d57ad7ddf71086b03988ee1f9eb5079073dd` | A und B planen dieselbe Aufgabe für verschiedene Tage; Task vor/nach Planung vergleichen | Jeder sieht nur den eigenen Plan; gemeinsame Revision, Deadline, Zuweisung und Wiedervorlage bleiben unverändert | bestanden | PostgreSQL-Mehrnutzervertrag in `planning_contract.py` |
| S5-A2 | `5821d57ad7ddf71086b03988ee1f9eb5079073dd` | Überfälligen Plan schließen und wieder öffnen | Offen in Heute; geschlossen unsichtbar; nach Wiederöffnung mit ursprünglichem Datum wieder sichtbar | bestanden | PostgreSQL-Servicevertrag in `planning_contract.py` |
| S5-A3 | `5821d57ad7ddf71086b03988ee1f9eb5079073dd` | Geplante und heute fällige Aufgaben einschließlich künftig geplantem Fälligkeitstreffer | Keine Duplikate; ungeplante Fälligkeit bleibt Hinweis; kein automatisch erzeugter Plan | bestanden | Servicevertrag und Desktop-Browserfall `tasks-planning.spec.mjs` |
| S5-A4 | `5821d57ad7ddf71086b03988ee1f9eb5079073dd` | Leser plant persönlich, versucht gemeinsame Mutation; danach Rechteentzug | Eigene Planung zulässig, Task-Mutation gesperrt; danach weder Task noch Plan auflösbar | bestanden | Service-/HTTP-Vertrag und PWA-Leserfall mit echtem Rechteentzug |
| S5-A5 | `5821d57ad7ddf71086b03988ee1f9eb5079073dd` | Plan entfernen, veraltete Revision schreiben, identischen Auftrag wiederholen | Revisionsträger verhindert ABA; veraltet 409; identischer Retry genau ein Effekt | bestanden | PostgreSQL-Transaktionsvertrag in `planning_contract.py` |
| S5-A6 | `5821d57ad7ddf71086b03988ee1f9eb5079073dd` | Ungültige Zeitzone und widersprüchliche Zustände; Ansicht in zwei Zeitzonen | 422 ohne Mutation; lokales Datum bleibt gespeichert und Heute-Zuordnung folgt der Zeitzone | bestanden | Service-/HTTP-Vertrag und vollständiger K2-Lauf |
| S6-A1 | – | noch auszuführen | siehe SLICES.md, S6-A1 | offen | – |
| S6-A2 | – | noch auszuführen | siehe SLICES.md, S6-A2 | offen | – |
| S6-A3 | – | noch auszuführen | siehe SLICES.md, S6-A3 | offen | – |
| S6-A4 | – | noch auszuführen | siehe SLICES.md, S6-A4 | offen | – |
| S6-A5 | – | noch auszuführen | siehe SLICES.md, S6-A5 | offen | – |
| S6-A6 | – | noch auszuführen | siehe SLICES.md, S6-A6 | offen | – |
| S7-A1 | – | noch auszuführen | siehe SLICES.md, S7-A1 | offen | – |
| S7-A2 | – | noch auszuführen | siehe SLICES.md, S7-A2 | offen | – |
| S7-A3 | – | noch auszuführen | siehe SLICES.md, S7-A3 | offen | – |
| S7-A4 | – | noch auszuführen | siehe SLICES.md, S7-A4 | offen | – |
| S7-A5 | – | noch auszuführen | siehe SLICES.md, S7-A5 | offen | – |
| S8-A1 | – | noch auszuführen | siehe SLICES.md, S8-A1 | offen | – |
| S8-A2 | – | noch auszuführen | siehe SLICES.md, S8-A2 | offen | – |
| S8-A3 | – | noch auszuführen | siehe SLICES.md, S8-A3 | offen | – |
| S8-A4 | – | noch auszuführen | siehe SLICES.md, S8-A4 | offen | – |
| S8-A5 | – | noch auszuführen | siehe SLICES.md, S8-A5 | offen | – |
| S8-A6 | – | noch auszuführen | siehe SLICES.md, S8-A6 | offen | – |
| S8-A7 | – | noch auszuführen | siehe SLICES.md, S8-A7 | offen | – |
| S8-A8 | – | noch auszuführen | siehe SLICES.md, S8-A8 | offen | – |
| S9-A1 | – | noch auszuführen | siehe SLICES.md, S9-A1 | offen | – |
| S9-A2 | – | noch auszuführen | siehe SLICES.md, S9-A2 | offen | – |
| S9-A3 | – | noch auszuführen | siehe SLICES.md, S9-A3 | offen | – |
| S9-A4 | – | noch auszuführen | siehe SLICES.md, S9-A4 | offen | – |
| S9-A5 | – | noch auszuführen | siehe SLICES.md, S9-A5 | offen | – |
| S9-A6 | – | noch auszuführen | siehe SLICES.md, S9-A6 | offen | – |
| S10a-A1 | – | noch auszuführen | siehe SLICES.md, S10a-A1 | offen | – |
| S10a-A2 | – | noch auszuführen | siehe SLICES.md, S10a-A2 | offen | – |
| S10a-A3 | – | noch auszuführen | siehe SLICES.md, S10a-A3 | offen | – |
| S10a-A4 | – | noch auszuführen | siehe SLICES.md, S10a-A4 | offen | – |
| S10b-A1 | – | noch auszuführen | siehe SLICES.md, S10b-A1 | offen | – |
| S10b-A2 | – | noch auszuführen | siehe SLICES.md, S10b-A2 | offen | – |
| S10b-A3 | – | noch auszuführen | siehe SLICES.md, S10b-A3 | offen | – |
| S10b-A4 | – | noch auszuführen | siehe SLICES.md, S10b-A4 | offen | – |
| S11-A1 | – | noch auszuführen | siehe SLICES.md, S11-A1 | offen | – |
| S11-A2 | – | noch auszuführen | siehe SLICES.md, S11-A2 | offen | – |
| S11-A3 | – | noch auszuführen | siehe SLICES.md, S11-A3 | offen | – |
| S11-A4 | – | noch auszuführen | siehe SLICES.md, S11-A4 | offen | – |
| S11-A5 | – | noch auszuführen | siehe SLICES.md, S11-A5 | offen | – |

## S1-Verifikation

- RED: Der echte Servicevertrag gegen den Ausgangsstand scheiterte am fehlenden
  `canEdit`-Feld; derselbe Vertrag bestand anschließend gegen S1.
- K1: vollständiger Repository-Lint inklusive Ruff, mypy, generierter API,
  Modulgrenzen, Workspace-Typprüfung und Formatierung bestanden. Nach den letzten
  UI-Änderungen zusätzlich die vollständige Frontend-Typprüfung im gepinnten
  Bun-Image und die Formatprüfung der betroffenen Dateien bestanden.
- K2: vollständiger isolierter Schema-/Service-/HTTP-Lauf bestanden, einschließlich
  leerem Aufbau, Upgrade eines befüllten Altstands, Rechteverträgen und Datenhalt.
  Eigene Testressourcen wurden entfernt.
- K3: alle zwölf Fälle des unveränderten `tools/testing/modular_browser.sh`
  bestanden (Web und PWA, Aufgaben/Wissen/Materialien/Inbox). Ausgeführt über einen
  temporären lokalen Wrapper um den bestehenden `SharedStack`, mit frisch
  aufgebautem eigenem Compose-Projekt; keine Test-Doubles. Der Wrapper hält den
  Stack für mögliche Wiederholungen offen und entfernt ihn beim Abschluss.
- Nachweise lokal: `/tmp/leonaid-s1-final-lint.log`,
  `/tmp/leonaid-s1-final-frontend-types.log`, `/tmp/leonaid-s1-green-schema.log`,
  `/tmp/leonaid-s1-diagnostic-browser-2.log`; Screenshots unter
  `.artifacts/tasks-s1-diagnostic/modules/`. Ausgewählte PNGs kommen als
  Anhänge in den Kommentar auf Draft-PR #7; Traces/Sitzungsdaten werden nicht publiziert.
- K5: PR-CI für Commit `faea4c800d4aa466a3f229384fe937ec9a8d48f3`
  vollständig grün; Screenshot-Kommentar im Draft-PR veröffentlicht.

## S2-Verifikation

- RED: Die drei neuen Browserfälle für responsive Details, URL-/Entwurfsschutz
  und mobile Erreichbarkeit scheiterten vor der Implementierung wie erwartet.
- K1: vollständiger Repository-Lint inklusive Ruff, mypy, generierter API,
  Modulgrenzen, Workspace-Typprüfung und Prettier bestanden.
- K2: entfällt für S2, weil weder API-Verhalten noch Schema geändert wurden.
- K3: vollständiger modularer Browserlauf mit 16/16 Fällen bestanden. Er umfasst
  Web und PWA bei 1440, 1024 und 390 px, reale Navigation, Konfliktbehandlung,
  Wissensreferenzen sowie bestehende Module.
- Plattformnachweis: echtes Safari unter iOS 26.5 mit nativer Bildschirmtastatur
  bestanden. In der mobilen Detailansicht wird die App-Navigation ausgeblendet;
  Speichern und Abbrechen bleiben sichtbar. Nach dem Schließen erscheint die
  einzeilige App-Navigation wieder.
- Nachweise lokal: `.artifacts/tasks-s2/modules/`,
  `.artifacts/tasks-s2/s2-ios-safari-workspace.png` und
  `.artifacts/tasks-s2/s2-ios-safari-keyboard.png`. Ausgewählte PNGs werden ohne
  Sitzungsdaten als Anhänge am Draft-PR veröffentlicht.
- K5: PR-CI für Commit `2ee6610f30f4417b60e573f4ce83ecfd4fb77566`
  einschließlich aller Vertrags-, Integrations-, E2E-, Survey-, Sicherheits- und
  Installationsjobs vollständig grün. Screenshot-Kommentar im Draft-PR veröffentlicht.

## S3-Verifikation

- RED: Der erweiterte Servicevertrag scheiterte vor der Implementierung am
  unbekannten `deferredState`; der Browservertrag blieb in `view=open` statt die
  angeforderte Terminansicht zu laden.
- K1: vollständiger Repository-Lint mit Ruff, mypy für 400 Quellen,
  deterministischem OpenAPI-Client, Frontend-Grenzen, allen Workspace-Typen und
  Prettier bestanden.
- K2: vollständiger isolierter Schema-/Service-/HTTP-Lauf bestanden. Er umfasst
  leeren Aufbau, befülltes Vorgänger-Upgrade, 125 Aufgaben, Sommerzeitgrenzen,
  Legacy-Kompatibilität und sämtliche Query-Fehlerfälle. Alle eigenen Container,
  Netze und Volumes wurden entfernt.
- K3: vollständiger modularer Browserlauf mit 17/17 Fällen bestanden. Der neue
  Fall lädt 122 Aufgaben über echte FastAPI-Aufrufe, hängt drei Seiten ohne
  Duplikate an, gruppiert Abschnitte und prüft Terminansichten sowie Zurücknavigation
  in Web und PWA.
- Visuelle Prüfung: Desktop zeigt Schnellerfassung und vier Filter in je einer
  ruhigen Zeile sowie kompakte, einklappbare Abschnittsüberschriften. Bei 390 px
  bleiben Beschriftungen, Touchflächen, Aufgabenzeilen und App-Navigation lesbar
  und ohne horizontalen Überlauf.
- Nachweise lokal: `.artifacts/tasks-s3-final/modules/`; die beiden S3-PNGs werden
  ohne Sitzungstraces oder Fixture-Daten am Draft-PR veröffentlicht.
- K5: PR-Head `bef87bcfd50785b525037cc95215facb62d0aac8`, Draft-Status
  erhalten und sämtliche Vertrags-, Security-, Integrations-, E2E-, Survey- und
  Installationsjobs grün. Screenshot-Kommentar:
  `https://github.com/BjoernSchotte/leonaid/pull/7#issuecomment-5667113349`.

## S4-Verifikation

- K1: vollständiger Repository-Lint mit Ruff, mypy für 400 Quellen,
  deterministischem OpenAPI-Client, Frontend-Grenzen, allen Workspace-Typen,
  Astro-Diagnostik und Prettier bestanden.
- K2: keine weitere API-, Schema- oder Produktänderung seit dem vollständig grünen
  S3-K2-Lauf. Der isolierte Schema-/Upgradevertrag läuft wegen seines destruktiven
  Datenaufbaus nicht parallel zum SharedStack und wird durch die vollständige
  S4-PR-CI erneut abgenommen.
- K3: vollständiger modularer Browserlauf mit 19/19 Fällen bestanden. Die
  checkout-lokale Fixture `leonaid-shared-b0c27804ed9603f1` wurde einmal aufgebaut,
  für den Wiederholungslauf ohne Build wiederverwendet und bleibt für Folgeslices
  erhalten. Keine Test-Doubles und kein paralleler Teststack.
- K4: 507/507 deterministische Unit-/Domain-/Architektur-/Migrationsfälle bestanden.
- Durchgängiger Ablauf: Aufgabe auf Web und PWA angelegt, zugewiesen, einem neu
  angelegten Abschnitt zugeordnet, zurückgestellt, über Ansicht und Suche gefunden,
  erledigt und wieder geöffnet. Der abschließende API-Read bestätigt Status,
  Abschnitt, unveränderte Fälligkeit und entfernte Wiedervorlage.
- Rechte: Leserzugriff wurde zu Bearbeiterzugriff erweitert und anschließend
  entzogen. Danach zeigen UI-Direktlink und API keinen Task; der Konfliktfall sowie
  Wissens-, Material- und Inbox-Regressionen blieben grün.
- Visuelle Prüfung: 1440/1024/720/390/320 px ohne horizontalen Überlauf oder
  abgeschnittene Pflichtaktionen. Die Desktop- und PWA-Hauptabläufe sowie 720-/320-
  Detailzustände liegen unter `.artifacts/tasks-s4-final-3/modules/`.
- K5: PR-Head `f8d4a85cb8ba171663f7c6fae19e64030c4a53a8`, Draft-Status
  erhalten und 68/68 PR-Checks grün. Screenshot-Kommentar:
  `https://github.com/BjoernSchotte/leonaid/pull/7#issuecomment-5668340706`.

## S5-Verifikation

- K1: vollständiger Repository-Lint mit Ruff, Formatierung, mypy für 403 Quellen,
  deterministischem OpenAPI-Client, Frontend-Grenzen und allen Workspace-Typen
  bestanden.
- K2: vollständiger isolierter Schema-/Service-/HTTP-Lauf bestanden. Er umfasst
  den leeren Aufbau bis Migration 0042, das Upgrade eines befüllten Vorgängers,
  Mehrnutzerisolation, Leserrechte, ABA-/Idempotenzfälle und Zeitzonenfehler.
- K3: vollständiger modularer Browserlauf mit 20/20 Fällen bestanden. Der neue
  Fall prüft persönliche Planung auf Web und PWA, private Ansichten, Fälligkeitshinweise
  ohne Duplikate sowie den Entzug eines Leserzugriffs. Desktop- und PWA-Aufnahmen
  liegen unter `.artifacts/tasks-s5-final/modules/`.
- K4: 507/507 Unit-/Domain-/Architektur-/Migrationsfälle bestanden. Zusätzlich
  sind Test-Double-, Diff- und der lokale SharedStack-Selbsttest mit 5/5 grün.
- Der lokale Browserrunner verwendet pro Worktree einen wiederverwendbaren
  Compose-Stack. Unveränderte Images werden nicht gebaut; der warme Datenreset
  dauerte im finalen Lauf 2,0 Sekunden. Nach dem Lauf wurden nur die Container
  gestoppt, Cache, Images und Volumes bleiben erhalten.
- Die erste PR-Ausführung deckte zwei CI-Vertragsfehler auf: Bootstrap muss seine
  reguläre `.venv` behalten, und der schlanke Core-Modus darf nur für den lokalen
  Browserstack gelten. Kalter Bootstrap/Doctor, 507 Unit-Tests, vollständiger
  Lint-/Typ-Gate und der explizite Lean-/Full-Stack-Selbsttest sind nach den
  Korrekturen grün.
- K5: PR-Head `1fb71d650f9aef6b745a86b3e849e1b112ac7a77`, Draft-Status
  erhalten, Merge-Status sauber und 69/69 ausgeführte PR-Checks grün; vier
  bedingte Jobs wurden erwartungsgemäß übersprungen. Screenshot-Kommentar:
  `https://github.com/BjoernSchotte/leonaid/pull/7#issuecomment-5670232217`.
