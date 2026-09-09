# One-time bootstrap control

The CMS is opt-in and its setup routes are denied by default. A missing or
unreadable state file, empty database, database outage, expired grant or failed
setup attempt does not authorize setup.

`cms-bootstrap-state` is a project-scoped Docker volume mounted at
`/app/bootstrap-state`, owned by the runtime Node user. It is separate from
PostgreSQL. An operator explicitly runs `tools/emdash_spike/arm-bootstrap.mjs`
in a network-disabled container sharing only that volume and the required source
directories, with the designated Core System Admin UUID as its sole argument.
The isolated proof contains the corresponding Compose operator definition;
normal `./leonaid` activation/recovery UX is still pending.

The grant is valid for 15 minutes and one setup attempt. Requests must also
authenticate against Core now, match the designated UUID, use the configured
HTTPS public origin and pass the origin/custom-header checks. The operator grant
is not a login credential and never substitutes for a current Core session.

State transitions:

```text
missing --explicit operator activation--> armed
armed --before upstream setup POST--> consumed
consumed --HTTP success AND verified database completion--> complete
```

An exclusive filesystem lock serializes transitions. State writes use file
sync, atomic rename and directory sync. A stale lock or temporary state after a
crash blocks further attempts; it is not automatically removed. No HTTP route
rearms the grant. Failure after consumption requires operator diagnosis and an
explicit recovery decision. Repeating the activation command refuses an existing
state rather than resetting it. This intentionally prioritizes safety over an
automatic retry of a partially applied seed.

Only the exact setup page, setup-status GET and setup POST are allowlisted.
Other setup, login and mutation paths remain closed. Upstream's setup response
alone is insufficient: it catches some persistence errors, so the outer guard
queries the actual `emdash:setup_complete` option before marking the independent
state complete.

Caddy is the public ingress; the CMS has no published port. CMS HTTP paths now
redirect to HTTPS locally. Caddy overwrites forwarded host/protocol/client-IP
headers and removes `Forwarded`. The application checks the canonical HTTPS
host and explicit Origin. Both Caddy configurations require TLS SNI and HTTP Host
to match. This does not claim isolation from compromised peer
containers on the shared Edge network; that trust boundary and the final pilot
origin configuration still need the complete EMS-070 review.

Recovery must include this volume alongside the CMS dump, mapping, media and
encryption-key continuity. Never infer an armed state when restoring a backup
without it. The versioned backup/restore implementation is still pending in
EMS-080; enabling a CMS pilot before that gate passes is not authorized.

Verification command: `./leonaid test-emdash-spike --case bootstrap-runtime`.
It uses real production EmDash/Core/PostgreSQL and Caddy TLS with the test CA
explicitly trusted by the HTTP client. It publishes no host ports, uses synthetic
accounts, owns its project resources and removes only those resources. Browser
wizard interaction, full recovery and general editor access are separate gates.
