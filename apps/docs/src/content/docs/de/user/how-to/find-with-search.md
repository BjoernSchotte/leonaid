---
title: Mit der Suche finden
description: Aktionen, Bestellungen, Rechnungen, Sponsoren und Mitglieder über „Suchen und Befehle“ finden und direkt öffnen.
docId: DOC-P053
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: e2e199217b9b0d23fc0ad225051cfc36fe01daf5
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** jedes Mitglied mit Zugang zur Verwaltung. Die Suche zeigt dir nur,
was du mit deinen Rollen auch auf der zugehörigen Seite öffnen darfst.

1. Wähle in der Verwaltung **Suchen und Befehle**, oder drücke `Strg+K`
   (Mac: `⌘K`). Außerhalb eines Eingabefelds öffnet auch `/` die Suche.
2. Tippe mindestens zwei Zeichen. Die Treffer erscheinen nach Art gruppiert:
   **Charity-Aktionen**, **Bestellungen**, **Rechnungen**, **Sponsoren** und
   **Mitglieder**, danach die Treffer der eingeschalteten Module.
3. Wähle einen Treffer mit den Pfeiltasten und `Enter` oder mit einem Klick.
   LeonAid öffnet die Seite des Treffers und dort den Eintrag selbst.

## Was die Suche findet

| Gruppe           | Gesucht wird in                      | Wer findet es                                                                                                                            |
| ---------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Charity-Aktionen | Name der Aktion                      | Charity-Admins der Aktion, System-Admins                                                                                                 |
| Bestellungen     | Name des Bestellers, Bestellnummer   | Charity-Admins der Aktion, System-Admins                                                                                                 |
| Rechnungen       | Rechnungsnummer, Name des Empfängers | Finanzrollen, Charity-Admins der Aktion, System-Admins                                                                                   |
| Sponsoren        | Name und Ort des Sponsors            | Charity-Admins und System-Admins: alle Zuordnungen der Aktion. Akquisiteure: ihre eigenen Zuordnungen, solange sie nicht übergeben sind. |
| Mitglieder       | Name, E-Mail-Adresse                 | wer die Mitgliederliste sehen darf                                                                                                       |

Die Suche unterscheidet keine Groß- und Kleinschreibung. Treffer, die mit
deinem Suchbegriff beginnen, stehen oben.

## Sponsoren

Ein Sponsor erscheint einmal je Zuordnung. Betreuen ihn in einer Aktion zwei
Akquisiteure, siehst du als Charity-Admin zwei Treffer. Jeder Treffer nennt den
Namen des Sponsors, die Aktion und, wenn im CRM gepflegt, den Ort.

- **Als Charity-Admin oder System-Admin** öffnet der Treffer die
  **Sponsor-Pipeline** der Aktion (**Akquise** in der Leiste). Die Tabelle
  springt zur Zeile der Zuordnung, die Zeile ist hervorgehoben, und das Detail
  öffnet sich: Ort, Ansprechperson, E-Mail, Telefon, Akquisiteur, Status,
  nächster Schritt und der Verlauf der Zuordnung. **Schließen** oder `Esc`
  schließt das Detail; die Zeile bleibt hervorgehoben. Du öffnest es für jede Zeile auch mit einem Klick auf
  den Namen des Sponsors.
- **Als Akquisiteur** öffnet der Treffer den Sponsor in der Akquise-App unter
  **Sponsoren**. Das gilt auch, wenn du in einer anderen Aktion Charity-Admin
  bist: Die Rolle in der Aktion des Treffers entscheidet.

LeonAid durchsucht bei Sponsoren nur Name und Ort. E-Mail-Adresse, Telefon und
Straße eines Sponsors stehen nur im CRM und sind über die Suche nicht zu
finden.

### Wie aktuell die Sponsoren sind

- Ein neu angelegter oder neu zugeordneter Sponsor ist sofort zu finden.
- Ändert jemand Name oder Ort direkt im CRM, übernimmt die Suche das nach
  spätestens etwa 15 Minuten.
- Löscht jemand einen Sponsor im CRM, verschwindet er in der folgenden Nacht
  aus der Suche. Seine Zuordnungen bleiben in der Sponsor-Pipeline und in der
  Akquise-App stehen, mit dem Namen **Im CRM nicht mehr vorhanden** und ohne
  Kontaktdaten. Als Charity-Admin schließt du eine solche Zuordnung im Detail
  mit **Zuordnung abschließen** ab; sie gilt dann als **Abgesagt**.
- Nach einer Datenschutz-Löschung ist der Sponsor sofort nicht mehr zu finden.
  Das gilt auch für die Firma einer Bestellung, deren Ansprechperson die
  Löschung verlangt hat. Der Sponsor bleibt verborgen, auch wenn er im CRM noch
  steht. Erst wenn jemand ihn neu erfasst oder ein Charity-Admin ihn neu
  zuordnet, findet die Suche ihn wieder, mit dem Namen, den das CRM dann hat.
  Eine Übergabe zählt nicht als neue Zuordnung. Soll der Sponsor verborgen
  bleiben, muss ein System-Admin ihn nach der Löschung auch im CRM löschen,
  bevor ihn eine nächste Aktion wieder zuordnet.

## Wenn du nichts findest

- **Zu kurz:** Die Suche startet erst ab zwei Zeichen.
- **Sponsor ohne Zuordnung:** Die Suche kennt nur Sponsoren, die in einer
  Aktion einem Akquisiteur zugeordnet sind. Ein Kontakt, der nur im CRM steht,
  erscheint nicht.
- **Fremde oder übergebene Zuordnung:** Als Akquisiteur findest du nur deine
  eigenen Sponsoren. Hast du einen Sponsor übergeben, findet ihn die neue
  zuständige Person.
- **Andere Aktion:** Bestellungen, Rechnungen und Sponsoren findest du nur in
  Aktionen, in denen du die passende Rolle hast.
- **„Die Suche ist gerade nicht erreichbar“:** Versuche es erneut. Fällt nur
  ein Teil aus, nennt die Suche ihn und zeigt die übrigen Treffer.

Weitere Grenzen stehen unter [Bekannte Grenzen](/de/known-limits/).
