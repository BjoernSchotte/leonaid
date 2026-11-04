# Live pilot: daily technical check

This runbook describes the daily technical check for a limited LeonAid
pilot. It replaces neither the functional pilot approval nor the open
decisions on legal entity, tax, privacy or operations.

## Responsibility and schedule

A named system admin runs the check on every pilot day before the usage
window starts, and after every P0/P1 incident:

1. open `System` in the portal (tab `Betrieb`, operations);
2. select `Tagesreport erstellen` (Create daily report);
3. read the status, the six operations areas, the stop reasons and the next
   step;
4. download the JSON report;
5. store it in the private, access-restricted pilot evidence area;
6. on `blocked`, do not start the pilot, or stop it immediately;
7. on `attention`, assign the finding to an owner and a due date.

The report is always generated fresh from the current system state. Old
downloads say nothing about today's state.

## Covered areas

The report combines only technical and aggregated values:

- latest backup status;
- open alerts by priority;
- outbox backlog and dead letters;
- available storage;
- TLS certificate status;
- reachability of the core database, Twenty, RustFS and the mail provider.

It contains no names, email addresses, or sponsor, order, invoice,
payment, request or response payloads.

## Status and stop reasons

The report's `technicalStatus` is one of:

- `ready`: no technical blocker and no technical finding that needs
  attention;
- `attention`: the pilot can technically continue, but the finding needs an
  owner and a due date;
- `blocked`: at least one stable stop reason is present.

A P0/P1 alert, a critical or missing backup, storage or TLS check, a dead
letter, an inactive or unreachable monitor, or an unreachable core
dependency blocks. The machine-readable stop reasons in the report are the
leading diagnosis. The displayed next step names the safe operator action.

`ready` explicitly does not mean that the live pilot is approved
functionally, for privacy or organizationally. For that, the approvals and
stop criteria from `PILOT-001`, `PILOT-044`, `PILOT-050` to `PILOT-053`
remain authoritative.

## Integrity check

The response header `X-Content-SHA256` and the field `checksumSha256` contain
the same checksum. It is computed over the UTF-8 encoded, compact JSON form
of the report without `checksumSha256`; object keys are sorted
lexicographically, non-ASCII characters are written as JSON escapes.

A diverging hash makes the download invalid as evidence. Generate the report
again directly from the portal. If the mismatch repeats, stop the pilot and
open a P1 incident.

## Incident and end of day

On a stop reason:

1. do not grant technical approval, or stop the pilot;
2. record support code, release, stop reason and time without personal data;
3. run the matching runbook for backup, alert, outbox, storage, TLS or
   dependency;
4. after the fix, generate a new daily report;
5. continue only with P0/P1 closed and the required functional approvals in
   place.

At the end of the day, volume, error rates, support cases, restarts and open
P2/P3 items are recorded in aggregate. A single daily report is not yet a
final report and does not yet prove that a live pilot actually took place.
