# Configure organization and legal settings

As of: 7 November 2026

This runbook describes the technical maintenance of the installation-wide
basis for the legal entity, invoicing and privacy. It does not replace legal
or tax advice. Real evidence documents stay in the private evidence store;
LeonAid stores only their neutral evidence ID.

## Functional scope

The admin page **Rechtliches** (legal) at `/admin/legal` shows the basis in
eight parts (Träger & Anschrift, Impressum, Zahlung & Nummernkreis, Steuern,
Datenschutz, Datenschutzerklärung, Aufbewahrungsfristen, E-Rechnung), each at
`/admin/legal/<part>`. Together they contain:

1. legal entity and invoice issuer data, bank details, tax case,
   invoice number format and payment term;
2. the Impressum details under § 5 DDG (representatives, telephone, register
   entry, VAT ID) and the optional person responsible under § 18 (2) MStV;
3. legal basis, notice text, text version, privacy contact and
   retention periods;
4. the privacy policy and the members' privacy notice of `/datenschutz`;
5. the e-invoicing decision and the related evidence IDs.

The active version is published at `/impressum` and `/datenschutz` on every
host. Both pages and the public footer read it through
`GET /api/v1/public/legal-notice` and `GET /api/v1/public/privacy-policy`
(at most 60 s cache).

This installation-wide basis is not the same as the campaign-scoped invoice
profile. The invoice profile of a charity campaign remains the currently
active contract for the actual invoice generation. It may be confirmed with
real values only once the installation-wide basis is functionally active.
This way there is no second, uncontrolled source for invoice snapshots that
were already issued.

Operations data such as DNS, VPS, mail relay, backup, secret, monitoring or
incident owners do not belong in this form. They are kept in the deployment
configuration, the runbooks and the decision register, which contains no
personal data.

## Roles and approval

- Only global system admins may read or change the configuration.
- Every change creates a new immutable version.
- The author cannot approve their own version.
- A second system admin records a neutral approval evidence ID.
- Only then can the version be activated as binding.
- Writes require a fresh login.
- Parallel or stale changes are rejected through the expected revision.

Audit events contain version, revision and technical IDs, but no IBAN,
email address, postal address or legal texts.

## Safe procedure

1. The functionally responsible roles answer the questions from
   `specs/leonaid-pilot/DECISION-INTAKE.md` and store private evidence.
2. A system admin opens `/admin/legal`, chooses `Neuen Entwurf beginnen`
   (start a new draft) or `Entwurf bearbeiten` (edit draft), fills in every
   part and checks the values.
3. They choose `Als Entwurf speichern` (save as draft). The draft is not yet
   in effect. The author sees a lock note instead of the approval.
4. A second system admin compares the changes of each part (old value above
   the new value) with the private evidence, enters its evidence ID and
   chooses `Entwurf freigeben` (approve draft).
5. A system admin chooses `Version N aktivieren` (activate version N) and
   confirms it.
6. The responsible functional roles then check the real staging record, the
   public form, the privacy export and the erasure workflow.

An open e-invoicing decision blocks activation. The result `required` blocks
the ERP-light pilot completely, because XRechnung and ZUGFeRD are not added
to this scope silently.

In a production environment, LeonAid also blocks recognizable
golden/test/placeholder values such as `.invalid`, `.test`, `example.org`,
`golden` or `review-required` (also in the Impressum and privacy texts), and
it blocks a version when:

- the representatives or the telephone number are missing;
- no legal form is chosen (an explicit field in Träger & Anschrift; the
  migration sets "eingetragener Verein" only for names with "e. V.");
- the chosen legal form (e. V., GmbH, gGmbH, eG) requires a register entry
  and none is given;
- the invoice tax identifier is a VAT ID and the Impressum VAT ID is empty;
- the privacy policy or the members' privacy notice is missing;
- any text still contains a template placeholder `[[ … ]]`.

The templates are not legal advice. The device-storage section of the
members' notice describes the acquisition app's offline capture and carries a
placeholder until the club decides it applies.

## After an update

A version activated before new requirements can be incomplete afterwards
(for example after migration 0054 added the Impressum fields). The page
**Rechtliches** then shows the warning „Die aktive Version … ist
unvollständig" with the missing points. Create a new draft, have it approved
and activate it. A save from an admin page loaded before the update keeps the
previous version's values for fields that page does not send.

## Reproducible technical proof

```sh
./leonaid test-pilot-legal-config
```

The command starts an isolated real Compose stack with PostgreSQL, Twenty,
RustFS and Chromium. It checks roles, immutable versions, four-eyes
approval, activation locks, competing revisions, audit without personal data,
desktop/mobile use and accessibility. After the run, exactly the test
containers, networks and volumes are removed.

## Functional acceptance still required

Technical activation alone does not close PILOT-044. Before production
approval, the following are still required:

- real legal entity, tax, invoice and privacy values are confirmed;
- the public form and consent evidence use the active text version;
- export and erasure respect the activated retention periods and the
  Twenty/RustFS references;
- the responsible functional owner accepts a real staging record.

## After a privacy erasure: delete the party in Twenty

The erasure workflow removes the subject's parties from the sponsor search
and leaves a marker, but it does not delete them in Twenty (manual step,
`crmDeletion: pending_manual_review`). A new assignment for such a party
(sponsor capture or assignment by a manager) is a new, deliberate relation:
it brings the party back into the search with the name Twenty then holds. So
after an erasure, delete the party in Twenty before the next campaign assigns
it again.

## Delivery tours: privacy paragraphs (before the flag goes on)

**Entwurf – Freigabe durch Björn erforderlich.** The two paragraphs below are
drafts for legal review. Both must be approved and activated (four-eyes path
of this runbook) before the feature flag `delivery.tours` is switched on.

### Member privacy notice: map tiles

Draft text for `member_privacy_notice_text`:

> Für die Karte in „Meine Tour“ und in der Tourenplanung laden wir Kartenkacheln
> von OpenStreetMap (Standard: tile.openstreetmap.org). Dabei erfährt der
> Anbieter Ihre IP-Adresse und den angezeigten Kartenausschnitt. Adressen
> oder Namen werden nicht übertragen. Rechtsgrundlage ist Art. 6 Abs. 1 lit. f
> DSGVO (Darstellung der Lieferstopps). Mit einem selbst betriebenen
> Kartenserver entfällt diese Übermittlung.

### Customer privacy notice: geocoding

Draft text for the privacy notice shown at the public order form and in the
order confirmation:

> Zur Planung der Lieferung wandelt LeonAid Ihre Lieferadresse (Straße,
> Postleitzahl, Ort, Land) über den Dienst Nominatim in Koordinaten um.
> Namen, Kontaktdaten und Bestelldaten werden nicht übermittelt. Rechtsgrundlage
> ist Art. 6 Abs. 1 lit. b DSGVO (Durchführung der Bestellung). Die Koordinaten
> werden mit der Lieferadresse gespeichert und gelöscht.

Notes:

- With the default public Nominatim, sending the address is a transfer to a
  third party. With a self-hosted geocoder it is not a transfer, and the
  paragraph can be shortened.
- The driver note (`Hinweis für den Fahrer`) is covered by access and erasure
  like the delivery contact.
- Check the retention wording against the active retention periods.
