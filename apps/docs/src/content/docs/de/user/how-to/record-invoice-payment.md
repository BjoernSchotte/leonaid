---
title: Zahlungseingang erfassen
description: Voll-, Teil- und Überzahlungen einer Rechnung erfassen und einen falschen Eintrag zurückbuchen.
docId: DOC-P014
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 68fe0e63b592a739925654788509e63a71b01e8a
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** globaler `finance_manager` oder Charity-Admin der betroffenen
Aktion. `finance_reader`, darunter der Demo-Benutzer Finn Finanzen, kann
Rechnungen und Zahlungsdaten lesen, aber keine Zahlung buchen oder
zurückbuchen.

## Zahlung erfassen

1. Öffne im Backoffice **Rechnungen**. Betreust du mehrere Aktionen, wähle
   rechts oben die richtige **Charity-Aktion**.
2. Die Ansicht **Offen** zeigt alle Rechnungen mit Restbetrag, auch
   **Teilweise bezahlt**; **Überfällig** nur die nach ihrem Fälligkeitstag.
   Öffne die Rechnung mit einem Klick oder mit den Tasten J/K und Enter.
3. Gleiche Rechnungsnummer, Empfänger, offenen Betrag und Zahlungsreferenz im
   Detailbereich mit dem tatsächlichen Bankumsatz ab.
4. Wähle **Zahlung erfassen**. Bei bezahlten oder überzahlten Rechnungen
   heißt die Schaltfläche **Weitere Zahlung erfassen**.
5. **Eingegangener Betrag in €** ist mit dem offenen Betrag vorbelegt. Ist
   der volle Betrag eingegangen, musst du nichts ändern. Sonst trage den
   tatsächlich eingegangenen Betrag ein; der Hinweis unter dem Feld zeigt,
   was danach offen bleibt oder wie viel zu viel eingegangen ist.
6. Trage das **Eingangsdatum** ein. **Verwendungszweck** ist optional; leer
   gilt die Zahlungsreferenz der Rechnung. **Notiz** ist optional, zum
   Beispiel „Rest kommt im Dezember“.
7. Bestätige mit **Zahlung erfassen**.

Jede Zahlung ist ein eigener Eintrag im Abschnitt **Zahlungen** mit Betrag,
Eingangsdatum, Verwendungszweck, Notiz, erfassender Person und Zeitpunkt.
Der Status folgt aus der Summe aller Einträge:

| Summe der Einträge          | Status                | Was du siehst                                 |
| --------------------------- | --------------------- | --------------------------------------------- |
| kleiner als der Betrag      | **Teilweise bezahlt** | **Eingegangen** und der verbleibende **Offen**-Betrag |
| genau der Betrag            | **Bezahlt**           | Stempel **Bezahlt**, offen 0,00 €             |
| größer als der Betrag       | **Überzahlt**         | Stempel **Überzahlt** und **Differenz erstatten** |

Bei einer Überzahlung überweist du die Differenz außerhalb von LeonAid an den
Sponsor zurück. LeonAid bucht keine Erstattung. Unter **Zahlungen** erscheint
jeder Eintrag in der Liste aller Zahlungseingänge. Wiederhole die Aktion
nicht, wenn die Bestätigung sichtbar ist.

## Falschen Eintrag zurückbuchen

Ein Eintrag wird nie gelöscht. Hast du einen Betrag falsch oder bei der
falschen Rechnung erfasst, oder hat die Bank eine Lastschrift zurückgegeben:

1. Öffne die Rechnung und wähle im Abschnitt **Zahlungen** beim Eintrag
   **Zurückbuchen**.
2. Gib den **Grund der Rückbuchung** mit mindestens acht Zeichen an.
3. Bestätige mit **Zurückbuchen**.

Der Eintrag bleibt durchgestrichen mit Grund, Person und Zeitpunkt sichtbar
und zählt nicht mehr zur Summe. Der offene Betrag und der Status werden neu
berechnet. Erfasse danach bei Bedarf den richtigen Betrag neu.

## Wenn etwas nicht klappt

- Ist keine Schaltfläche vorhanden, besitzt dein Konto nur Lesezugriff (der
  Hinweis **Nur lesen.** steht über der Liste) oder die Rechnung ist
  storniert.
- Meldet der Dialog, dass die Zahlungen inzwischen geändert wurden, hat eine
  andere Person gleichzeitig gebucht. Lade die Seite neu, prüfe den offenen
  Betrag und erfasse die Zahlung nur, wenn sie noch fehlt.
- Bei einem anderen Fehler bleibt die Rechnung unverändert. Gleiche die Daten
  erneut ab und wiederhole denselben Vorgang kontrolliert.
