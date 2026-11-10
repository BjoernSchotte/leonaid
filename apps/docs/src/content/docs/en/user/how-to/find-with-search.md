---
title: Find things with the search
description: Find campaigns, orders, invoices, sponsors and members through "Suchen und Befehle" and open them directly.
docId: DOC-P053
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 225fc66fd2f98b8127fea32a158acc6e51d39de1
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** every member with access to the back office. The search shows you
only what your roles let you open on the page it belongs to.

1. In the back office, select **Suchen und Befehle**, or press `Ctrl+K`
   (Mac: `⌘K`). Outside an input field, `/` opens the search too.
2. Type at least two characters. The results appear grouped by kind:
   **Charity-Aktionen**, **Bestellungen**, **Rechnungen**, **Sponsoren** and
   **Mitglieder**, followed by the results of the modules that are switched
   on.
3. Select a result with the arrow keys and `Enter`, or click it. LeonAid opens
   the page of the result and the record itself on that page.

## What the search finds

| Group            | Searched in                           | Who finds it                                                                                                                              |
| ---------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Charity-Aktionen | Name of the campaign                  | Charity admins of the campaign, system admins                                                                                             |
| Bestellungen     | Name of the buyer, order number       | Charity admins of the campaign, system admins                                                                                             |
| Rechnungen       | Invoice number, name of the recipient | Finance roles, charity admins of the campaign, system admins                                                                              |
| Sponsoren        | Name and city of the sponsor          | Charity admins and system admins: all assignments of the campaign. Acquirers: their own assignments, as long as they are not handed over. |
| Mitglieder       | Name, e-mail address                  | whoever may see the member list                                                                                                           |

The search ignores upper and lower case. Results that begin with your search
text come first.

## Sponsors

A sponsor appears once per assignment. If two acquirers look after the sponsor
in one campaign, a charity admin sees two results. Each result shows the name
of the sponsor, the campaign and, if it is maintained in the CRM, the city.

- **As a charity admin or system admin**, the result opens the
  **Sponsor-Pipeline** of the campaign (**Akquise** in the rail). The table
  jumps to the row of the assignment, the row is highlighted, and the detail
  opens: city, contact person, e-mail, phone, acquirer, status, next step and
  the history of the assignment. **Schließen** or `Esc` closes the detail;
  the row stays highlighted. You can also open the detail for any row by
  clicking the name of the sponsor.
- **As an acquirer**, the result opens the sponsor in the acquisition app
  under **Sponsoren**. This also applies if you are a charity admin in another
  campaign: your role in the campaign of the result decides.

For sponsors, LeonAid searches the name and the city only. The e-mail address,
phone number and street of a sponsor are stored only in the CRM, and the
search cannot find them.

### How current the sponsors are

- A sponsor that was just created or just assigned can be found at once.
- If someone changes the name or the city directly in the CRM, the search
  follows after about 15 minutes at the latest.
- If someone deletes a sponsor in the CRM, the sponsor leaves the search in
  the following night. Its assignments stay in the Sponsor-Pipeline and in
  the acquisition app, named **Im CRM nicht mehr vorhanden** and without
  contact data. A charity admin can still hand them over or close them.
- After a privacy erasure, the sponsor can no longer be found at once.

## If you find nothing

- **Too short:** the search starts at two characters.
- **Sponsor without an assignment:** the search knows only sponsors that are
  assigned to an acquirer in a campaign. A contact that exists only in the CRM
  does not appear.
- **Someone else's or a handed-over assignment:** as an acquirer you find only
  your own sponsors. After you hand a sponsor over, the new person in charge
  finds it.
- **Another campaign:** you find orders, invoices and sponsors only in
  campaigns in which you hold the matching role.
- **"Die Suche ist gerade nicht erreichbar":** try again. If only one part
  fails, the search names it and shows the other results.

More limits are listed under [Known limits](/en/known-limits/).
