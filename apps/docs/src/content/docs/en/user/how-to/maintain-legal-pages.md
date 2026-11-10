---
title: Maintain the Impressum and the privacy policy
description: Create, approve and activate the § 5 DDG details and the texts of the /datenschutz page as a draft.
docId: DOC-P048
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 5e94339473f2439e5532a5408069a974ca7f5ca0
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
   appear in the Impressum. Choose the **Rechtsform** (legal form), for example
   "Eingetragener Verein (e. V.)" or "Nicht eingetragener Verein". It decides
   whether a register entry belongs in the Impressum; LeonAid does not read it
   from the name.
3. Switch to the **Impressum** part and enter:
   - **Vertretungsberechtigte**: who represents the club, with their function,
     for example the board under § 26 BGB. Required.
   - **Telefon**: the second fast contact channel next to the e-mail address.
     Required.
   - **Registergericht** and **Registernummer**: the register entry the chosen
     legal form requires, for example "Amtsgericht Augsburg" and "VR 1234" for a
     registered association, "HRB 5678" for a GmbH or gGmbH, "GnR 12" for a
     cooperative. Both fields belong together. The Impressum names the
     register from the number's prefix.
   - **Umsatzsteuer-ID**: if the club has one. If **Steuerkennung** holds a
     VAT ID, the field is required.
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
   offline capture (a short form of the own sign-in with name, campaigns and
   roles, own sponsors with contact name, phone number and e-mail address,
   and entries not sent yet, for orders with invoice and delivery address),
   that they stay on this device only and are encrypted, that unsent entries
   expire after 14 days and that signing out in either app or another person
   signing in deletes everything. It describes the acquisition app's offline
   capture. Keep it only when offline capture is active; otherwise delete the
   whole section. The template marks this with a `[[ … ]]` note that blocks
   activation until you remove it. The system administration switches on the
   feature flag **Offline-Erfassung in der Akquise-App** only once a notice
   with this section is active. Claude Code proposed the text; like every
   version it needs the four-eyes approval (review by Björn Schotte open).
   The notice also contains the section "Benachrichtigungen auf deinem
   Gerät": that LeonAid stores, per device, the address at the notification
   service of the browser or operating system (Google, Apple, Mozilla or
   Microsoft) and two keys, that the notifications
   are encrypted and contain no names, addresses or amounts, that consent is
   the legal basis, and that switching off, signing out or an invalid
   address deletes it. Keep it only when notifications are active; it too
   carries a `[[ … ]]` note. The system administration switches on the
   feature flag **Benachrichtigungen in der Akquise-App** only once a notice
   with this section is active. Claude Code proposed this text as well (legal
   review open).
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
- **Die Rechtsform des Trägers ist nicht gewählt**: choose it in **Träger &
  Anschrift**. Versions from before the update have it only if the name
  contained "e. V.".
- **Im Impressum fehlt der Registereintrag**: the chosen legal form has a
  register (e. V., GmbH, gGmbH, eG). Enter the register court and number. An
  unregistered association, a foundation and "Sonstige" need none.
- **Die Steuerkennung ist eine Umsatzsteuer-ID; sie gehört auch ins
  Impressum**: enter it under **Umsatzsteuer-ID**.
- **Die Datenschutzerklärung fehlt** or **Der Datenschutzhinweis für
  Mitglieder fehlt**: enter the text in the **Datenschutzerklärung** part.
- **Ein Text enthält noch offene Vorlagen-Platzhalter**: complete or delete
  every `[[ … ]]`.

Edit the draft, save it and have it approved again.

## After an update

When new mandatory details are added, the active version can be incomplete
afterwards. **Rechtliches** then shows **Die aktive Version … ist
unvollständig** at the top with the missing points. Create a new draft, have
it approved and activate it. Fields that an older open admin page does not
know are taken over from the previous version when you save.
