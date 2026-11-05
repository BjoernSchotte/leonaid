# Golden Dataset v1

All names, companies, addresses and email addresses are synthetic. Email
addresses use only the reserved test zone `leonaid.invalid`. The data does not
represent any real Lions Club or real sponsors.

## Personas

- **Simone System** sees all three actions and is later used only for
  system-wide administration.
- **Klara Kern** manages the active and the archived Krapfentaxi action.
- **Felix Fremd** manages only the other, not yet published test action. This
  makes negative action boundaries provable.
- **Anna Akquise**, **Bernd Binder** and **Carla Club** are active acquirers of
  the running action.
- **Finn Finanzen** holds the action-scoped finance role.
- **Gesa Gesperrt** has a membership but sees no action because her user status
  is blocked.

## Conflict and visibility cases

- Musterwerk is assigned only to Anna.
- Bäckerei Sonnenseite is assigned only to Bernd.
- Doppelkontakt is assigned to both Anna and Bernd and has two contact persons.
- Freie Firma is deliberately assigned to nobody.
- Sophie Sponsor is a person without a company, assigned to Carla.
- `Baeckerei  Sonnenseite K.G.` normalizes to an existing company; on entry,
  the existing assignment to Bernd must appear as a warning.
- Two people are called Max Mustermann. Company, email and postcode force a
  deliberate disambiguation.

## Krapfentaxi business values

The active offer contains 24 Krapfen per box at 36.00 EUR, a complete order
period and `box` as the allowed quantity unit. Six commitments from personal
acquisition, the public form and admin entry cover draft, review-ready,
received publicly and invoiced. Together they add up to 25 boxes, 600 Krapfen
and 900.00 EUR. With a manual action goal of 1,000.00 EUR, that is 90.00
percent.

The three invoices cover open, paid and cancelled. Each contains its own
address snapshot and refers to an invoiced commitment.

## Public Web

`/krapfentaxi` is the moving alias of the active action. The active action also
has the stable canonical path `/archive/krapfentaxi-2026`; the previous year is
reachable only under `/archive/krapfentaxi-2025`.

## Files and checks

- `manifest.json` links dataset and schema version.
- `schema.json` defines collections and enums.
- `dataset.json` contains input data only.
- `expected.json` contains counts, visibilities, match results,
  quantity/money calculations, feed views and public resolution.
- `outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx`
  is a real, visually checked workbook with instructions, an initial contact
  import and a controlled second state. It proves new, updated, ambiguous and
  rejected CRM input.
- `import/leonaid-crm-import.csv` contains the same initial state as a
  semicolon-separated UTF-8 file and proves the alternative parser path.
- `documents/*.typ` are the deterministic sources of the three synthetic golden
  invoices. `./leonaid seed` renders them with the pinned Typst image, stores
  the PDFs in RustFS and saves SHA-256 plus the invoice mapping.

Check:

```sh
docker run --rm -v "$PWD:/workspace:ro" \
  python:3.13.18-slim-trixie@sha256:d0a9e379c0c588befb0e427db17ca9731751d281f32c6cb1a90a1277b680bdad \
  /bin/sh /workspace/tools/golden/test.sh /workspace
```
