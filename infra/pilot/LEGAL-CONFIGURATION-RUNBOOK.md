# Configure organization and legal settings

As of: 28 July 2026

This runbook describes the technical maintenance of the installation-wide
basis for the legal entity, invoicing and privacy. It does not replace legal
or tax advice. Real evidence documents stay in the private evidence store;
LeonAid stores only their neutral evidence ID.

## Functional scope

The admin page **Rechtliches** (legal) at `/admin/legal` shows the basis in
six parts (Träger & Anschrift, Zahlung & Nummernkreis, Steuern, Datenschutz,
Aufbewahrungsfristen, E-Rechnung), each at `/admin/legal/<part>`. Together
they contain:

1. legal entity and invoice issuer data, bank details, tax case,
   invoice number format and payment term;
2. legal basis, notice text, text version, privacy contact and
   retention periods;
3. the e-invoicing decision and the related evidence IDs.

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
`golden` or `review-required`.

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
