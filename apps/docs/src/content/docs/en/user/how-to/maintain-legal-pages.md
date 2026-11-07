---
title: Maintain the Impressum and the privacy policy
description: Create, approve and activate the § 5 DDG details and the texts of the /datenschutz page as a draft.
docId: DOC-P048
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** system admin. You need a second person with system administration:
whoever creates the draft cannot approve it (four-eyes principle).

The Impressum and the privacy policy apply to the whole installation: all
action pages, campaign pages, surveys and sign-in pages. The pages are always
`/impressum` and `/datenschutz`. Every public page, sign-in, the invitation and
the confirmation of a new login e-mail link both in the footer. In the admin
app and in the acquisition app, the links are below your name or in the
**Mehr** menu.

## Fill in the Impressum

1. In the admin app, open **Rechtliches** and choose **Neuen Entwurf
   beginnen** (or **Entwurf bearbeiten** if a draft is open already).
2. In **Träger & Anschrift**, check name, address and e-mail. These also
   appear in the Impressum.
3. Switch to the **Impressum** part and enter:
   - **Vertretungsberechtigte**: who represents the club, with their function,
     for example the board under § 26 BGB. Required.
   - **Telefon**: the second fast contact channel next to the e-mail address.
     Required.
   - **Registergericht** and **Registernummer**: for a registered association
     the Vereinsregister, for example "Amtsgericht Augsburg" and "VR 1234".
     Both fields belong together.
   - **Umsatzsteuer-ID**: only if the club has one.
   - **Inhaltlich verantwortlich** and **Anschrift der verantwortlichen
     Person**: for editorial content such as campaign pages and news
     (§ 18 (2) MStV). Both fields belong together.
4. Choose **Als Entwurf speichern**. The whole draft with all parts is saved.

## Fill in the privacy policy

1. In the draft, switch to the **Datenschutzerklärung** part.
2. In the first draft, **Datenschutzerklärung** and **Datenschutzhinweis für
   Mitglieder** contain templates. They describe only what LeonAid itself does.
   The club must complete or delete everything in double square brackets
   `[[ … ]]`, for example legal bases, service providers and the competent
   supervisory authority.
3. The **Datenschutzhinweis für Mitglieder** contains the section "Speicherung
   auf deinem Gerät": which data the acquisition app keeps on the device for
   offline capture (own sponsors with contact name, phone number and e-mail
   address, and entries not sent yet), that they are encrypted, that unsent
   entries expire after 14 days and that signing out or another person signing
   in deletes everything. Review it like the rest of the text.
4. Format: separate paragraphs with an empty line. `## ` at the start of a line
   starts a heading, `- ` a list item.
5. Choose **Als Entwurf speichern**.

The `/datenschutz` page also shows the controller and the privacy contact, the
order form's privacy notice with its legal basis (section "Bestellungen über
Aktionsseiten") and the members' notice (section "Für Mitglieder"). The short
notice on the order form stays and links to the full page.

## Approve and activate

1. A second person with system administration opens **Rechtliches**, reviews
   the changes, enters a **Nachweis-ID der Freigabe** and chooses **Entwurf
   freigeben**.
2. Then one of the two chooses **Version … aktivieren** and confirms with
   **Jetzt aktivieren**.
3. Within a minute, `/impressum` and `/datenschutz` show the new version.

## If the version cannot be activated

In production, the draft lists what is missing under **Noch nicht
aktivierbar**:

- **Im Impressum fehlen die vertretungsberechtigten Personen** or **fehlt die
  Telefonnummer**: complete the **Impressum** part.
- **Im Impressum fehlt der Eintrag im Vereinsregister**: the carrier's name
  contains "e. V.". Enter the register court and number.
- **Die Datenschutzerklärung fehlt** or **Der Datenschutzhinweis für
  Mitglieder fehlt**: enter the text in the **Datenschutzerklärung** part.
- **Ein Text enthält noch offene Vorlagen-Platzhalter**: complete or delete
  every `[[ … ]]`.

Edit the draft, save it and have it approved again.
