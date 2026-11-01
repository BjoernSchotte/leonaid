# Pilot operations runbooks

Every alert carries only technical labels, a fixed summary and a link to the
matching procedure below. Person, order, invoice, document and token content
never belongs in metrics or alerts.

## Backup

1. Acknowledge the alert in the independent operator channel.
2. Run `pilot-doctor` with the private latest manifest.
3. Check the restic target, credentials, free space at the target and the
   latest complete four-component snapshot.
4. If the backup is incomplete or old, create a new recovery point and run
   `restic check --read-data`.
5. Close the alert only after a successful check and a visibly delivered
   recovery event.

## Dependency

1. Identify the affected service from the `dependency` label.
2. Cross-check its state in `/admin/system`.
3. Search service logs only by request ID and stable error codes.
4. Restart the pinned service in a controlled way; never delete data volumes.
5. Wait for readiness and for the resolved-alert notification.

## Worker

The worker is ready only while PostgreSQL is reachable and each background
loop (`outbox`, `survey_sweep`) keeps completing iterations.

1. Read `GET /health/ready` on the worker (port 8010): `checks` names the
   failing loop.
2. Check the metrics `leonaid_worker_loop_healthy`,
   `leonaid_worker_loop_failures_total` and
   `leonaid_worker_loop_last_success_age_seconds` per `loop` label.
3. Search the worker log for `worker.loop.failed`. Each entry names the loop,
   the error type and the code location, never row data. A
   `worker.configuration.invalid` entry means the worker exited on start
   because of missing settings; fix the environment, do not restart blindly.
4. Restart the worker with the unchanged release image.
5. Check the outbox counters and the dead-letter backlog.
6. Retry business jobs only through the protected admin retry.

## Dead Letter

1. Restore the dependencies first.
2. Check the stable error code in `/admin/system`.
3. Sign in again and trigger `Sicher wiederholen` (safe retry).
4. Confirm exactly one successful processing and the resolved alert.

## Disk

1. Stop write-heavy processes without silencing backup or security alerts.
2. Identify large technical logs, temporary files and old, released
   Prometheus blocks.
3. Never delete database, RustFS or restic files by hand.
4. Add capacity or apply only the documented retention.

## TLS

1. Check the public domain, certificate chain, host name and expiry date.
2. Check the Caddy ACME logs and DNS resolution.
3. If renewal failed, check the ACME contact, reachability of ports 80/443 and
   rate limits.
4. Never roll back HSTS; renew the certificate in a controlled way.

## API

1. Determine the 5xx time window and the release commit.
2. Use request IDs from structured logs; never copy payloads.
3. Check dependencies, the database migration and the latest release.
4. If a release regression is suspected, follow the release runbook.

## Watchdog

`LeonAidWatchdog` fires all the time on purpose. Alertmanager sends it every
five minutes to the external heartbeat URL (`LEONAID_ALERT_HEARTBEAT_URL_FILE`)
and to nothing else. The external service alarms when these pings stop.

When the heartbeat service reports missing pings:

1. Check that the host answers and that `https://<portal-domain>/_health`
   returns `ready`.
2. Check that `prometheus` and `alertmanager` run:
   `docker compose ... --profile monitoring ps`.
3. Check the Alertmanager log for delivery errors to the heartbeat URL.
4. Start the monitoring profile again with `./leonaid pilot-monitoring`.
5. Close the incident only after the heartbeat service shows new pings.

## Login

1. Check rate limits, provider state and delivery state separately.
2. Never post email addresses, codes or magic links to the alert channel.
3. If abuse is suspected, escalate to the security owner and evaluate
   AuditEvents without payloads.
