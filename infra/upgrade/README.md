# Upgrade and rollback

Current bilingual task guide:
[Deutsch](../../apps/docs/src/content/docs/de/ops/how-to/upgrade-and-rollback.md) ·
[English](../../apps/docs/src/content/docs/en/ops/how-to/upgrade-and-rollback.md).
This file remains the detailed upgrade contract.

This runbook describes the fail-closed upgrade path for LeonAid Core, Twenty
and RustFS. It extends the
[`backup/restore runbook`](../backup/README.md). An upgrade without a fresh,
integrity-checked recovery point is not allowed.

## Mandatory preparation

1. Pin source and target images with tag and digest in
   `infra/locks/external-systems.lock` and `infra/locks/images.env`.
2. Read release notes and migrations and update the decision in
   `compatibility-matrix.json`.
3. Run `./leonaid check` on a clean checkout.
4. Run `./leonaid test-upgrade` against a golden-data clone.
5. Record the maintenance window, the responsible person and the verified
   recovery point.

The machine-readable matrix rejects missing release notes, unreviewed
migrations, incomplete gates, imprecise images and components without a
backup-restore strategy.

## Maintenance boundary

```sh
infra/upgrade/maintenance.sh enable
infra/upgrade/maintenance.sh status
```

The mode stores its state in its own Compose volume. FastAPI still answers
read requests but rejects `POST`, `PUT`, `PATCH` and `DELETE` with
`503 maintenance_mode` and `Retry-After`. The core worker, Twenty server and
Twenty worker are stopped. Only when the dependencies are ready again does
this command lift the write lock:

```sh
infra/upgrade/maintenance.sh disable
```

## Order in the change window

1. Enable maintenance mode and verify the write lock with a real request.
2. Create and verify an encrypted recovery point with `./leonaid backup`.
3. Start the RustFS target image and wait for its health check.
4. Start the Twenty target server once so that its entrypoint initializes
   the schema prerequisites.
5. Stop the Twenty server again and run both official commands fail-closed:

   ```sh
   docker compose --env-file .env.local -f infra/compose/compose.yml \
     run --rm --no-deps --entrypoint yarn twenty-server \
     command:prod run-instance-commands
   docker compose --env-file .env.local -f infra/compose/compose.yml \
     run --rm --no-deps --entrypoint yarn twenty-server \
     command:prod upgrade
   ```

6. Start the Twenty server/worker and LeonAid; check images, schema and
   health checks.
7. Run the contract suite, golden snapshot and browser journey.
8. Only then disable maintenance mode.

Twenty logs failed entrypoint upgrades only as a warning and can still look
healthy. LeonAid therefore accepts neither the health check nor the
entrypoint alone as proof of migration: both commands must exit with code 0,
the expected target schema must exist and the business contract must still
pass unchanged.

## Rollback boundaries

- **Twenty:** After the first instance or workspace migration step, no older
  image is started against the forward-migrated database. Rollback means
  restoring Twenty PostgreSQL and the Twenty files from the same recovery
  point.
- **RustFS:** A binary rollback is possible before the target version writes.
  After that, the complete RustFS volume is restored.
- **LeonAid Core:** After `alembic upgrade head`, no older core is claimed to
  work against the new schema. Core PostgreSQL is restored from the recovery
  point.
- **Core migration `0063_buyer_mails` (order number for every order):** an
  application from before this migration fails for certain against the
  migrated database, not only possibly. It refuses every order that a member
  entered, because such an order now has an order number
  (`commitment_public_reference_forbidden`), and every public order with the
  new short number (`commitment_public_reference_invalid`): the order list,
  the invoice journal and the worker's order mails answer with an error.
  Never start the older image against the migrated database. Roll back in
  this order: stop API and worker, restore Core PostgreSQL from the recovery
  point (or, when no order was written since the upgrade, run
  `alembic downgrade 0062_sponsor_search_entry` with the new image, which
  removes the numbers of internal orders and the buyer-mail settings), then
  start the older image. Order numbers that buyers already received in a
  mail are lost by the downgrade for orders that members entered.

On failure, the write lock stays active. The failed project is stopped,
receives no further writes and is restored into a new, explicitly confirmed
Compose project as described in
[`infra/backup/README.md`](../backup/README.md). Only the golden contract,
document hashes, sessions and browser journey release the environment again.

## Reproducible PoC evidence

```sh
./leonaid test-upgrade
```

The test uses no mocks. It starts Twenty 2.24.0 and RustFS 1.0.0-beta.11
with real golden data, upgrades to Twenty 2.54.0 and RustFS 1.0.4, checks
contracts and Chromium before and after the upgrade, deliberately damages a
separate target clone and restores it from the encrypted recovery point.
Secret-free results are stored under `.artifacts/poc113/`.

The pilot release evidence extends this component contract with an immutable
release manifest, identical staging/production promotion, a real failed
Alembic run and a secret-free promotion ledger:

```sh
./leonaid test-pilot-release
```

The operating procedure is described in
[`../pilot/RELEASE-RUNBOOK.md`](../pilot/RELEASE-RUNBOOK.md).
