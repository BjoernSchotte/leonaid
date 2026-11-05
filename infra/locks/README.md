# Reproducible dependencies

`external-systems.lock` is the canonical, machine-readable list of all
external systems and of all containers that build or check the PoC. Each
entry always contains a readable tag and the immutable multi-arch index
digest. Compose and Dockerfile references must use the same form
`image:version@sha256:digest`.

`browser-artifacts.lock` also records the browser revisions contained in the
Playwright image. `uv.lock` and `bun.lock` are the canonical package locks.
The toolchain versions are in `.tool-versions`.

As a narrow exception, the React peers of `packages/surveys` declare the
compatibility range `^19.2.8`. The pin checker allows this only for `react`
and `react-dom` in the peer section of this package. Every LeonAid host that
includes the package directly must pin both runtime dependencies exactly to
`19.2.8`. All other packages and dependency sections stay pinned exactly.
The independent consumer also checks the versions actually installed and uses
its own frozen lockfile. A version change requires a joint update of this
policy, the hosts and the locks, plus a new consumer test. The peer range
alone is no test evidence for future React versions.

Updates happen only in an explicit Renovate PR or a manually opened upgrade
PR. Such a PR updates tag and digest, sets `reviewedAt` and `nextReviewOn`,
regenerates all locks and SBOMs and passes the contract and E2E gates.
Automerge is disabled.

## Review deadline and vulnerability gates

`tools/pins/check.py` fails once `nextReviewOn` lies in the past, and it
rejects a `nextReviewOn` more than six months after `reviewedAt`. A review
compares every pinned tag with its latest upstream release and advisories,
upgrades or consciously keeps it, and runs `./leonaid check` and
`tools/ci/security.sh`. Then set `reviewedAt` to the review date and
`nextReviewOn` to at most three months later.

Every system in this lock must be classified in
`infra/security/image-scan-scope.json`: scanned as a runtime image, or
excluded with a kind and a reason. `tools/security/vulnerability-scan.sh`
blocks fixable HIGH/CRITICAL findings in the checkout, all LeonAid images,
the scanned third-party images (Trivy) and in `uv.lock`/`bun.lock`
(OSV-Scanner). Findings without an upstream fix go into
`infra/security/vulnerability-allowlist.json` with reason, reviewer and an
expiry at most 90 days after the review; expired waivers fail the gate.

The checks run only inside the Docker images recorded here:

```sh
docker run --rm -v "$PWD:/workspace:ro" \
  python:3.13.18-slim-trixie@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc \
  python /workspace/tools/pins/check.py /workspace
```
