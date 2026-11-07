---
title: Aufgaben planen und verfolgen
description: Aufgabenlisten anlegen und freigeben, Aufgaben zuweisen und den eigenen Tag in Web und App planen.
docId: DOC-P041
audience: [user]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: 1098635f282c7ab89dbaf25be05f645248026ddd
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** jedes aktive Konto. Öffne **Aufgaben** in der Verwaltung
(`/admin/tasks`) oder in der App (`/app/tasks`). Beide zeigen dieselben Listen
und Aufgaben. Hat deine Installation das Modul abgeschaltet, fehlt der Eintrag.

## Ansichten

Oben stehen die Ansichten **Mein Plan**, **Für mich**, **Alle offenen**,
**Nach Liste** und **Erledigt**; in einer Liste **Offen**, **Für mich**,
**Alle** und **Erledigt**. Mit **Filter** (Taste `F`), der Gruppierung und der
Sortierung passt du eine Ansicht an; **Ansicht speichern** merkt sie sich in
diesem Browser.

## Liste anlegen und freigeben

1. Wähle **Liste wechseln**, dann **Neue Liste**, gib den **Name der Liste**
   ein und wähle **Liste anlegen**. Die Liste ist zunächst nur für dich
   sichtbar.
2. Zum Freigeben öffne in der Liste **Zugriff verwalten**. Füge ein bestehendes
   aktives Konto per E-Mail-Adresse hinzu und wähle **Lesen** oder
   **Bearbeiten**.
3. Eine Liste kann zu einer Charity-Aktion gehören. Dann gewähren auch deren
   Aktionsrollen Zugriff; das Entfernen eines zusätzlichen Mitglieds entzieht
   keine Aktionsmitgliedschaft.

## Aufgaben anlegen und bearbeiten

1. Wähle **Aufgabe anlegen** (Taste `C`). Im Feld **Aufgabe schnell erfassen**
   tippst du den Titel und bestätigst mit Enter; außerhalb einer Liste wählst
   du daneben die Liste. Die Aufgabe startet mit dem Status **Offen**. In
   **Mein Plan** landet sie gleich unter **Heute**.
2. Wähle eine Aufgabe (oder `J`/`K` und Enter), um ihre Details rechts zu
   öffnen, in der App als ganze Seite. Setze dort Beschreibung, eine zuständige
   Person unter **Zuständigkeit auswählen**, einen Abschnitt unter **Abschnitt
   auswählen** und Zeiten unter **Termine und Wiedervorlage**. Wähle
   **Speichern**.
3. Unter **Schritte** ergänzt du Schritte mit **Neuer Schritt** und **Schritt
   hinzufügen**, hakst sie ab oder entfernst sie. Jede Änderung wird sofort
   gespeichert.
4. Unter **Priorität und Schlagworte** markierst du **Hohe Priorität**, wählst
   Schlagworte der Liste oder legst mit **Neues Schlagwort** und **Schlagwort
   anlegen** eines an. Wähle **Speichern**. Die Liste zeigt danach Priorität,
   Schlagworte und den Fortschritt der Schritte.
5. Status (`S`), Plan (`W`), Zuständig (`A`) und Priorität (`P`) änderst du
   auch direkt in der Liste, für eine Zeile oder alle mit `X` ausgewählten.
   **Erledigt** in der Auswahlleiste schließt die ausgewählten Aufgaben ab.
   Nach einer Änderung bietet die Meldung **Rückgängig** an.
6. **Reihenfolge ändern**: In einer Liste mit der Sortierung **Reihenfolge**
   und in **Mein Plan** ziehst du eine Aufgabe am Griff, nimmst den Griff mit
   der Leertaste auf und bewegst ihn mit den Pfeiltasten, oder nutzt in den
   Details **Nach oben**, **Nach unten**, **In Abschnitt** und **Für Tag
   planen**. Während die Bewegung gespeichert wird, bleibt der Tastaturfokus
   auf dem Griff oder der Schaltfläche, die du benutzt hast; nach einer
   Bewegung per Tastatur bleibt er auf dem Griff der verschobenen Aufgabe,
   sodass du dort weitermachen kannst.

Hat jemand die Aufgabe inzwischen geändert, wird das Speichern abgelehnt und
deine Eingabe bleibt im Formular. Lade den aktuellen Stand und speichere erneut.
Verlässt du die Details mit ungespeicherten Änderungen, fragt LeonAid vorher
nach.

## Den eigenen Tag planen

**Für mich** zeigt die offenen Aufgaben, für die du zuständig bist. Unter
**Persönliche Planung** in den Details legst du eine Aufgabe auf einen Tag, auf
**Irgendwann** oder lässt sie **Nicht geplant**. Deine Planung ist privat:
Andere Mitglieder sehen weder deinen Plan noch deine persönliche Reihenfolge.
**Mein Plan** gruppiert nach **Heute**, **Bis heute fällig** (heute fällig
oder überfällig), **Diese Woche**, **Später** und **Irgendwann**.

Eine zurückgestellte Aufgabe (**Zurückgestellt**) bleibt bis zum gewählten
Zeitpunkt aus **Offen** und **Alle offenen** ausgeblendet; der Filter
**Wiedervorlage** zeigt sie. Die Fälligkeit bleibt unverändert.
