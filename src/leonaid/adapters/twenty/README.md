# Twenty CRM Gateway

The gateway implements the domain port from
`leonaid.application.crm`. Application services talk only through
`CompanyData`, `PersonData`, controlled update types and
`CrmSyncReceipt`. Twenty's wire fields and transport details stay in
`gateway.py`.

## Deliberate boundaries

- Companies and people stay authoritative in Twenty.
- LeonAid does not duplicate any CRM party. A `CrmSyncReceipt` links the ID
  of the triggering LeonAid domain object to the Twenty record ID, status and
  correlation.
- Create and update accept only the explicit semantic fields of each data
  type. Arbitrary Twenty payloads are not part of the port.
- A partial person update sends only the parts of the composite name that are
  actually set; a first-name update does not silently clear the last name.
- Delete, merge and free metadata operations are not part of the gateway.
- Browsers and acquirers talk only to the LeonAid Core API. They get neither a
  Twenty login nor a Twenty API key. The restricted integration key is injected
  on the server side only.

## Transport contract for Twenty 2.54.0

- REST Data API for search, read, single create and controlled patch.
- GraphQL Data API for create batches.
- At most 60 records per batch; larger inputs are split into stable chunks of 60.
- At most 100 requests per minute and gateway process, enforced by
  sliding-window throttling.
- Configurable total/connect/read/write/pool timeout.
- `429` is retried only after a bounded, capped `Retry-After`.
- REST pagination follows only `pageInfo.endCursor` via `starting_after`.
  Duplicate IDs, repeated cursors, missing next cursors and an endless page
  sequence are rejected.

## Bounded queries and match keys

Request paths never list a whole Twenty collection. The port
(`CrmGateway`) offers only queries bounded by a name, a match key or explicit
record IDs; `list_companies`/`list_people` exist on the adapter for imports
and maintenance only.

- Every create and every name-changing update stores the normalized match key
  (`leonaid.application.crm_matching.normalize_match_name`) in the provisioned
  custom field `leonaidMatchKey` on companies and people. After each update
  the gateway compares the stored key with the key of the returned name and
  patches it when they differ (for example after a partial person rename).
- `find_companies_by_match_key`/`find_people_by_match_key` use an exact
  `leonaidMatchKey[eq]` filter. `find_company_matches`/`find_person_matches`
  combine that lookup with the literal name search and keep only records
  whose current name still has the requested key. Matching therefore costs two
  bounded queries, independent of the CRM size, and a stale key never causes a
  false match.
- `get_companies`, `get_people` and `list_company_contacts` read referenced
  records with `id[in]`/`companyId[in]` filters in chunks of 50 IDs.
- List pages use Twenty's maximum of 200 records (`page_size` default).
- `repair_match_keys` (operator command
  `./leonaid repair-crm-match-keys`) backfills keys for records created or
  renamed outside LeonAid. It is idempotent and patches only records whose
  stored key differs from their name.

For the people batch projection, Twenty 2.54.0 needs the direct field
`companyId`. A GraphQL selection of the relation `company { id }` also tries to
read the technical company field `deletedAt`, which is not granted, and the
least-privilege role correctly denies it. The gateway therefore requests no
further permissions.

## Error and correlation contract

Every request carries `X-Request-ID` and `X-Correlation-ID`. Successful writes
return `CrmSyncReceipt(status=SYNCED)` and log only operation, correlation,
LeonAid ID, Twenty ID, party type and status.

`CrmGatewayError` contains a stable code, a retry hint, the HTTP status, the
correlation and, where known, both IDs. Response bodies, payload data and API
keys never go into error texts or logs.

Transport errors during reads are safe to retry. For writes the gateway does
not retry blindly, because the response may have been lost after successful
processing. The error then carries `outcome_unknown=True`; the calling use case
must reconcile based on the domain matching/idempotency rules. With several
chunks of 60, an error also contains the receipts that were already confirmed.

## Real-system check

```sh
./leonaid test-twenty-gateway
```

The test starts an empty, isolated, pinned Twenty instance, provisions the
least-privilege role and checks real batches, CRUD, search, pagination,
correlation, outage and restart. It uses no mocks, HTTP fixtures, direct
database access or fixed sleeps.

`./leonaid test-policy` adds the record-level Core policies to this transport
proof, against the same real Twenty and real PostgreSQL. Twenty only provides
the companies and contacts that are already authorized; the Core derives these
IDs from membership and assignment on every request.
