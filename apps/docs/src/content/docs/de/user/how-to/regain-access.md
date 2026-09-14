---
title: Zugang wiederherstellen
description: Neuen Login-Code anfordern, eine Einladung erneut erhalten oder eine falsche E-Mail korrigieren lassen.
docId: DOC-P015
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

LeonAid verwendet Magic Links und sechsstellige Einmalcodes statt eines
Passworts.

## Neuen Login anfordern

1. Öffne `/login`.
2. Trage genau die **Login-E-Mail** ein, mit der du eingeladen wurdest, und
   wähle **Login-Code anfordern**.
3. Öffne die zuletzt versendete LeonAid-E-Mail. Verwende den Magic Link oder
   trage den **Sechsstelligen Code** ein und wähle **Anmelden**.

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
