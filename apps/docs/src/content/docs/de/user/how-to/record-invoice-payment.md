---
title: Rechnung als bezahlt erfassen
description: Eine offene Rechnung nach Bankabgleich mit der exakten Vollzahlung abschließen.
docId: DOC-P014
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 1c054b0fb55c59b9f884aee956b431a519ce521d
reviewer: Björn Schotte
---

**Rolle:** globaler `finance_manager` oder Charity-Admin der betroffenen
Aktion. `finance_reader`, darunter der Demo-Benutzer Finn Finanzen, kann
Rechnungen und Zahlungsdaten lesen, aber keine Zahlung buchen.

1. Öffne im Backoffice **Rechnungen**. Betreust du mehrere Aktionen, wähle
   rechts oben die richtige **Charity-Aktion**.
2. Die Ansicht **Offen** zeigt alle Rechnungen mit Restbetrag, **Überfällig**
   nur die nach ihrem Fälligkeitstag. Öffne die Rechnung mit einem Klick oder
   mit den Tasten J/K und Enter.
3. Gleiche Rechnungsnummer, Empfänger, Bruttobetrag und Zahlungsreferenz im
   Detailbereich mit dem tatsächlichen Bankumsatz ab.
4. Wähle **Zahlung erfassen**.
5. Trage im Dialog **Eingegangener Betrag in €** und **Eingangsdatum** ein.
   **Verwendungszweck** ist optional; leer gilt die Zahlungsreferenz der
   Rechnung. Der Betrag muss exakt dem vollständigen offenen Rechnungsbetrag
   entsprechen; Teil- und Überzahlungen werden nicht gespeichert.
6. Bestätige mit **Zahlung erfassen**.

Die Rechnung trägt danach den Stempel **Bezahlt** und den Status **Bezahlt**.
Der Abschnitt **Zahlung** zeigt Betrag, Eingangsdatum, Verwendungszweck,
erfassende Person und Zeitpunkt; der offene Posten sinkt auf null. Unter
**Zahlungen** erscheint der Eingang in der Liste aller Zahlungen. Wiederhole die
Aktion nicht, wenn diese Bestätigung sichtbar ist.

Ist die Schaltfläche nicht vorhanden, besitzt dein Konto nur Lesezugriff (der
Hinweis **Nur lesen.** steht über der Liste) oder die Rechnung ist bereits
bezahlt beziehungsweise storniert. Bei einem Fehler bleibt die Rechnung offen;
gleiche die Daten erneut ab und wiederhole denselben Vorgang kontrolliert.
