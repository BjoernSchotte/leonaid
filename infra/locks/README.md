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

Updates happen only in an explicit Renovate PR, a manually opened upgrade PR
or the re-pin PR described below. An upgrade PR updates tag and digest, sets
`reviewedAt` and `nextReviewOn`, regenerates all locks and SBOMs and passes
the contract and E2E gates. Automerge is disabled.

`tools/pins/check.py` also requires that every other file agrees with the
lock: each `name:tag@sha256:digest` reference anywhere in the checkout
(Compose, Dockerfiles, scripts, READMEs, `infra/upgrade/compatibility-matrix.json`,
golden fixtures) must be a locked image. Only proofs under `specs/` keep the
images they ran with. Workflows read images from `images.env` and carry no
digest of their own.

## Upstream rebuilds and digest drift

Upstreams such as the Docker Official Images rebuild an existing tag for
security patches. The tag then points to a new digest; the version stays.
The recorded digest stays pullable, so the pin is still reproducible:

- Pull-request, merge-queue and push CI (`Dependency pins` →
  `tools/pins/verify-image-digests.sh`) require that every recorded digest
  still resolves in its registry. A moved tag alone does not fail.
- A pin that the change adds or alters (compared with the PR or queue base,
  or with `main` for dispatched runs) must be the digest its tag resolves to
  at that moment.
- The daily `Image pin drift` workflow (`.github/workflows/pin-drift.yml`)
  resolves every tag on `main`. On drift it rebuilds the branch
  `pins/repin-images` from `main`, rewrites every file that carries an old
  digest (`tools/pins/image_digests.py repin`; the lock is the source of
  truth, `images.env` is regenerated from it) and opens or updates one PR.
  The PR runs the full CI, including the vulnerability gate. Once `main` has
  no drift any more, the workflow closes that PR.
- The workflow uses only `GITHUB_TOKEN` (`contents`, `pull-requests`,
  `actions`: write). Pushes and PRs made with it start no workflows, so it
  dispatches every required workflow on the branch; their checks report on
  the head commit and satisfy branch protection. If a check is missing, run
  `gh workflow run <file> --ref pins/repin-images`. Opening the PR needs the
  repository setting "Allow GitHub Actions to create and approve pull
  requests" (Settings → Actions → General → Workflow permissions).
  `tools/ci/workflow_contract.py` keeps the dispatched list equal to the
  required checks.

Fix drift locally in seconds:

```sh
./leonaid repin-images                  # every system
./leonaid repin-images --image postgres # one lock system id
LEONAID_PIN_ALL_TAGS=1 sh tools/pins/verify-image-digests.sh .  # report drift only
```

Then review `git diff`, commit and run `./leonaid check`. A re-pin keeps the
version, so it does not change `reviewedAt` or `nextReviewOn`. If two lock
systems share the drifted digest, the command refuses; re-pin them by hand.

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
