# SURV-100 — Document, mail and settlement regressions

**100.3h / 100.S2g are accepted for these six existing suites.** Each original
command exited zero against actual services. The harness changes isolate owned
resources; their original sequence from the first build through the final
business assertion is byte-identical to the preceding committed version.

| Suite               | Actual successful verification                                                                                                                                                                                 |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Typst               | Three database snapshots, four invoices rendered twice byte-identically, four PDFs/six pages opened by PDF parsers; pinned Typst 0.13.1.                                                                       |
| Storage             | RustFS and SeaweedFS object/version/signature/privacy/immutability/deletion checks; actual RustFS stop, pending retry and recovered byte-identical authorized PDF download.                                    |
| Documents           | Original API/database/document assertions and two Chromium journeys (9.8 seconds).                                                                                                                             |
| Mail relay          | Plain SMTP, STARTTLS, implicit TLS, authentication/certificate failures, delivery identities, provider limits, timeout and exactly-once retry.                                                                 |
| Invoice delivery    | Actual SMTP outage, visible retry in one Chromium journey (6.9 seconds), one recovered MIME message with unchanged PDF, then separately requested resend with a second Message-ID and no new document version. |
| Invoice settlements | Original role/full-payment contract, two Chromium journeys (1.0 minute), and subsequent database verification of payment, cancellation, audit, replay and unchanged Typst PDF.                                 |

[Commands, project identities, elapsed times and harness hashes](assets/SURV-100-document-mail-regressions.json)
identify the six accepted runs. All use a checkout/PID project, reserve unique
networks before startup, publish no host ports and remove only owned resources.
Independent post-command inventories confirmed zero owned containers, volumes
and networks for every project. Only one owned full stack ran at a time.

The delivered guard inventory adds these six harnesses, bringing its total to
31 harnesses / 124 occupied-container, occupied-volume, occupied-network and
unreadable-inventory rejection cases. These are a subset of the passing expanded
40-harness / 160-case preparation run. That refusal proof complements, rather
than replaces, the actual service runs above. Shell syntax and unchanged-business
sequence checks passed for all six scripts.

An earlier mail-relay service run passed its assertions but its outer collector
rejected the `pilot020` project prefix. It is not used for acceptance. The fresh
accepted mail-relay run recorded its terminal exit before independently checking
cleanup. Slow Twenty provisioning in the invoice runs ultimately completed;
no timeout or temporary lack of log output was treated as a passing result.

This brings the accepted isolated legacy regressions to **30 of 42**. The
remaining twelve, complete repeated Survey gate, final CI, capability audit and
independent host-loss recovery remain open. Screenshot checks do not establish a
new visual or accessibility audit. No CI security disposition is part of this
change.
