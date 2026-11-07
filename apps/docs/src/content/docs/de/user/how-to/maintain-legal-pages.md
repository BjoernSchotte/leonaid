---
title: Impressum und Datenschutzerklärung pflegen
description: Pflichtangaben nach § 5 DDG und die Texte der Seite /datenschutz als Entwurf anlegen, freigeben und aktivieren.
docId: DOC-P048
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** System-Admin. Du brauchst eine zweite Person mit Systemverwaltung:
Wer den Entwurf anlegt, darf ihn nicht selbst freigeben (Vier-Augen-Prinzip).

Impressum und Datenschutzerklärung gelten für die ganze Installation, also für
alle Aktionsseiten, Kampagnenseiten, Umfragen und Anmeldeseiten. Die Seiten
heißen immer `/impressum` und `/datenschutz`. Jede öffentliche Seite, die
Anmeldung, die Einladung und die Bestätigung einer neuen Login-E-Mail verlinken
beide im Fuß. In der Verwaltung und in der Akquise-App stehen die Links unter
deinem Namen beziehungsweise im Menü **Mehr**.

## Impressum ausfüllen

1. Öffne in der Verwaltung **Rechtliches** und wähle **Neuen Entwurf beginnen**
   (oder **Entwurf bearbeiten**, wenn schon ein Entwurf offen ist).
2. Prüfe im Bereich **Träger & Anschrift** Name, Anschrift und E-Mail. Diese
   Angaben erscheinen auch im Impressum.
3. Wechsle in den Bereich **Impressum** und trage ein:
   - **Vertretungsberechtigte**: wer den Verein vertritt, mit Funktion, zum
     Beispiel der Vorstand nach § 26 BGB. Pflichtfeld.
   - **Telefon**: der zweite schnelle Kontaktweg neben der E-Mail-Adresse.
     Pflichtfeld.
   - **Registergericht** und **Registernummer**: bei einem eingetragenen
     Verein das Vereinsregister, zum Beispiel „Amtsgericht Augsburg“ und
     „VR 1234“. Beide Felder gehören zusammen.
   - **Umsatzsteuer-ID**: nur, wenn der Verein eine hat.
   - **Inhaltlich verantwortlich** und **Anschrift der verantwortlichen
     Person**: für redaktionelle Inhalte wie Kampagnenseiten und Neuigkeiten
     (§ 18 Abs. 2 MStV). Beide Felder gehören zusammen.
4. Wähle **Als Entwurf speichern**. Gespeichert wird immer der ganze Entwurf
   mit allen Bereichen.

## Datenschutzerklärung ausfüllen

1. Wechsle im Entwurf in den Bereich **Datenschutzerklärung**.
2. Beim ersten Entwurf stehen in **Datenschutzerklärung** und
   **Datenschutzhinweis für Mitglieder** Vorlagen. Sie beschreiben nur, was
   LeonAid selbst tut. Alles in doppelten eckigen Klammern `[[ … ]]` muss der
   Verein ergänzen oder löschen, zum Beispiel Rechtsgrundlagen, Dienstleister
   und die zuständige Aufsichtsbehörde.
3. Der **Datenschutzhinweis für Mitglieder** enthält den Abschnitt
   „Speicherung auf deinem Gerät“: welche Daten die Akquise-App für die
   Erfassung ohne Netz auf dem Gerät speichert (eigene Sponsoren mit
   Ansprechperson, Telefonnummer und E-Mail-Adresse sowie noch nicht gesendete
   Einträge), dass sie verschlüsselt sind, dass nicht gesendete Einträge nach
   14 Tagen ablaufen und dass Abmelden oder die Anmeldung einer anderen Person
   alles löscht. Prüfe ihn wie den übrigen Text.
4. Format: Trenne Absätze durch eine Leerzeile. `## ` am Zeilenanfang beginnt
   eine Überschrift, `- ` einen Listenpunkt.
5. Wähle **Als Entwurf speichern**.

Die Seite `/datenschutz` zeigt außerdem den Verantwortlichen und den
Datenschutz-Kontakt, den Datenschutzhinweis des Bestellformulars mit seiner
Rechtsgrundlage (Abschnitt „Bestellungen über Aktionsseiten“) und den
Mitgliederhinweis (Abschnitt „Für Mitglieder“). Der kurze Hinweis direkt am
Bestellformular bleibt und verlinkt auf die vollständige Seite.

## Freigeben und aktivieren

1. Eine zweite Person mit Systemverwaltung öffnet **Rechtliches**, prüft die
   Änderungen, trägt eine **Nachweis-ID der Freigabe** ein und wählt
   **Entwurf freigeben**.
2. Danach wählt eine der beiden Personen **Version … aktivieren** und
   bestätigt mit **Jetzt aktivieren**.
3. Nach spätestens einer Minute zeigen `/impressum` und `/datenschutz` die neue
   Version.

## Wenn sich die Version nicht aktivieren lässt

Im Produktivbetrieb nennt der Entwurf unter **Noch nicht aktivierbar**, was
fehlt:

- **Im Impressum fehlen die vertretungsberechtigten Personen** oder **fehlt
  die Telefonnummer**: Bereich **Impressum** ergänzen.
- **Im Impressum fehlt der Eintrag im Vereinsregister**: Der Name des Trägers
  enthält „e. V.“. Trage Registergericht und Registernummer ein.
- **Die Datenschutzerklärung fehlt** oder **Der Datenschutzhinweis für
  Mitglieder fehlt**: Text im Bereich **Datenschutzerklärung** eintragen.
- **Ein Text enthält noch offene Vorlagen-Platzhalter**: Alle Stellen mit
  `[[ … ]]` ergänzen oder löschen.

Bearbeite den Entwurf, speichere ihn und lass ihn erneut freigeben.
