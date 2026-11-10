---
title: Status und wichtige Felder
description: Nachschlagewerk für Aktions-, Akquise-, Bestell-, Rechnungs- und Lieferstatus.
docId: DOC-P017
audience: [user]
diataxis: reference
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: 176b94f63b8ff6dbd9deadb71b9ab507ee53989b
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

## Charity-Aktion

`draft` (**Entwurf**) → `scheduled` (**Geplant**) → `active` (**Aktiv**) →
`completed` (**Abgeschlossen**) → `archived` (**Archiviert**). Eine geplante
Aktion darf in den Entwurf zurückkehren. Abgeschlossene Aktionen werden nur
noch archiviert; archivierte Aktionen sind schreibgeschützt.

## Akquise

| Technisch     | Oberfläche  | Bedeutung                                         |
| ------------- | ----------- | ------------------------------------------------- |
| `open`        | Offen       | Bearbeitung hat noch nicht begonnen               |
| `contacted`   | Kontaktiert | Kontaktversuch ist dokumentiert                   |
| `committed`   | Zugesagt    | Sponsor hat zugesagt oder bestellt                |
| `declined`    | Abgesagt    | kein weiterer Akquiseschritt geplant              |
| `handed_over` | Übergeben   | interner Übergabestatus, nicht regulär editierbar |

Wiedervorlage, Priorität und nächste Aktion gehören zur Zuordnung, nicht zum
CRM-Kontakt selbst.

## Bestellung

`draft` (**Entwurf**), `review_ready` (**Prüfbereit**), `confirmed`
(**Bestätigt**), `invoiced` (**Fakturiert**) und `cancelled` (**Storniert**).
Quelle ist `acquisition`, `public_form` oder `admin`. Preise, Positionen,
Rechnungs- und Lieferangaben werden serverseitig geprüft; ein gebuchtes
Lieferfenster bleibt als Snapshot erhalten.

**Storniert** ist endgültig und nur möglich, solange die Bestellung nicht
geliefert und zu ihrer Rechnung keine Zahlung erfasst ist. Das Storno speichert
Grund, optionale Notiz, Vorstatus, Person und Zeitpunkt. Eine stornierte
Bestellung bleibt in Listen sichtbar, zählt aber in keiner Summe und auf keiner
Liefertafel; eine offene Rechnung wird mitstorniert und erhält eine
Stornorechnung (siehe [Bestellung stornieren](/de/user/how-to/cancel-order/)).

## Lieferfenster

| Technisch     | Oberfläche  | Bedeutung                                                              |
| ------------- | ----------- | ---------------------------------------------------------------------- |
| offen         | Buchbar     | wird in Bestellformular, Akquise und Backoffice angeboten              |
| `fullyBooked` | Ausgebucht  | öffentlich nicht wählbar; Backoffice und Akquise buchen nach Rückfrage |
| `retired`     | Stillgelegt | wird nicht mehr angeboten; gebuchte Bestellungen behalten den Termin   |

Stilllegen hebt **Ausgebucht** auf. Ein Fenster, das schon begonnen hat, wird
nicht mehr angeboten.

## Rechnung und Versand

Rechnungen sind `issued` (**Ausgestellt**), `sent` (**Versendet**), `paid`
(**Bezahlt**) oder `cancelled` (**Storniert**). Die Rechnungsliste zeigt
ausgestellte oder versendete Rechnungen mit Restbetrag als **Offen**, nach dem
Fälligkeitstag als **Überfällig**. Der Status lässt sich in der Liste nicht
direkt ändern; Zahlung und Storno sind eigene Befehle im Detailbereich.

Ein Storno stellt eine **Stornorechnung** aus: ein eigener Beleg mit der
nächsten Nummer aus dem Nummernkreis der Rechnungen, der die aufgehobene
Rechnung nennt. Der Nummernkreis gilt für die ganze Installation. War auf die
Rechnung Geld eingegangen, zeigt sie **Erstattung offen**, bis jemand
**Erstattung erledigt** vermerkt (siehe
[Rechnung stornieren](/de/user/how-to/cancel-invoice/)).

Der E-Mail-Versand besitzt eigene Status: `queued`, `sending`, `retrying`,
`failed` und `sent`. Ein Versandfehler verändert den Beleg nicht. Das PDF ist
unabhängig davon `pending`, `available` oder `deleted`.
