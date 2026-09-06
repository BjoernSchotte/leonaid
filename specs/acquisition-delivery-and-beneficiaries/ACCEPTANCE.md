# Acceptance evidence and remaining scope

This is a partial requirement audit, not a completion declaration. Checked PLAN.md items are supported below; unchecked items remain open until their full stated scope is demonstrated.

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Window invariants and recipient/window snapshots | `tests/unit/test_delivery_domain.py`: 7 tests passed on 2026-09-06. `tools/delivery/orders.py` and `foundation.py` passed against PostgreSQL, including actual create/readback and old/new recipient serialization. | Proven |
| Migration, references, old defaults and fixtures | `tools/delivery/foundation.py` applies 0027 over historical confirmed data, checks nullable initial selection, snapshot/reference protection, retirement and downgrade/re-upgrade. Fresh run exited 0. | Proven |
| Retirement, booked timezone and action period | `tools/delivery/foundation.py`, `concurrency.py` and `form_configuration.py` prove booked-window/timezone protection, real concurrent booking/retirement in both channels, and rejecting action-period edits that exclude configured dates. Fresh run exited 0. | Proven |
| Authorized schedule read/write and revision conflicts | `foundation.py` exercises real role principals and repository revision races; recorded admin gate `...admin-20260906l` proves actual competing HTTP writes and both UI reconciliation choices. | Proven |
| Delivery section in management UI | Current `manage-action.tsx` mounts `DeliverySection`; recorded real admin browser gates prove persisted editing, tab retention, 3/3/1 windows and responsive rendering. | Proven |
| Historical read and non-delivery regression | `foundation.py` reads a valid pre-0027 confirmed order through the actual repository after migration with unchanged buyer/line/total and null delivery. `form_configuration.py` creates, reads and replays a sponsoring order without delivery. Both passed in the latest isolated run. | Proven |
| Same-action operational configuration propagation | Real Admin UI saves 3/3/1 windows; already-loaded Anna/public forms refresh to identical saved IDs without rebuild or CMS publication. Both channels now create real orders afterward; admin API and PostgreSQL prove matching delivery snapshots and separate/reused billing. Same-action retirement now rejects both loaded selections, retains inputs and creates no orders until explicit replacement. Admin UI detail inspection and EmDash continuation remain open. | Partial |
| Template/default compatibility across channels | Persisted Krapfentaxi/blank defaults and existing null records are proven. `form_configuration.py` now also creates and reads a real review-ready sponsoring order on a blank action, preserving EUR 5 pricing and billing with null delivery fields; exact replay returns the same order. Broader channel/template compatibility still needs integrated acceptance. | Partial |
| Both capture channels and legacy completion | Actual acquisition/public orders, address reuse/separation, notes/contact, country fields, historical completion and invoice issuance have separate proofs in PROGRESS.md. The complete integrated action journey is not yet recorded. | Partial |
| Recovery behavior | Public stale policy/window, empty availability, no-JavaScript error retention and accepted-response retry; Anna accepted-response 503 retry; admin revision reconciliation all have recorded live proofs. Audit remaining draft/action-switch and no-JavaScript unknown-outcome scope before marking the broad item complete. | Partial |
| Privacy handling of new delivery fields | Real privacy browser flow and PostgreSQL assertion remove contactName, contactPhone and instructions; existing retained invoice/document hashes stay unchanged. See privacy checkpoint in PROGRESS.md. | Proven |
| Final In-App Browser acceptance | Direct public desktop In-App screenshots and billing-toggle/notes/refresh interactions now pass; corrected the refresh button found there. Exact mobile widths and the integrated authenticated journey remain open. | Partial |
| EmDash canonical/alias parity and editorial independence | Read-only parallel worktree baseline `3f39ed7` records the SMTP browser login checkpoint; its `apps/campaign-site/src` still has no public order renderer. No source was imported or modified there. | Open |

Fresh foundation command:

```sh
LEONAID_DELIVERY_FOUNDATION_SUBNET=172.30.81.0/24 sh tools/delivery/test-foundation.sh
```

The run used a newly created internal network, temporary PostgreSQL storage and no host ports; cleanup targeted only returned resource IDs. The default automatic subnet attempt failed before starting a database because Docker's address pools were exhausted. Optional explicit subnet support was added and the completed run passed every foundation/order/race/completion/template check. No existing Docker network was removed or changed.
