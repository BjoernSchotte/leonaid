# PILOT-010 – Autorisierte Mitgliederübersicht

Task-ID: `PILOT-010`

Nachweisdatum: 28. Juli 2026

Status: technisch vollständig bewiesen, formaler Abschluss blockiert

## Ergebnis

Die Mitgliederadministration ist als echte, rollenbegrenzte
FastAPI-/PostgreSQL-Funktion umgesetzt:

- System-Admins sehen alle Konten mit verständlichem Status, globalen Rollen,
  Aktionsmitgliedschaften, letzter Anmeldung und Zahl aktiver Sitzungen.
- Charity-Admins sehen ausschließlich Mitglieder und Rollen ihrer selbst
  verwalteten Aktionen. Globale Rollen und fremde Aktionsmitgliedschaften
  werden bereits im Repository-Snapshot ausgeblendet.
- Akquisiteur und Finanzen erhalten HTTP `403`; nicht sichtbare
  Mitgliedsdetails werden gegenüber Charity-Admins als `404` verborgen.
- Suche, Status- und Aktionsfilter sowie stabile cursorbasierte Pagination
  werden serverseitig ausgewertet und autorisiert.
- Die React-Oberfläche gestaltet Club- und Teilscope, Loading, Fehler, Empty,
  leere Filterergebnisse, Liste, Detail und Einladung als eine geführte
  tabbasierte Arbeitsfläche.
- Die OpenAPI-Spezifikation und der generierte TypeScript-Client enthalten
  `listMembers` und `getMember`; Query-Parameter besitzen korrekte
  TypeScript-Bezeichner.

## Automatische Nachweise

```sh
./leonaid test-unit
./leonaid test-identity
```

Ergebnis:

```text
167 passed
identity-contract: OK
7 passed in Chromium
identity-test: OK: autorisierte Mitgliederübersicht, Rollen,
Sitzungsentzug und Persona-Navigation real bewiesen
```

Die Unit-Tests laden das gepflegte Golden Dataset und beweisen Suche,
Status-/Aktionsfilter, Sortierung, Seitengrenzen und die Ablehnung
manipulierter Cursor.

Der Integrationstest baut ein leeres echtes PostgreSQL auf, seedet die
Golden-Konten und erzeugt echte Sitzungen. Er vergleicht die API-Antworten
für System-Admin und Charity-Admin, prüft fremde Aktionsfilter und Details
sowie die negativen Zugriffswege für Akquisiteur und Finanzen.

Die sieben Chromium-Journeys prüfen zusätzlich:

1. System-Admin-Pagination, Suche, Statusfilter und Detail;
2. Charity-Admin-Teilscope in einem echten 390-px-Viewport;
3. Tastaturbedienung der Tabs;
4. direkte URL-Aufrufe durch Akquisiteur und Finanzen;
5. vier private Screenshots mit Modus `0600`;
6. Axe ohne kritische oder ernste Befunde.

Nach fehlgeschlagenem wie erfolgreichem Testlauf blieben für das exakte
Compose-Projekt `leonaid-poc040-test` jeweils null Container, Netze und
Volumes zurück.

## Sichtbarer In-App-Browser-Nachweis

Die laufende lokale Anwendung wurde mit einem synthetischen System-Admin über
den echten Magic-Code-Weg geöffnet. Sichtbar bedient und geprüft wurden:

- Wechsel auf Seite 2 und zurückgesetzte Pagination;
- Statusfilter „Gesperrt“ mit genau einem Treffer;
- Filter-Reset und Suche nach „Klara“ mit Detailansicht;
- Wechsel zwischen Übersicht und Einladung per Pfeiltasten;
- fehlerfreie Browserkonsole.

Der echte mobile Chromium-Screenshot zeigt die einspaltige 390-px-Anordnung
mit erreichbaren Filtern, Liste, Pagination und Detail.

## Formale Taskgrenze

Alle Kriterien von `PILOT-010` sind technisch bewiesen. Der Task bleibt im
Plan dennoch offen, weil der Pilotvertrag einen abgeschlossenen Task mit
offener Abhängigkeit ablehnt: `PILOT-010` hängt von `PILOT-002` ab, dessen
formaler Abschluss wiederum die externen Entscheidungen aus `PILOT-001`
benötigt. Diese Abhängigkeit wird nicht durch einen verfrühten Haken umgangen.
