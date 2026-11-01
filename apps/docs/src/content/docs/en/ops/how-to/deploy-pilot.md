---
title: Deploy a pilot installation
description: Deploy a manifest-bound staging or production installation without building on the target host.
docId: DOC-P022
audience: [ops]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 86b4e396de4569cbc7dbd03cdb2153a8698bb0d1
reviewer: Björn Schotte
---

Define separate domains, Compose projects, volumes, buckets, SMTP credentials,
Restic repositories, and secrets for staging and production. A further
organisation gets a further installation.

1. Copy `infra/pilot/production.env.example` outside the repository. The
   completed file belongs to the operator account and has mode `0600`.
2. Copy the lines of `release-images.env` from the approved GitHub release
   (see [Release a version](/en/ops/how-to/release-a-version/)): version,
   full `LEONAID_RELEASE_COMMIT` and images with tag and digest. Add an
   external backup target.
3. Render and inspect the effective configuration with `docker compose ...
config --format json`, using `infra/compose/compose.yml` and
   `infra/pilot/compose.yml`.
4. Run `./leonaid pilot-doctor --env-file ENV --backup-manifest MANIFEST
--gate pilot-deploy`. Exit 0 means technically ready, 1 means a blocker, 2
   means open decisions, and 3 means a STOP decision.
5. Deploy only an approved release manifest with `./leonaid pilot-deploy
--env-file ENV --backup-manifest BACKUP --release-manifest RELEASE`.

The target host does not build and exposes only Caddy on ports 80/443.
Production accepts the same manifest SHA only after staging verification. A
real deployment stays blocked while DNS, trusted TLS, mail, operator details,
recovery target, or business decisions remain open.
