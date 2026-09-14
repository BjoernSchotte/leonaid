---
title: Install a local demo
description: Start and verify a fresh LeonAid checkout with the locked Docker toolchain.
docId: DOC-P021
audience: [ops]
diataxis: tutorial
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

You need Git, Docker with Compose v2, and at least 5 GiB of free space. Node,
Bun, Python, and databases do not need to be installed on the host.

1. Clone the repository and enter the checkout.
2. Run `./leonaid bootstrap`. It creates ignored `.env.local` values with local
   randomness and installs locked packages in Docker. It does not overwrite an
   existing file.
3. Run `./leonaid doctor` to check Docker, locks, secrets, and local dependencies.
4. Start the standard stack with `./leonaid dev` and wait for its health checks.
5. Open `https://localhost:8443`. The certificate comes from Caddy's local CA.
   `http://localhost:8080` is an additional diagnostic endpoint only.
6. Run `./leonaid test-handoff`. It proves the documented handoff path again
   from a fresh checkout.

The tutorial succeeds when `doctor` and `test-handoff` exit with zero and the
member UI responds over HTTPS. All test data is synthetic. Later,
`./leonaid test-env-stop` removes the reusable test environment without
deleting regular local development data.
