# Krapfentaxi Golden Journey

`./leonaid test-golden-journey` proves the complete PoC path with real
services and without mocks or direct business-level database writes.

## Prerequisites

```sh
./leonaid bootstrap
```

OrbStack or Docker must be running. The test uses its own Compose project, its
own volumes and the ports `18142` and `18502`. It does not change the normal
local development stack.

## Flow

The test:

1. builds API, worker, web, PWA and Public Web from the current state;
2. starts PostgreSQL, Twenty, RustFS and Mailpit on empty volumes;
3. provisions the restricted Twenty schema and Golden Dataset v1;
4. runs the complete journey in Chromium, Firefox and WebKit, one after the
   other;
5. checks the business totals and real artifacts after the first round;
6. runs a second round without a reset and rules out technical duplicates;
7. deletes all test volumes, starts again fully empty and repeats the first
   round in all three browsers;
8. compares the normalized business results byte for byte.

Every fresh Twenty instance gets its own short-lived token file. This way no
API key from the previous, already deleted workspace can be reused.

## Determinism and proof artifacts

Within each run, the browser download, the RustFS object and the mail MIME
attachment must have exactly the same SHA-256. The complete proof log contains
these per-run hashes.

When two golden resets run one after the other are compared, the real issue
timestamps and the PDF hashes derived from them are normalized. The comparison
covers business totals, companies, invoice numbers and PDF sizes. This keeps
business deviations visible without faking an identical real-time timestamp.

Successful runs store the private, unversioned evidence under
`.local/pilot/evidence/golden-journey/`:

- complete and normalized JSON logs;
- admin and acquirer screenshots of all browsers and rounds;
- the Typst PDFs downloaded in the browser;
- screenshots of the visible in-app browser smoke test.

The directories have mode `0700`, files mode `0600`. Screenshots, PDFs and raw
data are never uploaded as public GitHub artifacts. On failure, sanitized
service diagnostics are also written under `.artifacts/failures/poc122/`. As
soon as a screenshot, PDF, trace or other artifact that cannot be safely
checked reaches the public boundary, the CI wrapper discards the whole public
artifact set (fail-closed).
