---
title: Set up domains for campaigns
description: Show a campaign under its own domain or subdomain, hand the domain to a follow-up campaign and remove domains again.
docId: DOC-P048
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 8f8176da
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** system admin. Domains cost money and concern the whole club, so
only the system administration manages them. Charity admins see the
addresses of their campaign but do not change them.

A campaign can run under its own domain (`krapfentaxi.org`) or a subdomain of
the club (`weihnachtsmarkt.example.org`). Administration stays on the admin
host. Each domain shows only the campaign pages of the campaigns bound to it.
The admin UI is German; this guide names its labels unchanged.

## Add a domain

1. Open **System** › **Domains**.
2. Enter only the name under **Domain**, without `https://` and without a
   path, and choose **Domain hinzufügen**. Capital letters and umlauts are
   allowed; LeonAid stores the spelling DNS uses.
3. Create the record that the domain card names at your registrar or DNS
   provider: a `CNAME` to the club's host for a subdomain, `A` and `AAAA` to
   this server's addresses for an own domain. Registrar forwarding products do
   not work.

The admin host, the public host and its extra names cannot be added, nor
names below the admin host.

## Bind a campaign

1. Choose **Aktion binden** on the domain card.
2. Pick the **Aktion**. **Pfad der Ausgabe** (the edition path) is optional;
   left empty, the edition gets the year of its publication start, for
   example `2025`.
3. Keep **Diese Ausgabe unter „/“ zeigen** on if the campaign should be the
   start page of the domain.
4. Confirm with **Binden**.

The domain only shows campaign pages from the CMS. If the campaign has no
published campaign page, the dialog warns you.

Every edition stays reachable at `https://<domain>/<path>/`. The start page
`/` shows the edition marked **aktuell auf /** while it runs. After the end,
`/` redirects to the archive page of the edition.

## Hand the domain to a follow-up campaign

For recurring campaigns such as Lions Open 2025 and 2026:

1. Choose **Domain an Folgeaktion übergeben**.
2. Pick the follow-up campaign and, if needed, its path.
3. Check the preview: the follow-up takes over `/` from its publication
   start. The previous edition stays reachable under its path; aliases and
   order confirmations already sent point there.
4. Confirm with **Übergeben**.

If both editions run at the same time, the previous one keeps taking orders
under its path.

## More settings

- **Pfad ändern** (change path): the old path then redirects permanently to
  the new one. It is listed under **Frühere Pfade**.
- **Als Weiterleitung nutzen** (use as redirect): a domain without editions,
  such as `www.krapfentaxi.org`, redirects as a whole to another domain. The
  path is kept.
- **Als Hauptadresse** (main address): if a campaign runs on two domains, the
  main address decides the link in search engines and mails.
- **Lösen** (unbind): the edition disappears from the domain; its path
  redirects to the campaign's next public address. If it is the only edition,
  `/` then shows an error page; the dialog asks you to confirm.

## Remove a domain

1. Choose **Domain entfernen**.
2. The preview shows each edition's new address, or "nicht mehr öffentlich
   erreichbar" (no longer public).
3. Confirm with **Entfernen**.

The domain is switched off and gets no certificate anymore. Old links to this
domain stop working; aliases and addresses on the public host stay. If another
domain still redirects here, remove or change that one first. You can add a
removed domain again later; it is then checked again.
