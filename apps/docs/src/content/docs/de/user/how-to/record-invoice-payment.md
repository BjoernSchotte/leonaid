---
title: Rechnung als bezahlt erfassen
description: Eine offene Rechnung nach Bankabgleich mit der exakten Vollzahlung abschließen.
docId: DOC-P014
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

**Rolle:** globaler `finance_manager` oder Charity-Admin der betroffenen
Aktion. `finance_reader`, darunter der Demo-Benutzer Finn Finanzen, kann
Rechnungen und Zahlungsdaten lesen, aber keine Zahlung buchen.

1. Öffne im Backoffice **Rechnungen** und wähle die richtige
   **Charity-Aktion**.
2. Filtere bei Bedarf nach **Offen** und öffne den Beleg im **Belegjournal**.
3. Gleiche Rechnungsnummer, Empfänger, Bruttobetrag und Zahlungsreferenz mit dem
   tatsächlichen Bankumsatz ab.
4. Wähle **Zahlung erfassen**.
5. Trage **Zahlungsbetrag**, **Geldeingang am** und **Zahlungsreferenz** ein.
   Der Betrag muss exakt dem vollständigen offenen Rechnungsbetrag entsprechen;
   Teil- und Überzahlungen werden nicht gespeichert.
6. Wähle **Vollzahlung verbuchen**.

Die Karte zeigt danach **Vollständig bezahlt** und den Status **Erledigt**. Im
Zahlungsdatensatz stehen Betrag, Eingangsdatum, Referenz, buchende Person und
Zeitpunkt; der offene Posten sinkt auf null. Wiederhole die Aktion nicht, wenn
diese Bestätigung sichtbar ist.

Ist die Schaltfläche nicht vorhanden, besitzt dein Konto nur Lesezugriff oder
der Beleg ist bereits bezahlt beziehungsweise storniert. Bei einem Fehler
bleibt der Beleg offen; gleiche die Daten erneut ab und wiederhole denselben
Vorgang kontrolliert.
