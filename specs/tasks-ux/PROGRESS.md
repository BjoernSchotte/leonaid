# Aufgaben-UX: Implementierung und Abnahme

Stand: S1 implementiert und lokal vollständig geprüft. PR-CI für S1 steht noch aus;
S2–S11 bleiben offen. S2 beginnt nach grüner S1-CI.
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
| S1-A1 | S1-Änderungsstand dieses Commits | Web/PWA: zwölf Aufgaben, 390/320 px, Zeilen- und Trefferflächenmessung | Erste Zeile sichtbar, kein Überlauf, Trefferfläche ≥44 px | lokal bestanden | `modules-tasks.spec.mjs`, finaler K3-Lauf: 12/12; Desktop/PWA-Screenshots |
| S1-A2 | S1-Änderungsstand dieses Commits | Service/HTTP/Browser: Abschluss, Undo, Doppelklick, Receipts | Nur Status/Revision geändert, keine doppelten Effekte | lokal bestanden | K2 und K3 erfolgreich |
| S1-A3 | S1-Änderungsstand dieses Commits | Zwei Akteure: Titeländerung vor Undo | 409 ohne Überschreiben, sichtbarer Konflikt und Neuladen | lokal bestanden | Service-, HTTP- und Browservertrag |
| S1-A4 | S1-Änderungsstand dieses Commits | Leser, Bearbeiter, Fremdzugriff, Rechteentzug und Receipt-Replay | Aktuelle Rechte in Projektion und Mutation; Leser ohne Bearbeitungsaktionen | lokal bestanden | Aufgaben-/Aktionsverträge und Web/PWA |
| S1-A5 | S1-Änderungsstand dieses Commits | SQL query_logger mit 1/50 Aufgaben; Browser zählt Requests | Konstante SQL-Leseanzahl, keine Einzelabfragen für Zeilenlabels | lokal bestanden | K2 und K3 erfolgreich |
| S1-A6 | S1-Änderungsstand dieses Commits | Tastatur/Undo/Fokus, langer Titel, leere Suche, langsames Refetch | Bedienung ohne Fokusverlust oder verschwindende Bestandszeilen | lokal bestanden | Beide S1-Browserfälle erfolgreich |
| S1-A7 | S1-Änderungsstand dieses Commits | Aufgaben/Wissen/Materialien Web/PWA, Inbox, 780-px-Abmelden, langes Materiallabel bei 320 px | Desktop 40 px, Touch/Iconflächen ≥44 px, Icons inline, kein Abschneiden | lokal bestanden | K3-Verbraucherfälle; Screenshots visuell geprüft |
| S2-A1 | – | noch auszuführen | siehe SLICES.md, S2-A1 | offen | – |
| S2-A2 | – | noch auszuführen | siehe SLICES.md, S2-A2 | offen | – |
| S2-A3 | – | noch auszuführen | siehe SLICES.md, S2-A3 | offen | – |
| S2-A4 | – | noch auszuführen | siehe SLICES.md, S2-A4 | offen | – |
| S2-A5 | – | noch auszuführen | siehe SLICES.md, S2-A5 | offen | – |
| S2-A6 | – | noch auszuführen | siehe SLICES.md, S2-A6 | offen | – |
| S3-A1 | – | noch auszuführen | siehe SLICES.md, S3-A1 | offen | – |
| S3-A2 | – | noch auszuführen | siehe SLICES.md, S3-A2 | offen | – |
| S3-A3 | – | noch auszuführen | siehe SLICES.md, S3-A3 | offen | – |
| S3-A4 | – | noch auszuführen | siehe SLICES.md, S3-A4 | offen | – |
| S3-A5 | – | noch auszuführen | siehe SLICES.md, S3-A5 | offen | – |
| S3-A6 | – | noch auszuführen | siehe SLICES.md, S3-A6 | offen | – |
| S4-A1 | – | noch auszuführen | siehe SLICES.md, S4-A1 | offen | – |
| S4-A2 | – | noch auszuführen | siehe SLICES.md, S4-A2 | offen | – |
| S4-A3 | – | noch auszuführen | siehe SLICES.md, S4-A3 | offen | – |
| S4-A4 | – | noch auszuführen | siehe SLICES.md, S4-A4 | offen | – |
| S5-A1 | – | noch auszuführen | siehe SLICES.md, S5-A1 | offen | – |
| S5-A2 | – | noch auszuführen | siehe SLICES.md, S5-A2 | offen | – |
| S5-A3 | – | noch auszuführen | siehe SLICES.md, S5-A3 | offen | – |
| S5-A4 | – | noch auszuführen | siehe SLICES.md, S5-A4 | offen | – |
| S5-A5 | – | noch auszuführen | siehe SLICES.md, S5-A5 | offen | – |
| S5-A6 | – | noch auszuführen | siehe SLICES.md, S5-A6 | offen | – |
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
- K5: PR-CI des neuen S1-Commits noch offen. Die lokale Verifikation allein ist
  keine vollständige Slice-Abnahme.
