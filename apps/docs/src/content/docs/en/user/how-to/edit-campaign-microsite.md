---
title: Edit a campaign microsite
description: Change the text and images of your campaign's public microsite in the CMS editor and publish the changes.
docId: DOC-P042
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

You need the Charity-Admin role for the campaign. The microsite editor is part
of the optional campaign site. Its interface uses English labels; this guide
quotes them unchanged. If the installation runs without the campaign site
(`LEONAID_CMS_ENABLED=false`), LeonAid shows neither **Microsite bearbeiten**
nor the navigation entry "Kampagnenseiten".

1. In LeonAid, open the campaign and select **Microsite bearbeiten**. The
   editor opens with the current draft of the page.
2. Change the text fields. The editor saves a draft automatically a few
   seconds after you stop typing and then shows **Saved**. **Save** stores a
   draft at once. Visitors do not see a draft.
3. To add or change an image, select **Select image** or **Replace** in the
   image field. The dialog shows only the images of this campaign. Upload a
   PNG, JPEG or WebP file with **Upload files**; the upload is selected
   automatically. Confirm with **Select** or **Replace**. **Remove** clears
   the field.
4. To publish, select **Publish now** (first publication) or **Publish
   changes**. Confirm the same button in the dialog. The page is visible at
   once; **Live View** opens it at the club's public
   address, also when the editor runs on the admin host. While the action is
   active in its publication period, the public home page also lists it under
   **Aktuelle Aktionen**.
5. **Discard changes** in the **Publish** panel drops the draft and returns
   to the published version.
6. Select **Zurück zu LeonAid** to return to the LeonAid administration.

You can keep typing while the editor saves or publishes; your input is kept
and saved with the next automatic save. If you leave the page with unsaved
input, the browser asks before it discards it.

LeonAid owns the address of the page, the campaign it belongs to and its
publication period. Changes to the slug, the publication date, a schedule or
bylines are refused, and the editor shows an error message. Publishing
also fails while the campaign is outside its publication period in LeonAid.
