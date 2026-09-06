# EmDash spike decisions

Status: dependency, closed-runtime, PostgreSQL and RustFS provisioning checkpoints
passed; integrated service, authorization and public campaign delivery remain unproven.

## Dependency baseline (EMS-000)

- EmDash: `0.36.0`, MIT, upstream source commit
  `603062902369d9695608e85c2d034d4f66f7a1f1`.
- npm tarball: `https://registry.npmjs.org/emdash/-/emdash-0.36.0.tgz`.
- Integrity: `sha512-a/lldbDMig8z3WycPliHwZ2VwFQl9ewT9OMvK9/2gvbzoJOXXUF73KTK7AThSss5SbT1oj0h9exGa/GyIr3vAw==`.
- Astro `7.1.3`, Node `22.23.0`, Bun `1.2.19`: existing repository versions.
- Node adapter `11.0.2`, React adapter `5.0.7`, React/React DOM `19.2.8`.
- PostgreSQL driver `pg@8.16.3` (MIT), verified with the actual EmDash adapter.
- `kysely@0.29.5` is explicitly pinned for the real EmDash migration proof.
- The S3 adapter imports packages not declared by EmDash itself. Explicitly add
  `@aws-sdk/client-s3@3.1127.0` and `@aws-sdk/s3-request-presigner@3.1127.0`
  (Apache-2.0); omission failed the first production build.
- Direct versions live in `apps/campaign-site/package.json`; transitive versions
  and package integrity live in the existing root `bun.lock`.

## Persistence and security boundaries

Use a dedicated `emdash` database and non-superuser role on the isolated
installation's existing Core PostgreSQL server. Use a private CMS-only RustFS
bucket with scoped credentials. No SQLite fallback and no Core database access.
PostgreSQL and RustFS provisioning are proven; coordinated SQL/media recovery
proofs remain outstanding.

`tools/emdash_spike/provision-postgres.mjs` is operator-only. Its CLI requires
`CMS_PROVISION_DATABASE_URL` and `CMS_POSTGRES_PASSWORD`; Core DB/owner default
to the existing `leonaid` names and can be supplied explicitly. Run it only in
an operator container on the selected installation's database network, never
inside the CMS HTTP service. It checks ownership/role state before mutation,
serializes provisioning with a PostgreSQL advisory lock, and preserves explicit
Core-owner access while removing PUBLIC access to Core. Unexpected additional
active Core clients require operator review. No Core tables are modified.

No marketplace, native third-party, or sandboxed plugins are authorized. No
`workerd` runtime is planned. Before adding any HTTP route, deny setup and editor
access by default. Charity Admin access remains disabled until the complete
campaign-isolation gate passes. A narrow pinned identity/authorization patch may
be evaluated under the plan's STOP rules; no broad fork is approved.

## Native editor revision transport (EMS-020/030)

The reviewed Git checkout and the published 0.36.0 tarball are not interchangeable
evidence. The installed admin bundle discards the server's `_rev` envelope and
omits revision tokens from native saves, whereas the reviewed checkout contains
later editor concurrency work. Runtime proofs use the exact locked npm packages.

`apps/campaign-site/emdash-editor-patch.mjs` applies a build-local backport to the
published admin bundle with SHA-256
`b7c64e5f4ba4cb760d1694332d920194a107db6d42258fd5358a1201776ce299`.
It preserves read/update tokens, remembers the revision loaded by each editor,
sends that token on native manual/autosaves, and refreshes it after publishing.
Background query refreshes must not silently advance a stale editor's token.
The build checks every replacement anchor, rejects byte drift and repeat
application, and fails if the production client transform did not execute.
This is an additional narrow spike-only compatibility patch, not authorization
to maintain a broad fork. Reevaluate against a published upstream fix before
pilot release; upstream coordination and complete editor operations remain open.

The server continues to require `_rev` and serializes updates in PostgreSQL.
Native slug/locale echoes are accepted only unchanged. Autosave's `skipRevision`
hint is deliberately ignored after type validation: retain an attributed revision
for every accepted save. Measure resulting history/storage cost in the resource
and recovery gates. Publication still uses the actual 0.36 server contract;
no revision-token publication guarantee is inferred from newer checkout code.

## Local execution boundary

Do not operate the existing `leonaid` Compose project. Every spike test owns a
new uniquely named project, networks and volumes. Tests must check ownership
before cleanup and must never attach to external networks or fixed volume names.
Use loopback-only dynamically allocated ports for test proxies where possible;
do not claim ports 8080/8443 used by the parallel development stack.

## Evidence

Registry metadata was read inside the repository-pinned Node Docker image on
6 September 2026. All listed package versions exist. Package availability is not
proof of integration compatibility. Subsequent evidence must distinguish
dependency, build, database, browser, authorization and recovery gates.

- `./leonaid test-emdash-spike --case dependencies`: passed version, integrity,
  license and workspace/Dockerfile parity checks.
- `./leonaid test-emdash-spike --case closed-runtime`: production Docker build
  and real HTTP proof passed. Astro check reported zero errors/warnings/hints;
  Vite emitted upstream deprecated React-plugin option and bundle-size warnings.
- EmDash's supported `middleware.outer` runs the closed bootstrap guard before
  EmDash database, setup and auth middleware. Eighteen GET/POST requests to editor,
  setup, plugin, login, MCP, campaign and readiness routes returned 503/no-store.
  Liveness returned 200 without a database and with Docker networking disabled.
- No host ports, named volumes or shared Compose networks were used. The test
  runner builds to a per-invocation image-ID file, not a shared mutable image tag.
- No full-spike success is reported: the unqualified test command exits nonzero
  while the remaining cases are unimplemented. Closed access is a temporary
  implementation checkpoint, not the target CMS functionality.
- `./leonaid doctor` and `./leonaid check` passed; the latter at commit `6d881f9`
  with 206 unit tests, all type/format/API/policy gates, and an unchanged tree.
  Readiness/privacy tests needed read-only access to linked-worktree Git metadata.
  One pre-existing identity-test line was mechanically reformatted; its 28 tests
  passed independently before the complete suite.
- The running-container/port inventory before and after the checkpoint matched;
  the existing LeonAid stack on 8080/8443 was not restarted or reconfigured.
- `./leonaid test-emdash-spike --case postgres`: passed on fresh volumes and
  again after restart. The real EmDash PostgreSQL adapter applies migrations
  twice with no pending migrations. Core and CMS rows persist; the CMS login
  cannot connect to Core, create a database, create a privileged role or switch
  to the Core role. Unsafe existing role attributes and wrong ownership are
  rejected. The operator remains separate from the eventual CMS runtime.
- The PostgreSQL test creates a unique Compose project with internal `cms-data`
  and `core-data` networks and its own volume, checks for project collisions
  before startup, publishes no ports, and cleans only its own resources.
- `./leonaid check` passed again at PostgreSQL checkpoint commit `08e2169`:
  206 unit tests, all existing quality gates plus CMS type/format checks, and
  an unchanged worktree. This does not prove the outstanding RustFS/auth gates.

## RustFS operator and proof

Use the native signed RustFS admin API for scoped credentials and policy
bindings, as described in the official
[IAM documentation](https://docs.rustfs.com/en/security-compliance/iam/policies).
The documented user/policy endpoints are under `/rustfs/admin/v3`. Verify their
behavior against the pinned beta.11 image rather than treating documentation as
proof of a successful provision or a working least-privilege policy.

- `python -m tools.emdash_spike.provision_rustfs` runs only in an operator
  container. It needs `RUSTFS_ENDPOINT_URL`, root `RUSTFS_ACCESS_KEY` and
  `RUSTFS_SECRET_KEY`, plus `CMS_S3_ACCESS_KEY_ID=leonaid-emdash` and a separately
  supplied `CMS_S3_SECRET_ACCESS_KEY`. The runtime must receive only CMS keys.
- The fixed `emdash-media` namespace has no anonymous policy. Existing bucket
  policies, unexpected IAM attachments/groups and different named policies are
  rejected for review rather than silently replaced. Signed admin requests do
  not follow redirects or print credential-bearing response bodies.
- beta.11 returns HTTP 500 for a missing individual policy lookup. Provisioning
  uses the successful full policy inventory to establish absence; it does not
  reinterpret arbitrary HTTP 500 errors as permission to create a policy.
- `./leonaid test-emdash-spike --case rustfs` passed the real operator process,
  repeated provisioning, private own-bucket operations, cross-bucket/admin/
  anonymous denial, unexpected binding rejection, and IAM/object persistence
  after restart. Only the fresh test project's resources were removed.
- App runtime S3 wiring, browser media delivery and coordinated recovery are
  still outstanding and must not be inferred from this provisioning proof.
- Full `./leonaid check` passed at commit `97b6d83`: 206 unit tests, type checks
  covering 240 Python sources and all frontends including CMS, format checks,
  policy/API/privacy gates, and unchanged Git state. EMS-000 is complete; the
  next gate is EMS-010's integrated private service and route ownership proof.
