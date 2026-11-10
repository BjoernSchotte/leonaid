---
title: Impressum und Datenschutzerklärung pflegen
description: Pflichtangaben nach § 5 DDG und die Texte der Seite /datenschutz als Entwurf anlegen, freigeben und aktivieren.
docId: DOC-P048
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 30c252a22ffbcc5a41735023446c40168b5cc260
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
   Angaben erscheinen auch im Impressum. Wähle die **Rechtsform**, zum Beispiel
   „Eingetragener Verein (e. V.)“ oder „Nicht eingetragener Verein“. Sie
   bestimmt, ob ein Registereintrag ins Impressum gehört; LeonAid liest sie
   nicht aus dem Namen.
3. Wechsle in den Bereich **Impressum** und trage ein:
   - **Vertretungsberechtigte**: wer den Verein vertritt, mit Funktion, zum
     Beispiel der Vorstand nach § 26 BGB. Pflichtfeld.
   - **Telefon**: der zweite schnelle Kontaktweg neben der E-Mail-Adresse.
     Pflichtfeld.
   - **Registergericht** und **Registernummer**: der Registereintrag, den die
     gewählte Rechtsform verlangt, zum Beispiel „Amtsgericht Augsburg“ und „VR 1234“
     beim eingetragenen Verein, „HRB 5678“ bei einer GmbH oder gGmbH, „GnR 12“
     bei einer Genossenschaft. Beide Felder gehören zusammen. Das Impressum
     nennt das Register nach dem Kürzel der Nummer.
   - **Umsatzsteuer-ID**: wenn der Verein eine hat. Steht unter
     **Steuerkennung** eine Umsatzsteuer-ID, ist das Feld Pflicht.
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
   Erfassung ohne Netz auf dem Gerät speichert (eine Kurzform der eigenen
   Anmeldung mit Name, Aktionen und Rollen, eigene Sponsoren mit
   Ansprechperson, Telefonnummer und E-Mail-Adresse sowie noch nicht gesendete
   Einträge, bei Bestellungen mit Rechnungs- und Lieferadresse), dass sie nur
   auf diesem Gerät und verschlüsselt liegen, dass nicht gesendete Einträge
   nach 14 Tagen ablaufen und dass Abmelden in einer der beiden Apps oder die
   Anmeldung einer anderen Person alles löscht. Er beschreibt die
   Offline-Erfassung der Akquise-App. Behalte ihn nur, wenn die
   Offline-Erfassung aktiv ist, sonst lösche den ganzen Abschnitt. Die
   Vorlage markiert das mit einem `[[ … ]]`-Hinweis, der die Aktivierung
   blockiert, bis du ihn entfernst. Die System-Administration schaltet das
   Feature-Flag **Offline-Erfassung in der Akquise-App** erst ein, wenn ein
   Hinweis mit diesem Abschnitt aktiv ist. Den Text hat Claude Code
   vorgeschlagen; er braucht wie jede Fassung die Freigabe im
   Vier-Augen-Ablauf (Prüfung durch Björn Schotte offen).
   Der Hinweis enthält außerdem den Abschnitt „Benachrichtigungen auf deinem
   Gerät“: dass LeonAid je Gerät die Adresse beim Benachrichtigungsdienst
   des Browsers oder Betriebssystems (Google, Apple, Mozilla oder Microsoft),
   zwei Schlüssel und die Kennung des Browsers speichert, dass die Hinweise
   verschlüsselt sind und keine Namen, Adressen oder Beträge enthalten, dass
   die Einwilligung die Rechtsgrundlage ist und dass Ausschalten, Abmelden
   oder eine ungültige Adresse sie löscht. Behalte ihn nur, wenn
   Benachrichtigungen aktiv sind; auch er trägt einen `[[ … ]]`-Hinweis. Die
   System-Administration schaltet das Feature-Flag **Benachrichtigungen in
   der Akquise-App** erst ein, wenn ein Hinweis mit diesem Abschnitt aktiv
   ist. Auch diesen Text hat Claude Code vorgeschlagen (rechtliche Prüfung
   offen).
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
- **Die Rechtsform des Trägers ist nicht gewählt**: Wähle sie im Bereich
  **Träger & Anschrift**. Versionen von vor dem Update haben sie nur, wenn der
  Name „e. V.“ enthielt.
- **Im Impressum fehlt der Registereintrag**: Die gewählte Rechtsform hat ein
  Register (e. V., GmbH, gGmbH, eG). Trage Registergericht und Registernummer
  ein. Ein nicht eingetragener Verein, eine Stiftung und „Sonstige“ brauchen
  keinen Eintrag.
- **Die Steuerkennung ist eine Umsatzsteuer-ID; sie gehört auch ins
  Impressum**: Trage sie unter **Umsatzsteuer-ID** ein.
- **Die Datenschutzerklärung fehlt** oder **Der Datenschutzhinweis für
  Mitglieder fehlt**: Text im Bereich **Datenschutzerklärung** eintragen.
- **Ein Text enthält noch offene Vorlagen-Platzhalter**: Alle Stellen mit
  `[[ … ]]` ergänzen oder löschen.

Bearbeite den Entwurf, speichere ihn und lass ihn erneut freigeben.

## Nach einem Update

Kommen neue Pflichtangaben hinzu, kann die aktive Version danach
unvollständig sein. **Rechtliches** zeigt dann oben **Die aktive Version … ist
unvollständig** mit den fehlenden Punkten. Lege einen neuen Entwurf an, lass
ihn freigeben und aktiviere ihn. Felder, die eine ältere geöffnete
Verwaltungsseite nicht kennt, übernimmt LeonAid beim Speichern aus der
vorigen Version.
