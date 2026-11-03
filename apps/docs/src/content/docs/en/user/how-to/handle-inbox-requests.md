---
title: Handle inbox requests
description: Read public contact requests, assign them, clarify the CRM contact, link tasks and file versions, and close them.
docId: DOC-P045
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 0fb14dea5053c12fc1ff6e83757f9b458cf2317a
reviewer: Björn Schotte
---

**Role:** system administrators see every request. Campaign administrators
see the requests of their campaign. Assigned members see the requests
assigned to them. Open **Eingang** (inbox) in the back office
(`/admin/inbox`) or in the app (`/app/inbox`). The module needs the task and
material modules. If your installation switched the module off, the entry
and the public form are missing.

## Where requests come from

The public home page and every published campaign page show the form
**Kontakt aufnehmen** (get in touch). Archived campaigns show no form.

- The form asks for first name, last name, subject, message, and an e-mail
  address or phone number.
- Above the form, a privacy notice states the purpose, the storage in LeonAid
  and in the club CRM, and how to request deletion.
- The submitter must tick the consent checkbox. Without it, the form does not
  send.
- After sending, the submitter gets a reference number. No e-mail is sent.

Five requests per address in ten minutes are accepted. More are rejected
until the time window ends.

## Work on a request

1. Open **Eingang** (inbox). The view **Offen** (open) shows new requests and
   requests in progress, grouped by status. Further views are **Mir
   zugewiesen** (assigned to me), **Kontakt klären** (clarify contact) and
   **Alle** (all). Use **Filter** (key F) to filter by status, contact,
   responsibility or campaign.
2. Select a request, or move to it with J and K and press Enter. The request
   opens next to the list, on a phone as a sheet. Esc closes it again.
3. Change **Status** (key S) and **Zuständigkeit** (responsibility, key A) at
   the top. Only the case management, that is system and campaign
   administrators, changes the responsibility. Press X to select several
   requests and change them together.
4. **Übernehmen** (take over) sets a new request to **In Bearbeitung**. If
   nobody is responsible yet, you become responsible.
5. Under **Interne Notizen** (internal notes), write a note and select
   **Hinzufügen** (add). Only people who can open the request see the notes.
6. To close a request, select **Abschließen …** (close) or the status
   **Abgeschlossen**. The dialog **Anfrage abschließen** asks for an
   **Abschlussnotiz** (closing note) of at least 10 characters.
   **Abbrechen** (cancel) changes nothing. To reopen a closed request, choose
   another status.

If someone else changed the request in the meantime, LeonAid refuses your
change and loads the current state. Your closing note stays in the dialog.

## Clarify the CRM contact

After a request arrives, a background job creates the submitter as a person in
Twenty (the CRM) or links an existing person. The status **Kontakt
zugeordnet** confirms the link. LeonAid stores the consent for this person
only after the link is confirmed. The view **Kontakt klären** lists every
request whose contact is still open.

If **Kontakt in Twenty** shows **Kontaktzuordnung benötigt Klärung** (needs
clarification) or **Kontaktzuordnung fehlgeschlagen** (failed):

1. Adjust first and last name and select **In Twenty suchen** (search in
   Twenty).
2. Choose the right person among the hits.
3. Give a reason under **Begründung der Zuordnung** and select **Zuordnung
   bestätigen** (confirm). LeonAid does not overwrite the data of the existing
   person.

## Link tasks and file versions

- Under **Verknüpft** (linked), select **Aufgabe verknüpfen** and pick a task
  under **Bestehende Aufgabe auswählen**. You can pick tasks from lists you
  may edit. The request shows the current task status.
- Select **Material verknüpfen**, pick a material and select **Dateiversion
  einfügen**. The link stays on exactly that version. A click on the file
  downloads that version.

A link does not grant access. People who cannot open the task or material see
it as unavailable.

## Deletion requests

When a submitter asks for deletion, a system administrator runs the privacy
workflow with the submitter's e-mail address under **Datenschutz** (privacy)
in the back office. The workflow removes the name, contact data and message from the request. It
keeps the handling history and revokes the stored consent. Delete the Twenty
person in the manual CRM step of the same workflow.
