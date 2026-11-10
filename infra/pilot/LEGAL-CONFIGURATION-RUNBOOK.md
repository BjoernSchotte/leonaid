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

The section „Benachrichtigungen auf deinem Gerät" of the members' notice
describes push notifications of the acquisition app: the address at the push
service of the browser vendor (Google, Apple, Mozilla or Microsoft) and the
two keys that LeonAid stores per device, and the consent as legal basis.
LeonAid stores nothing about the browser itself. LEGAL REVIEW PENDING: the wording is a proposal
(`specs/mails-documents-donations-push/PLAN.md`, Appendix A.4, item P4). The
feature flag `pwa.push` (System → Feature-Flags, „Benachrichtigungen in der
Akquise-App") may be switched on only once the **active** version of the
legal configuration carries this section in the members' notice, as for the
offline capture (`pwa.offline_queue`). LeonAid does not enforce this order;
the system admin who switches the flag checks it. Without
`LEONAID_VAPID_PRIVATE_KEY` the page says „noch nicht eingerichtet" whatever
the flag says.

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

## Donations: receiving body and wording (before a real club takes donations)

**LEGAL REVIEW PENDING – Freigabe durch Björn erforderlich (P3).** The part
"Spenden" of the legal configuration names the body that receives donations
(ADR-0016). The tax points behind it rest on the implementation's knowledge,
not on a looked-up source. Before a real club records donations, its tax
adviser should confirm:

- the receiving body, its notice (kind, date, assessment period) and the
  purposes, word for word as in the notice;
- that the donation account belongs to the receiving body;
- the two wording blocks. The UI offers them as proposals ("Vorschlag
  einsetzen", `packages/features/src/system-admin/legal-templates.ts`), from
  `specs/mails-documents-donations-push/PLAN.md` Appendix A.3.

Text of the donation pledge (`DONATION_PLEDGE_TEXT_TEMPLATE`):

> Ihre Spende ist freiwillig. Sie erhalten dafür keine Gegenleistung. Dieses
> Schreiben ist keine Rechnung. Nach Eingang Ihrer Zahlung senden wir Ihnen
> eine Zuwendungsbestätigung für Ihre Steuererklärung.

The pledge PDF (`donation-pledge-v1.typ`, `donation_pledge_renderer.py`) adds
fixed sentences around it:

> Vielen Dank für Ihre Spende von 50,00 € für die Aktion „Krapfentaxi 2026“
> (Lions Club Musterstadt).

> Bitte überweisen Sie den Betrag auf das folgende Konto und geben Sie als
> Verwendungszweck die Nummer dieser Spendenzusage an.

The cover mail (`application/donations.py`) repeats amount, number and
"Dieses Schreiben ist keine Rechnung." and is signed with the name of the
receiving body.

The liability note (`DONATION_RECEIPT_LIABILITY_TEMPLATE`) is printed at the
end of every donation receipt. Compare it with the current official sample of
the Federal Ministry of Finance before use.

The donation receipt (`donation-receipt-v1.typ`,
`donation_receipt_renderer.py`, `domain/donation_receipts.py`) follows the
official sample for money donations. Its fixed texts, for the tax adviser:

> **Bestätigung über Geldzuwendungen**
> im Sinne des § 10b des Einkommensteuergesetzes an eine der in § 5 Abs. 1
> Nr. 9 des Körperschaftsteuergesetzes bezeichneten Körperschaften,
> Personenvereinigungen oder Vermögensmassen

> Es handelt sich nicht um den Verzicht auf Erstattung von Aufwendungen.

Notice paragraph with a Freistellungsbescheid (with the Anlage zum
Körperschaftsteuerbescheid the words "der Anlage zum
Körperschaftsteuerbescheid" take the place of "dem Freistellungsbescheid"):

> Wir sind wegen {Zwecke} nach dem Freistellungsbescheid des Finanzamtes
> {Ort}, StNr. {Steuernummer}, vom {Datum} für den letzten
> Veranlagungszeitraum {von} bis {bis} nach § 5 Abs. 1 Nr. 9 des
> Körperschaftsteuergesetzes von der Körperschaftsteuer und nach § 3 Nr. 6
> des Gewerbesteuergesetzes von der Gewerbesteuer befreit.

Notice paragraph after § 60a AO. The last sentence differs from Appendix A.3:
the purposes are quoted as entered, because their grammar cannot be derived:

> Die Einhaltung der satzungsmäßigen Voraussetzungen nach den §§ 51, 59, 60
> und 61 AO wurde vom Finanzamt {Ort}, StNr. {Steuernummer}, mit Bescheid vom
> {Datum} nach § 60a AO gesondert festgestellt. Wir fördern nach unserer
> Satzung: {Zwecke}.

> Es wird bestätigt, dass die Zuwendung nur zur {Zwecke} verwendet wird.

This sentence reads well only when the purposes start with a noun such as
"Förderung der …". Enter them that way.

Under the signatory with the machine procedure:

> Diese Zuwendungsbestätigung wurde maschinell erstellt und trägt keine
> eigenhändige Unterschrift. Das Verfahren ist dem {Finanzamt} angezeigt
> (R 10b.1 Abs. 4 EStR).

Rules built in, to confirm: a receipt only for a paid donation and for the
amount that arrived; no receipt when the notice is older than five years
(Freistellungsbescheid, Anlage zum Körperschaftsteuerbescheid) or three years
(§ 60a AO); a receipt signed by hand is never mailed; declaring a receipt
void needs the original back or the donor's tax office informed.

Order forms with the extra donation show this sentence
(`apps/public/src/components/PublicOrder.astro`), with the name of the
receiving body:

> Ihre Spende ist freiwillig und ohne Gegenleistung. Empfänger ist
> {Körperschaft}. Sie erhalten dafür eine eigene Zahlungsbitte, getrennt von
> der Rechnung für Ihre Bestellung.

The order confirmation (`application/order_mails.py`) adds a paragraph:

> **Ihre Spende**
> Sie haben zusätzlich eine Spende von 50,00 € an {Körperschaft} zugesagt.
> Die Spende ist freiwillig, ohne Gegenleistung und nicht Teil Ihrer
> Bestellung oder der Rechnung. Die Spendenzusage SP26-0007 mit der
> Bankverbindung erhalten Sie in einer eigenen E-Mail.

**Privacy policy (P6).** When the receiving body is another legal entity
than the club, the donor's name, address, amount and day of payment go to
it. LeonAid does not add this to the privacy policy by itself. Before a real
club switches the extra donation on, add a section like this one to the
privacy policy text (part "Datenschutzerklärung" of the legal configuration)
and have it reviewed:

> **Spenden**
> Spenden Sie im Rahmen einer Aktion, ist Empfänger Ihrer Spende der
> {Körperschaft}. Wir übermitteln ihm dazu Ihren Namen, Ihre Anschrift, den
> Betrag und den Tag der Zahlung. Er stellt Ihnen die Zuwendungsbestätigung
> aus und bewahrt ein Doppel zehn Jahre auf (§ 50 Abs. 7 EStDV).
> Rechtsgrundlage ist die Erfüllung der Spendenvereinbarung mit Ihnen und die
> gesetzliche Aufbewahrungspflicht (Art. 6 Abs. 1 Buchst. b und c DSGVO).

The dev tenant carries a synthetic receiving body ("Förderverein Lions Club
Musterstadt e. V.") with the machine procedure; it is not a model for a real
club.

## Cancellation invoice: wording (before a real club relies on it)

**LEGAL REVIEW PENDING – Freigabe durch Björn erforderlich (P2).** Cancelling
an invoice issues a cancellation invoice ("Stornorechnung", ADR-0015). Its
texts are fixed in the template
`src/leonaid/adapters/typst/templates/invoice-cancellation-v1.typ`, in
`adapters/typst/invoice_cancellation_renderer.py` and in the cover mail
(`application/invoice_deliveries.py`). They are proposals from
`specs/mails-documents-donations-push/PLAN.md` Appendix A.2. The club's tax
adviser should read them once before a real club sends such a document.

Title and reference:

> **Stornorechnung KT26-0042**
> zur Rechnung KT26-0017 vom 28.11.2026

Introduction:

> Mit dieser Stornorechnung heben wir die Rechnung KT26-0017 vom 28.11.2026
> vollständig auf. Die Beträge der Rechnung werden mit umgekehrtem Vorzeichen
> ausgewiesen.

Closing line when nothing was received:

> Aus der Rechnung KT26-0017 ist kein Betrag mehr zu zahlen.

Closing line when payments were received:

> Auf die Rechnung KT26-0017 haben wir 72,00 € erhalten. Die Erstattung
> erfolgt gesondert.

Cover mail:

> Betreff: Stornorechnung KT26-0042 zur Rechnung KT26-0017 · Krapfentaxi 2026
>
> anbei erhalten Sie die Stornorechnung zu Ihrer Rechnung KT26-0017. Die
> Rechnung ist damit aufgehoben.

Notes for the review:

- The cancellation invoice takes the next number of the invoice number series
  (D-C1). Whether it shall carry a prefix of its own is open (P5).
- It repeats issuer, recipient, tax case and tax note of the invoice. The
  reason of the cancellation is internal and is not printed.
- A change of the wording is a new template version; documents already issued
  keep their PDF.
