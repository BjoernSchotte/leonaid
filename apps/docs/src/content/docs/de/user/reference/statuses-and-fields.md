---
title: Status und wichtige Felder
description: Nachschlagewerk für Aktions-, Akquise-, Bestell-, Rechnungs- und Lieferstatus.
docId: DOC-P017
audience: [user]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
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

## Rechnung und Versand

Rechnungen sind `issued` (**Ausgestellt**), `sent` (**Versendet**), `paid`
(**Bezahlt**) oder `cancelled` (**Storniert**). Im Journal fasst **Offen** die
ausgestellten oder versendeten Belege mit Restbetrag zusammen.

Der E-Mail-Versand besitzt eigene Status: `queued`, `sending`, `retrying`,
`failed` und `sent`. Ein Versandfehler verändert den Beleg nicht. Das PDF ist
unabhängig davon `pending`, `available` oder `deleted`.
