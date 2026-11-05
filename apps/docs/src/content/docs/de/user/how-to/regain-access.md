---
title: Zugang wiederherstellen
description: Neuen Login-Code anfordern, eine Einladung erneut erhalten oder eine falsche E-Mail korrigieren lassen.
docId: DOC-P015
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 11720893881db3a1ebc4374a04d57e09a4fc61ec
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

LeonAid verwendet Magic Links und sechsstellige Einmalcodes statt eines
Passworts.

## Neuen Login anfordern

1. Öffne `/login`.
2. Trage genau die **Login-E-Mail** ein, mit der du eingeladen wurdest, und
   wähle **Login-Code anfordern**.
3. Öffne die zuletzt versendete LeonAid-E-Mail. Verwende den Magic Link oder
   trage unter **Sechsstelliger Code** den Code ein und wähle **Anmelden**.

Kommt kein Code an, wähle nach 30 Sekunden **Neuen Code senden**. Mit
**Andere E-Mail-Adresse** kehrst du zum ersten Schritt zurück und korrigierst
die Adresse.

Die Antwort beim Anfordern ist absichtlich auch für unbekannte Adressen gleich.
Erhältst du keine Nachricht, prüfe Schreibweise und Spamordner und frage danach
den zuständigen Charity- oder System-Admin. Bei **Zu viele Versuche** wartest du
zehn Minuten.

## Einladung erneut erhalten

Ein abgelaufener, widerrufener oder bereits verwendeter Einladungslink wird
nicht reaktiviert. Bitte den zuständigen Admin, die Einladung kontrolliert neu
zu senden oder die Adresse zu korrigieren. Öffne danach `/invite`, trage die
eingeladene E-Mail und den neuesten Code ein und wähle **Einladung bestätigen**.

## Falsche Login-E-Mail

Mitglieder können ihre Adresse nicht selbst ändern. Ein System-Admin startet
die Änderung nach frischer Anmeldung. Bis zur Bestätigung an der neuen Adresse
bleibt die bisherige Adresse aktiv. Nach der Bestätigung werden die Sitzungen
des betroffenen Kontos widerrufen; melde dich mit der neuen Adresse neu an.
