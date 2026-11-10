---
title: Benachrichtigungen einschalten
description: In der Akquise-App Benachrichtigungen für Wiedervorlagen, neue Bestellungen, Aufgaben und Lieferungen auf dem eigenen Gerät einschalten, testen und wieder ausschalten.
docId: DOC-P058
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: b1c08d3c04dbf7a46d1bb477753e36ad369a6fec
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Mitglied mit Zugang zur Akquise-App. Benachrichtigungen gibt es
nur, wenn die System-Administration das Feature-Flag **Benachrichtigungen in
der Akquise-App** eingeschaltet hat. Dann steht im Menü **Mehr** der Eintrag
**Benachrichtigungen**. Das Flag kommt erst an, wenn der aktive
Datenschutzhinweis für Mitglieder den Abschnitt „Benachrichtigungen auf
deinem Gerät“ enthält (siehe
[Impressum und Datenschutzerklärung pflegen](../maintain-legal-pages/)) und
der Betreiber den Schlüssel hinterlegt hat (siehe
[Voraussetzungen und Konfiguration](../../../ops/reference/requirements-and-configuration/)).

## Voraussetzungen

- Ein aktueller Chrome, Edge, Firefox oder Safari.
- **iPhone und iPad:** LeonAid muss auf dem Home-Bildschirm liegen und von
  dort geöffnet sein (iOS/iPadOS 16.4 oder neuer). In einem Safari-Tab gibt
  es keine Benachrichtigungen. So legst du LeonAid dort ab: LeonAid in Safari
  öffnen, **Teilen** antippen, **Zum Home-Bildschirm** wählen.
- Du bist auf dem Gerät angemeldet, auf dem die Benachrichtigungen ankommen
  sollen. Jedes Gerät schaltest du einzeln ein.

## Einschalten

1. Öffne in der Akquise-App **Mehr** und dann **Benachrichtigungen**.
2. Wähle **Benachrichtigungen einschalten**.
3. Dein Browser fragt, ob LeonAid Benachrichtigungen senden darf. Wähle
   **Zulassen**.
4. Unter **Worüber möchtest du Bescheid bekommen?** schaltest du ein, was du
   brauchst. Jede Art ist aus, bis du sie einschaltest. Die Schalter gelten
   für alle deine Geräte.

| Schalter              | Wann die Benachrichtigung kommt                                          | Was sie öffnet     |
| --------------------- | ------------------------------------------------------------------------ | ------------------ |
| **Wiedervorlagen**    | Einmal am Tag ab 8 Uhr, wenn Wiedervorlagen fällig oder überfällig sind. | **Wiedervorlagen** |
| **Neue Bestellungen** | Wenn unter **Neues** eine Bestellung für dich eingeht.                   | **Neues**          |
| **Aufgaben**          | Wenn dir jemand eine Aufgabe zuweist.                                    | **Aufgaben**       |
| **Lieferungen**       | Wenn dir Lieferungen für eine Tour zugewiesen werden.                    | Auslieferung       |

Du siehst nur die Schalter, die zu deinen Rollen passen: **Wiedervorlagen**
als Akquisiteur, **Neue Bestellungen** als Akquisiteur oder Charity-Admin,
**Lieferungen** als Ausfahrer. **Aufgaben** gibt es, wenn das Aufgaben-Modul
eingeschaltet ist.

## Ergebnis prüfen

Wähle unter **Dieses Gerät** **Test senden**. Die Seite meldet **Der Test ist
unterwegs.** Kurz danach zeigt dein Gerät die Benachrichtigung
**Benachrichtigungen funktionieren auf diesem Gerät.** Ein Tipp darauf öffnet
LeonAid.

## Was in einer Benachrichtigung steht

Eine Benachrichtigung nennt die Art und eine Anzahl, zum Beispiel **3
Wiedervorlagen sind fällig.** Sie enthält keine Namen, Adressen oder Beträge.
Ein Tipp darauf öffnet die passende Seite in LeonAid.

Zu jeder Art kommt höchstens eine Benachrichtigung in 15 Minuten. Was in
dieser Zeit dazukommt, zählt LeonAid zusammen und meldet es danach in einer
Benachrichtigung. Für etwas, das du selbst ausgelöst hast, bekommst du keine.

## Ausschalten

- **Eine Art:** Schalte den Schalter aus.
- **Dieses Gerät:** Wähle **Auf diesem Gerät ausschalten**. LeonAid löscht
  die Adresse dieses Geräts sofort.
- **Abmelden:** Wenn du dich auf dem Gerät abmeldest, enden die
  Benachrichtigungen dort. Nach der nächsten Anmeldung schaltest du sie auf
  dem Gerät wieder ein; deine Schalter bleiben, wie sie waren.
- **90 Tage ohne Öffnen:** Öffnest du die App auf einem Gerät 90 Tage lang
  nicht, endet dort deine Anmeldung und mit ihr die Benachrichtigungen.
  Melde dich an und öffne die App; dann kommen sie wieder.

## Wenn es nicht klappt

| Was du siehst                                                 | Was es bedeutet und was hilft                                                                                                                                                           |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Im Menü **Mehr** fehlt **Benachrichtigungen**                 | Dein Club hat die Funktion nicht eingeschaltet.                                                                                                                                         |
| **Benachrichtigungen sind noch nicht eingerichtet.**          | Der Betreiber hat keinen Schlüssel hinterlegt. Wende dich an die System-Administration.                                                                                                 |
| **Lege LeonAid zuerst auf den Home-Bildschirm.**              | iPhone oder iPad im Safari-Tab. Folge den drei Schritten auf der Seite.                                                                                                                 |
| **Dieser Browser kann keine Benachrichtigungen empfangen.**   | Nutze einen aktuellen Chrome, Edge, Firefox oder Safari.                                                                                                                                |
| **Benachrichtigungen sind im Browser blockiert.**             | Du hast die Frage des Browsers abgelehnt. Erlaube Benachrichtigungen für die Seite in den Einstellungen des Browsers (Schloss- oder Einstellungssymbol neben der Adresse) und lade neu. |
| **Dieses Gerät konnte nicht angemeldet werden.**              | Der Browser hat den Benachrichtigungsdienst nicht erreicht. Prüfe die Verbindung und versuche es erneut.                                                                                |
| **Das waren viele Tests in kurzer Zeit.**                     | Mehr als fünf Tests in zehn Minuten, egal von welchem Gerät. Warte ein paar Minuten.                                                                                                    |
| Der Test kommt nicht an                                       | Prüfe in den Einstellungen des Geräts, ob Benachrichtigungen für LeonAid (oder den Browser) erlaubt sind und kein „Nicht stören“ aktiv ist. Schalte das Gerät dann aus und wieder ein.  |
| Nach dem Abmelden oder nach langer Pause kommt nichts mehr    | Melde dich an, öffne **Benachrichtigungen** und schalte sie auf dem Gerät wieder ein. Nach 90 Tagen ohne Öffnen der App endet die Anmeldung auf dem Gerät.                              |
| LeonAid konnte die Anmeldung des Geräts gerade nicht erneuern | Die App wurde in der letzten Stunde sehr oft geöffnet. Das Gerät bleibt eingeschaltet; **Test senden** und **Auf diesem Gerät ausschalten** sind in etwa einer Stunde wieder da.        |
| **Du hast schon zehn Geräte angemeldet.**                     | Schalte Benachrichtigungen auf einem Gerät aus, das du nicht mehr nutzt.                                                                                                                |

## Grenzen

- Benachrichtigungen sind ein Hinweis, keine Zustellgarantie. Ist dein Gerät
  länger als einen Tag aus, verfällt eine Benachrichtigung.
- Es gibt keine Ruhezeiten und keine Einstellung je Gerät. Du kannst
  höchstens zehn Geräte anmelden.
- Erreicht LeonAid ein Gerät mehrere Tage lang nicht, entfernt es das Gerät.
  Schalte Benachrichtigungen dort dann neu ein.
- Weitere Grenzen stehen unter [Bekannte Grenzen](../../../known-limits/).
