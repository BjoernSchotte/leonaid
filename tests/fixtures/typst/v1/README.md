# Typst layout references v1

These PNG files are approved renders of the pinned templates `invoice-v2`,
`invoice-cancellation-v1` and `donation-pledge-v1` with Typst 0.13.1 and
PyMuPDF 1.26.3 at 144 dpi.

Invoices (`invoice-v2`):

- `KT26-0001-page-1.png`, `KT26-0002-page-1.png` and `KT26-0003-page-1.png`
  prove the normal one-page invoice for the three golden invoices.
- `KT26-LAYOUT-0001-page-{1,2,3}.png` proves long recipient data, many line
  items, repeated table headers, page breaks and the closing totals section.

Cancellation invoices (`invoice-cancellation-v1`), from the snapshots in
`tests/fixtures/golden/v1/cancellations`:

- `KT26-0004-page-1.png` cancels the unpaid invoice KT26-0003: negative
  amounts, the reference to the invoice, "kein Betrag mehr zu zahlen".
- `KT26-0005-page-1.png` cancels the paid invoice KT26-0002: the amount
  received and "Die Erstattung erfolgt gesondert.".
- `KT26-LAYOUT-0002-page-{1,2,3}.png` is the multi-page case.

Donation pledges (`donation-pledge-v1`), from the snapshots in
`tests/fixtures/golden/v1/donations`:

- `SP26-0001-page-1.png` is the usual pledge: one page, the receiving body
  with its bank details, the number as payment reference, no tax line and no
  invoice wording.
- `SP26-LAYOUT-0001-page-{1,2}.png` carries the longest values (names, a
  million euro, a pledge text of nearly 2,000 characters) and breaks the page.

`./leonaid test-typst` always renders new candidates (invoices from real Core
PostgreSQL snapshots, cancellation invoices and donation pledges from the
versioned snapshots) and
compares the decoded RGB pixels of every page against these files. To inspect
a deliberate template change before updating the references, run the same
command with `LEONAID_TYPST_APPROVAL_CANDIDATE=1`; this never updates the
references. The candidates are written to `.artifacts/poc091`.
