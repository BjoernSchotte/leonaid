---
title: Eingänge bearbeiten
description: Öffentliche Kontaktanfragen lesen, zuweisen, den CRM-Kontakt klären, Aufgaben und Dateiversionen verknüpfen und abschließen.
docId: DOC-P045
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: e16f01e1b86aab7869fc2937806dbbc15fb04e47
reviewer: Björn Schotte
---

**Rolle:** Systemadministration sieht alle Anfragen. Aktionsverwaltungen sehen
die Anfragen ihrer Aktion. Zugewiesene Mitglieder sehen die ihnen zugewiesenen
Anfragen. Öffne **Eingänge** im Backoffice (`/admin/inbox`) oder in der App
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

1. Öffne eine Anfrage aus **Alle Eingänge**. Filtere bei Bedarf nach Status:
   **Neu**, **In Bearbeitung** oder **Abgeschlossen**.
2. Setze unter **Bearbeitung** den Status und die **Zuständigkeit**. Wähle dann
   **Bearbeitung speichern**.
3. Schreibe unter **Interne Notizen** eine Notiz und wähle **Notiz speichern**.
   Nur Personen, die die Anfrage öffnen dürfen, sehen die Notizen.
4. Zum Abschließen wählst du **Abgeschlossen**, schreibst eine
   **Abschlussnotiz** und speicherst. Eine abgeschlossene Anfrage kannst du
   später wieder öffnen.

Hat jemand die Anfrage inzwischen gespeichert, lehnt LeonAid dein Speichern ab
und behält deinen Entwurf. Lade bewusst den aktuellen Stand, bevor du erneut
speicherst.

## Den CRM-Kontakt klären

Nach dem Eingang legt ein Hintergrundauftrag die anfragende Person in Twenty
(dem CRM) an oder verknüpft eine vorhandene Person. Der Status **Kontakt
zugeordnet** bestätigt die Verknüpfung. Erst dann speichert LeonAid die
Einwilligung für diese Person.

Steht der Status auf **Kontaktzuordnung benötigt Klärung**:

1. Passe unter **Bestehenden Kontakt suchen** die Namen an und wähle **In
   Twenty suchen**.
2. Wähle unter **Kontakt auswählen** die richtige Person.
3. Wähle **Kontaktzuordnung bestätigen**. LeonAid überschreibt die Daten der
   vorhandenen Person nicht.

## Aufgaben und Dateiversionen verknüpfen

- Wähle unter **Aufgaben** **Aufgabe verknüpfen** und dann unter **Bestehende
  Aufgabe auswählen** eine Aufgabe. Du kannst Aufgaben aus Listen wählen, die
  du bearbeiten darfst. Die Anfrage zeigt den aktuellen Aufgabenstatus.
- Wähle unter **Materialien** **Material verknüpfen**, dann ein Material und
  **Dateiversion einfügen**. Die Verknüpfung bleibt genau bei dieser Version.

Eine Verknüpfung gewährt keinen Zugriff. Wer Aufgabe oder Material nicht öffnen
darf, sieht sie als nicht verfügbar.

## Löschwünsche

Bittet die anfragende Person um Löschung, führt die Systemadministration den
Datenschutz-Workflow mit ihrer E-Mail-Adresse im Backoffice unter
**Datenschutz** aus. Der Workflow entfernt Name, Kontaktdaten und Nachricht aus der Anfrage. Er
behält den Bearbeitungsverlauf und widerruft die gespeicherte Einwilligung.
Lösche die Twenty-Person im manuellen CRM-Schritt desselben Workflows.
