# EmDash spike decisions

Status: dependency and closed-runtime checkpoints passed; database, authorization
and public campaign delivery remain unproven.

## Dependency baseline (EMS-000)

- EmDash: `0.36.0`, MIT, upstream source commit
  `603062902369d9695608e85c2d034d4f66f7a1f1`.
- npm tarball: `https://registry.npmjs.org/emdash/-/emdash-0.36.0.tgz`.
- Integrity: `sha512-a/lldbDMig8z3WycPliHwZ2VwFQl9ewT9OMvK9/2gvbzoJOXXUF73KTK7AThSss5SbT1oj0h9exGa/GyIr3vAw==`.
- Astro `7.1.3`, Node `22.23.0`, Bun `1.2.19`: existing repository versions.
- Node adapter `11.0.2`, React adapter `5.0.7`, React/React DOM `19.2.8`.
- PostgreSQL driver `pg@8.16.3` (MIT). Real PostgreSQL proof is still pending.
- The S3 adapter imports packages not declared by EmDash itself. Explicitly add
  `@aws-sdk/client-s3@3.1127.0` and `@aws-sdk/s3-request-presigner@3.1127.0`
  (Apache-2.0); omission failed the first production build.
- Direct versions live in `apps/campaign-site/package.json`; transitive versions
  and package integrity live in the existing root `bun.lock`.

## Persistence and security boundaries

Use a dedicated `emdash` database and non-superuser role on the isolated
installation's existing Core PostgreSQL server. Use a private CMS-only RustFS
bucket with scoped credentials. No SQLite fallback and no Core database access.
Provisioning and SQL/media recovery proofs remain outstanding.

No marketplace, native third-party, or sandboxed plugins are authorized. No
`workerd` runtime is planned. Before adding any HTTP route, deny setup and editor
access by default. Charity Admin access remains disabled until the complete
campaign-isolation gate passes. A narrow pinned identity/authorization patch may
be evaluated under the plan's STOP rules; no broad fork is approved.

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
