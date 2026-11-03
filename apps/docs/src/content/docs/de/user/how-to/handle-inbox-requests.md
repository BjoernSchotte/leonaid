---
title: Eingänge bearbeiten
description: Öffentliche Kontaktanfragen lesen, zuweisen, den CRM-Kontakt klären, Aufgaben und Dateiversionen verknüpfen und abschließen.
docId: DOC-P045
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 2ffe04e8c92f8eb60033985eb35aa89e75e36b92
reviewer: Björn Schotte
---

**Rolle:** Systemadministration sieht alle Anfragen. Aktionsverwaltungen sehen
die Anfragen ihrer Aktion. Zugewiesene Mitglieder sehen die ihnen zugewiesenen
Anfragen. Öffne **Eingang** im Backoffice (`/admin/inbox`) oder in der App
(`/app/inbox`). Das Modul braucht die Module Aufgaben und Materialien. Hat
deine Installation das Modul abgeschaltet, fehlen der Eintrag und das
öffentliche Formular.

## Woher Anfragen kommen

Die öffentliche Startseite und jede veröffentlichte Aktionsseite zeigen das
Formular **Kontakt aufnehmen**. Archivierte Aktionen zeigen kein Formular.

- Das Formular fragt Vorname, Nachname, Betreff, Nachricht und eine
  E-Mail-Adresse oder Telefonnummer ab.
- Über dem Formular nennt ein Datenschutzhinweis den Zweck, die Speicherung in
  LeonAid und im CRM des Clubs und den Weg zur Löschung.
- Die anfragende Person muss die Einwilligung ankreuzen. Ohne Haken sendet das
  Formular nicht.
- Nach dem Senden erhält sie eine Referenznummer. Es wird keine E-Mail
  versendet.

Pro Adresse werden fünf Anfragen in zehn Minuten angenommen. Weitere werden
bis zum Ende des Zeitfensters abgelehnt.

## Eine Anfrage bearbeiten

1. Öffne **Eingang**. Die Ansicht **Offen** zeigt neue Anfragen und Anfragen
   in Bearbeitung, nach Status gruppiert. Weitere Ansichten sind **Mir
   zugewiesen**, **Kontakt klären** und **Alle**. Mit **Filter** (Taste F)
   filterst du nach Status, Kontakt, Zuständigkeit oder Aktion.
2. Wähle eine Anfrage, oder gehe mit J und K zu ihr und drücke Enter. Die
   Anfrage öffnet sich rechts neben der Liste, auf dem Handy als Blatt. Esc
   schließt sie wieder.
3. Ändere oben **Status** (Taste S) und **Zuständigkeit** (Taste A). Die
   Zuständigkeit ändert nur die Fallverwaltung, also die Systemadministration
   und die Aktionsverwaltung. Mit X wählst du mehrere Anfragen aus und änderst
   sie gemeinsam.
4. **Übernehmen** setzt eine neue Anfrage auf **In Bearbeitung**. Ist noch
   niemand zuständig, wirst du zuständig.
5. Schreibe unter **Interne Notizen** eine Notiz und wähle **Hinzufügen**. Nur
   Personen, die die Anfrage öffnen dürfen, sehen die Notizen.
6. Zum Abschließen wählst du **Abschließen …** oder den Status
   **Abgeschlossen**. Der Dialog **Anfrage abschließen** fragt eine
   **Abschlussnotiz** mit mindestens 10 Zeichen ab. **Abbrechen** ändert
   nichts. Eine abgeschlossene Anfrage öffnest du wieder, indem du einen
   anderen Status wählst.

Hat jemand die Anfrage inzwischen geändert, lehnt LeonAid deine Änderung ab
und lädt den aktuellen Stand. Deine Abschlussnotiz bleibt im Dialog erhalten.

## Den CRM-Kontakt klären

Nach dem Eingang legt ein Hintergrundauftrag die anfragende Person in Twenty
(dem CRM) an oder verknüpft eine vorhandene Person. Der Status **Kontakt
zugeordnet** bestätigt die Verknüpfung. Erst dann speichert LeonAid die
Einwilligung für diese Person. Die Ansicht **Kontakt klären** zeigt alle
Anfragen, deren Kontakt offen ist.

Steht unter **Kontakt in Twenty** der Status **Kontaktzuordnung benötigt
Klärung** oder **Kontaktzuordnung fehlgeschlagen**:

1. Passe Vorname und Nachname an und wähle **In Twenty suchen**.
2. Wähle in den Treffern die richtige Person.
3. Begründe die Wahl unter **Begründung der Zuordnung** und wähle **Zuordnung
   bestätigen**. LeonAid überschreibt die Daten der vorhandenen Person nicht.

## Aufgaben und Dateiversionen verknüpfen

- Wähle unter **Verknüpft** **Aufgabe verknüpfen** und dann unter
  **Bestehende Aufgabe auswählen** eine Aufgabe. Du kannst Aufgaben aus Listen
  wählen, die du bearbeiten darfst. Die Anfrage zeigt den aktuellen
  Aufgabenstatus.
- Wähle **Material verknüpfen**, dann ein Material und **Dateiversion
  einfügen**. Die Verknüpfung bleibt genau bei dieser Version. Ein Klick auf
  die Datei lädt diese Version herunter.

Eine Verknüpfung gewährt keinen Zugriff. Wer Aufgabe oder Material nicht öffnen
darf, sieht sie als nicht verfügbar.

## Löschwünsche

Bittet die anfragende Person um Löschung, führt die Systemadministration den
Datenschutz-Workflow mit ihrer E-Mail-Adresse im Backoffice unter
**Datenschutz** aus. Der Workflow entfernt Name, Kontaktdaten und Nachricht aus der Anfrage. Er
behält den Bearbeitungsverlauf und widerruft die gespeicherte Einwilligung.
Lösche die Twenty-Person im manuellen CRM-Schritt desselben Workflows.
