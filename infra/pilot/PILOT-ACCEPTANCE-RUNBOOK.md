# Pilot acceptance and readiness dossier

This runbook brings together technical evidence and explicit decisions for
`PILOT-053`. It does not itself grant any functional, legal or operational
approval.

## Assess the technical state

On the intended final commit:

```sh
./leonaid pilot-readiness --report .local/pilot/evidence/pilot-readiness.json
```

The report assesses, fail-closed:

- all 21 pilot tasks and their open criteria or dependencies;
- all 16 hard gates and their assigned tasks;
- every reserved proof link as `missing`, `partial` or `complete`;
- all public decision IDs due for `pilot-release`;
- branch, commit, clean working tree and being level with `origin/main`;
- a canonical SHA-256 checksum of the full sanitized report.

Exit `0` means technically `ready`, exit `2` `blocked`, exit `3` a
functional `stop` decision and exit `1` an invalid contract. Even exit `0`
replaces no signature and no explicit go-live decision.

The machine-readable report contains only public IDs, status values, proof
paths and commit SHAs. Private pilot evidence, URLs, credentials, names,
email addresses and functional payloads stay outside the report.

## Prepare the final record

The template
[`PILOT-ACCEPTANCE-TEMPLATE.md`](PILOT-ACCEPTANCE-TEMPLATE.md) is copied into
the private evidence store and filled in there. Only the empty template stays
in the repository.

Before acceptance, at least the following must be referenced:

1. final commit and release manifest;
2. image and dependency locks;
3. golden dataset version;
4. private evidence IDs without private URLs;
5. completed CI runs;
6. external restore evidence;
7. SHAs of sanitized screenshots and records;
8. applicable runbooks;
9. open P2/P3 items with owner and due date;
10. decision on the next milestone and the operations handover.

## Decision

Product ownership, operations and the required functional roles explicitly
confirm or stop the pilot. Permitted next milestones are:

- Krapfentaxi delivery;
- further pilot hardening;
- Lions Open discovery.

A successful pilot acceptance is not an automatic open-ended production
approval. Duration, user group, handover of responsibility, operations,
retention and renewed stop criteria are confirmed separately.
