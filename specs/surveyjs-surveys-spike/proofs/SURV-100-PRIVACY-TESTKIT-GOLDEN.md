# SURV-100 — Privacy, testkit and Golden Journey regressions

All three complete existing regressions pass against real isolated services,
with independently verified cleanup. This accepts **100.3k / 100.S2j**, the
three named suites within 100.A3. Other spike acceptance gates remain open.

| Operator command | Exit | Duration | Browser coverage |
| --- | --- | --- | --- |
| `sh tools/privacy/test.sh "$PWD"` | 0 | 1615.315 s | One Chromium journey, 5.3 s |
| `sh tools/testkit/test.sh "$PWD"` | 0 | 759.799 s | One Chromium journey, 2.2 s |
| `sh tools/golden_journey/test.sh "$PWD"` | 0 | 1379.483 s | Nine tests: three browsers in three rounds |

The [command evidence](assets/SURV-100-privacy-testkit-golden.json) records source
checkpoints and exact tested harness hashes. Privacy and testkit were recorded
at `86bf028d9a6698c49a0c503148a44e1486035f6f`; Golden Journey started at
`61b8a5ce9c22b746421f4077d78e68168cf9c415`. Isolation changes were present
as working-tree overlays, identified by those hashes. These are scoped runs,
not a claim that the complete final revision has passed every CI gate.

## Privacy

The real administrative browser performs subject lookup, JSON export, contact
suppression and operative anonymization. API/database checks enforce role
boundaries and fresh login, verify withdrawn consent and acquisition/marketing
suppression, reject contact attempts through the direct API, and check that
operative order snapshots no longer contain the original subject details.
The erasure and audit records exclude the raw subject email.

Existing invoice data and generated PDF hashes remain unchanged according to
the fixture's configured retention rules. The
[mobile result](assets/SURV-100-privacy-after-erasure-mobile.png) was visually
inspected: it reports two operative orders anonymized and one invoice/document
retained. This is the existing privacy regression, not an independent-host
survey recovery proof or a legal assessment of retention settings.

## Testkit

Actual API, Twenty, SQL and browser results agree on the fixture sponsor ID and
name. The exercise obtains a Magic-Link persona session, verifies SMTP/Mailpit
delivery, writes and reads a RustFS object by hash, and deletes that temporary
object. The [browser screenshot](assets/SURV-100-testkit-ui.png) was inspected:
Anna's sponsor list contains the expected Musterwerk entry. Retained API/UI
JSON artifacts were checked against one another.

## Golden Journey and deterministic reset

The full existing persona journey runs in Chromium, Firefox and WebKit:
two consecutive business rounds, then a complete owned-stack reset and a
repetition of the first round. Browser durations are **40.8 s**, **37.2 s** and
**45.9 s**. The [second-round Firefox screenshot](assets/SURV-100-golden-firefox-admin.png)
was visually inspected. The earlier second-round Firefox activity-save failure
did not recur in this complete run; this result does not establish its cause.

The server-side verifier checks real users/memberships, assignments, activities,
internal/public orders, invoices, payments, deliveries and absence of duplicate
outbox records. Stored PDFs match their database hash/size; browser downloads
are byte-identical and email attachments match the stored PDF hashes.
The original and post-reset normalized summaries are byte-identical. That
cross-round comparison retains counts, company names, invoice numbers and PDF
sizes; it does not compare PDF hashes across separately generated rounds.

## Preserved assertions and resource ownership

The privacy and testkit business bodies are byte-identical to their committed
pre-isolation versions. Golden Journey retains its original round commands,
browser assertions, complete round sequence and final normalized comparison.
Its browser artifact mount/output changes keep failure traces outside the
temporary directory that the harness removes.

Each run rejects occupied project identities before mutation, uses a unique
checksum/PID project, reserves unused networks and publishes no host ports.
Golden Journey tears down only its owned stack and reserves networks again
before reseeding. Cleanup failures propagate, and independent checks confirm
zero owned containers, volumes and networks for all three projects. Shell
syntax checks pass. No screenshot baseline, timeout or assertion was relaxed.
