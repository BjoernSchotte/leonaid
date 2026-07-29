# Typst invoice layout references v1

These PNG files are approved renders of the pinned `invoice-v2` template with
Typst 0.13.1 and PyMuPDF 1.26.3 at 144 dpi.

- `KT26-0001-page-1.png` proves the normal one-page invoice.
- `KT26-LAYOUT-0001-page-{1,2,3}.png` proves long recipient data, many line
  items, repeated table headers, page breaks and the closing totals section.

`./leonaid test-typst` always renders new candidates from real Core PostgreSQL
snapshots and compares their decoded RGB pixels against these files. To inspect
a deliberate template change before updating the references, run the same command with
`LEONAID_TYPST_APPROVAL_CANDIDATE=1`; this never updates the references.
