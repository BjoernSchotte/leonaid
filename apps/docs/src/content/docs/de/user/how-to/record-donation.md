---
title: Spende erfassen
description: Eine Spende erfassen, die Spendenzusage senden, den Zahlungseingang buchen oder zurücknehmen und eine Spende stornieren.
docId: DOC-P059
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 38a834b682cdd63daf56fc53a1a92929c0f60797
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der betroffenen Aktion oder globaler
`finance_manager`. Senden kann nur der Charity-Admin der Aktion.
`finance_reader` sieht Spenden, Zahlungen und Spendenzusagen, kann aber nichts
ändern.

Eine Spende hat keine Gegenleistung. Sie bekommt deshalb keine Rechnung,
sondern eine **Spendenzusage**: ein PDF mit Betrag, Spendenkonto und der
Nummer der Spende als Verwendungszweck. Die Zuwendungsbestätigung für die
Steuererklärung stellt LeonAid in dieser Version noch nicht aus.

## Voraussetzungen

- Die Aktion hat die Fähigkeit **Spenden**. Sie wird beim Anlegen der Aktion
  gewählt und lässt sich ändern, solange die Aktion im Entwurf oder in der
  Planung ist.
- Unter **Rechtliches** ist der Teil **Spenden** ausgefüllt und aktiv
  (siehe
  [Impressum und Datenschutzerklärung pflegen](/de/user/how-to/maintain-legal-pages/#empfangende-körperschaft-für-spenden)).
  Er nennt die Körperschaft, die Spenden empfängt. Fehlt er, zeigt die Seite
  **Spenden** einen Hinweis, und es lässt sich keine Spende erfassen.

Der Eintrag **Spenden** erscheint in der Navigation unter **Arbeit**, sobald
du die Finanzen mindestens einer Aktion mit dieser Fähigkeit lesen oder
verwalten darfst.

## Spende erfassen

1. Öffne im Backoffice **Spenden** und wähle oben die Aktion.
2. Wähle **Spende erfassen**.
3. Trage **Name des Spenders**, **Straße und Hausnummer**, **Postleitzahl**
   und **Ort** ein. Schreibe den Namen so, wie er später auf der
   Zuwendungsbestätigung stehen soll.
4. Trage die **E-Mail** ein, wenn du die Spendenzusage per E-Mail senden
   willst. Das Feld ist freiwillig.
5. Trage den **Betrag in €** ein, von 1,00 € bis 1.000.000,00 €. Das ist der
   zugesagte Betrag.
6. Bestätige mit **Spende erfassen**. Weil dabei ein Beleg entsteht,
   bestätigst du deine Anmeldung gegebenenfalls erneut.

Die Spende erhält sofort eine Nummer aus dem Nummernkreis der Spendenzusagen,
zum Beispiel **SP26-0007**. Der Nummernkreis gilt für die ganze Installation.
Name, Adresse und Betrag lassen sich danach nicht mehr ändern. Bei einem
Fehler stornierst du die Spende und erfasst sie neu.

## Spendenzusage ansehen und senden

Öffne die Spende in der Liste. Der Abschnitt **Spendenzusage** zeigt Nummer
und Datum. Das PDF wird kurz nach dem Erfassen erzeugt und lässt sich dann
ansehen und herunterladen. Es steht außerdem unter **Rechnungen** in der
Ansicht **Dokumente**.

Die Spendenzusage zeigt Name, Anschrift, Finanzamt, Steuernummer und Konto
der empfangenden Körperschaft, nicht die des Rechnungsausstellers. Sie ist
keine Rechnung und enthält keine Steuerzeilen.

Wähle im Bereich **Versand der Spendenzusage** die Schaltfläche
**Spendenzusage senden**, sobald das PDF bereitsteht. Die E-Mail geht mit dem
PDF im Anhang an die E-Mail-Adresse des Spenders. Der Bereich zeigt danach,
ob die E-Mail zugestellt wurde. Ein fehlgeschlagener Versand lässt sich dort
erneut starten. Mit **Erneut senden** schickst du dieselbe Spendenzusage
bewusst noch einmal.

Ist keine E-Mail-Adresse gespeichert, kann LeonAid die Spendenzusage nicht
senden: Lade das PDF herunter und gib es auf anderem Weg weiter.

## Zahlung erfassen

1. Öffne die Spende und wähle **Zahlung erfassen**.
2. Prüfe den **eingegangenen Betrag**. Vorbelegt ist der zugesagte Betrag.
   Ist mehr oder weniger angekommen, trage ein, was angekommen ist.
3. Trage das **Eingangsdatum** ein. Es liegt nicht vor dem Tag der Zusage und
   nicht in der Zukunft.
4. Bestätige mit **Zahlung erfassen**.

Die Spende ist danach **Bezahlt**. Es zählt der eingegangene Betrag, nicht
die Zusage. Der Detailbereich nennt den Unterschied.

Eine Spende hat genau eine Zahlung. Zahlt ein Spender in zwei Teilen, erfasst
du den zweiten Teil als eigene Spende.

## Zahlung zurücknehmen

Hast du eine Zahlung der falschen Spende zugeordnet, wähle im Abschnitt
**Zahlung** die Schaltfläche **Zahlung zurücknehmen** und trage den **Grund
der Rücknahme** ein, mindestens acht Zeichen. Die Spende ist danach wieder
**Offen**. Unter **Zurückgenommene Zahlungen** bleibt sichtbar, was erfasst
war, wer es erfasst und wer es zurückgenommen hat.

## Spende stornieren

Nur eine Spende ohne erfasste Zahlung lässt sich stornieren. Wähle **Spende
stornieren** und trage den **Grund der Stornierung** ein. Die Spende bleibt
mit Nummer, Daten und Spendenzusage erhalten, zählt aber nicht mehr zu den
offenen Zusagen. Ein Storno lässt sich nicht zurücknehmen.

Bei einer bezahlten Spende nimmst du zuerst die Zahlung zurück.

## Summen

Die Seite **Spenden** zeigt oben **Eingegangen** und **Zugesagt, noch offen**
für die gewählte Aktion. Die Übersicht der Aktion nennt beide Summen unter
**Weitere Kennzahlen**.

## Datenschutz

Spenden und ihre Dokumente sind steuerliche Nachweise. Eine
Datenschutz-Löschung nennt die Spenden der Person, lässt sie aber wie
ausgestellte Rechnungen für die freigegebene Aufbewahrungsfrist unverändert.
