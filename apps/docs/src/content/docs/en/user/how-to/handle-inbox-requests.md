---
title: Handle inbox requests
description: Read public contact requests, assign them, clarify the CRM contact, link tasks and file versions, and close them.
docId: DOC-P045
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2ffe04e8c92f8eb60033985eb35aa89e75e36b92
reviewer: Björn Schotte
---

**Role:** system administrators see every request. Campaign administrators
see the requests of their campaign. Assigned members see the requests
assigned to them. Open **Eingänge** (inbox) in the back office
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

1. Open a request from **Alle Eingänge**. Filter by status if needed: **Neu**,
   **In Bearbeitung** or **Abgeschlossen**.
2. Under **Bearbeitung**, set the status and the **Zuständigkeit**
   (responsibility). Then select **Bearbeitung speichern**.
3. Under **Interne Notizen**, write a note and select **Notiz speichern**. Only
   people who can open the request see the notes.
4. To close a request, choose **Abgeschlossen**, write an **Abschlussnotiz**
   and save. You can reopen a closed request later.

If someone else saved the request in the meantime, LeonAid refuses your save
and keeps your draft. Load the current state on purpose before you save
again.

## Clarify the CRM contact

After a request arrives, a background job creates the submitter as a person in
Twenty (the CRM) or links an existing person. The status **Kontakt
zugeordnet** confirms the link. LeonAid stores the consent for this person
only after the link is confirmed.

If the status is **Kontaktzuordnung benötigt Klärung** (needs clarification):

1. Under **Bestehenden Kontakt suchen**, adjust the names and select **In
   Twenty suchen**.
2. Choose the right person under **Kontakt auswählen**.
3. Select **Kontaktzuordnung bestätigen**. LeonAid does not overwrite the data
   of the existing person.

## Link tasks and file versions

- Under **Aufgaben**, select **Aufgabe verknüpfen** and pick a task under
  **Bestehende Aufgabe auswählen**. You can pick tasks from lists you may edit.
  The request shows the current task status.
- Under **Materialien**, select **Material verknüpfen**, pick a material and
  select **Dateiversion einfügen**. The link stays on exactly that version.

A link does not grant access. People who cannot open the task or material see
it as unavailable.

## Deletion requests

When a submitter asks for deletion, a system administrator runs the privacy
workflow with the submitter's e-mail address under **Datenschutz** (privacy)
in the back office. The workflow removes the name, contact data and message from the request. It
keeps the handling history and revokes the stored consent. Delete the Twenty
person in the manual CRM step of the same workflow.
