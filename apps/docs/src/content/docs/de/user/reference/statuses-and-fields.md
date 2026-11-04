---
title: Status und wichtige Felder
description: Nachschlagewerk für Aktions-, Akquise-, Bestell-, Rechnungs- und Lieferstatus.
docId: DOC-P017
audience: [user]
diataxis: reference
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 1c054b0fb55c59b9f884aee956b431a519ce521d
reviewer: Björn Schotte
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

Der E-Mail-Versand besitzt eigene Status: `queued`, `sending`, `retrying`,
`failed` und `sent`. Ein Versandfehler verändert den Beleg nicht. Das PDF ist
unabhängig davon `pending`, `available` oder `deleted`.
