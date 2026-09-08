# SURV-100 — Corrected Caddy dependency and image integration

**Status: pending. Task 100.3i / scenario 100.S2h remain open.** The corrected
candidate passes image scans, bounded routing checks and the full application
security suite. Complete pilot release/restore runs, promotion into the main
worktree and integrated CI acceptance are outstanding. No scanner exception is
introduced; the earlier rejected VEX proposal is not active or delivered.

## Problem and selected correction

The current branch's security job reports CVE-2026-56854 in
`golang.org/x/crypto` 0.52.0. The reported fixed version is 0.55.0. The candidate
builds Caddy 2.11.4 with that corrected dependency using pinned builder/runtime
images, a committed Go module graph, module checksum verification and a local
Go 1.26.8 toolchain. CGO is disabled and target OS/architecture are explicit.
The runtime image receives the resulting binary from the builder stage.

The image exporter saves the exact Docker build result by image ID rather than
a shared mutable tag. Both scanner and SBOM generation consume the exported
image. Scanner policy remains critical severity, ignore-unfixed and exit code 1
on a finding. The original vulnerable image still fails the same policy.

## Evidence inventory

| Required layer | Observed evidence | Boundary |
| --- | --- | --- |
| amd64 and arm64 actual images | Both candidate image scans exit zero with zero fixable critical findings; binary provenance identifies the selected dependencies. | Image-specific evidence; does not prove a complete application deployment. |
| Negative scanner control | Original image exits 1 with CVE-2026-56854. | No VEX or other finding suppression. |
| TLS and route handling | Eight routes pass on each architecture using the production Caddyfile. | Synthetic upstreams; application behavior is covered separately. |
| Application security | Complete service-backed security command exits zero in 639.764 seconds; one Chromium test passes in 1.1 seconds; independent owned cleanup passes. | Candidate-only run; release/restore still separate. |
| SBOM integration | Complete command produces 17 nonempty CycloneDX documents; the Caddy document identifies the corrected dependency. | Inventory evidence, not a substitute for vulnerability scans. |
| Pilot deployment | Running baseline proxy identifies Caddy 2.11.4, Go 1.26.8 and crypto 0.55.0; real TLS/deployment-doctor checks and manifest creation pass. The next Doctor fails against a stale container ID after Compose recreates the proxy. | Baseline exits 125 after 1191.875 seconds; full corrected repetitions remain pending. |
| Corrected survey pilot deploy | With unchanged HEAD, negative manifest drift is rejected as expected and the actual manifest-bound operator deploy plus subsequent Doctor pass. The running proxy reports Caddy 2.11.4 / Go 1.26.8 / crypto 0.55.0. | The complete survey pilot exits zero in 6227.611 seconds, including release, encrypted backup, restore and 20 independent cleanup inventories. The complete baseline repetition also passes; branch integration remains open. |
| Integrated branch CI | The inspected `5aedbe5` Security job still reports one critical finding in crypto 0.52.0 and exits 1. | Candidate has not been promoted; this is not accepted. |

The application-security suite retains TLS/header checks, CORS, CSRF, session
rotation, RBAC, rate limiting and the browser retry explanation. It checks the
actual services and logs, then removes its owned resources. The observed running
image ID is distinct from the later pilot build's image ID; the two complete
`caddy build-info` outputs have the same SHA-256:
`8926263bfafb78e0a19e154a0975894a67c82143bea51229bd13330da9eae5b9`.
This establishes matching reported build information, not identical image bytes.
Exact image identities and source hashes must accompany final acceptance.

## Direct scan of the running survey proxy

The exact proxy image observed in the running survey pilot is exported by its
immutable Docker identifier and scanned with the pinned Trivy 0.72.0 image.
The command exits zero after 36.947 seconds, reporting zero fixable critical
findings for both Alpine OS packages and `usr/bin/caddy`. Its policy remains
`--scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1`.
No VEX, ignore file or finding exception is supplied.

Docker reports an OCI index digest, while Trivy reports the selected image's
configuration digest. These identifiers are not interchangeable. The review
verifies the archive's index, selected arm64 manifest, configuration and all six
layer digests and lengths, then matches the configuration digest to Trivy's
reported image identity:

- Running OCI index: `sha256:1b9e618bd46aab97fd5a3d39ee468e49375e020012395a54a6d8f5439375a6fd`.
- Selected arm64 manifest: `sha256:a3db7e502e47897c7be516dc5a09f169ed28722b414c7ca8f67d7c1e88b316d0`.
- Image configuration / Trivy identity: `sha256:7efc1ae05a9cdd445c3011607cc5ba3f8b56e0e3e5af05bf12bfb9b8bca5588f`.
- Exported archive SHA-256: `c49e10dee7fc0f8bebd0bd25cb878f9b1b3477eb1e03007446551f0ccad03afc`.
- Scanner report SHA-256: `c504a66697c9d6fc609c429311a106f9cad97bb875f00b6fbd3fc425fe74aa2a`.

The scanner retains a database warning about unavailable vulnerability details
for CVE-2026-80256. The result is zero **reported fixable critical findings**,
not a claim that the image has no vulnerabilities. This direct scan closes the
identity gap between the running survey proxy and its scanned image; full
release/backup/restore, baseline repetition and integrated branch acceptance
remain separate requirements.

## Integration under test

Development Compose builds the corrected proxy. Production configuration rejects
live builds and unpinned proxy references. Release, upgrade and Restic recovery
paths bind the actual proxy image ID alongside the existing application images.
The pilot harness retains the original proxy tag for cleanup even after binding
the immutable ID. Its cleanup and preflight tests reject unreadable/occupied
inventories and failed removals; complete operator runs remain required.

Only the explicit 23-file candidate allowlist may be promoted. The newer main
worktree seed-test typing, route loading, UI synchronization/baseline, legacy
harness isolation and documentation changes must be preserved. The reviewed
Restic diff adds only the proxy to the immutable-image inventory; the reviewed
upgrade diff adds proxy builds and actual-image binding without replacing the
newer rollback/cleanup logic. Candidate and main runtime sources remain fixed
through their currently running or queued tests.

## Container-reference correction

The initial full pilot cached the proxy container ID before the manifest-bound
deploy. Compose then recreated the proxy, making that ID invalid for the next
Doctor container's network namespace. Docker returned exit 125 with a missing
container error. The baseline's cleanup and all 20 independent inventories
passed. The second mode was deliberately interrupted before repeating that
known common-path defect; it exited 1 after 68.092 seconds, with the same 20
cleanup inventories passing. Neither mode is accepted.

The candidate harness now resolves the running proxy's stable container name
and lets Docker resolve that name at each Doctor launch. A real isolated
Docker probe creates and replaces a container: the stale ID fails with exit
125, the stable name succeeds, and the owned probe container is removed.
The revised harness also passes 40 simulated preflight rejection cases and
45 simulated cleanup failure/residue cases, with a 25-operation successful
cleanup control. These bounded checks support the correction but do not replace
the queued complete baseline and survey pilot repetitions.

## Retry and Git revision isolation

The first corrected baseline repetition exits 1 after 972.622 seconds at the
negative manifest-drift assertion, before the operator deploy. All 20 independent
cleanup inventories pass. The test captures the rejected command output but
reports only that the expected image-drift message was absent; its original
underlying rejection text is unavailable.

The candidate directory inherits the main worktree's Git repository. Its
baseline source snapshot predates commit `5aedbe5`, which was created while the
baseline ran. The harness captures HEAD at startup, whereas the deployment
command reads HEAD again. A read-only reproduction using the actual manifest
validator proves that a changed expected commit rejects the same input with
`gitCommit weicht vom Checkout ab` before reaching the expected image-drift
check. This explains the observed failure as an inference from validation order
and commit timing; it does not recover the swallowed original error text.

The current survey repetition started after that commit and has now passed the
negative image-drift assertion, the real manifest-bound operator deployment and
its subsequent Doctor. The complete survey pilot then exits zero after
6227.611 seconds, with all 20 independent cleanup inventories passing. Candidate
sources and main Git HEAD remained fixed through the baseline-only repetition
`3397817358-83085`, which exits zero after 3344.392 seconds. Both runs verify
all 20 independent cleanup inventories, unchanged candidate source hashes and
the same Git HEAD before and after execution. No deployment safety assertion is weakened or bypassed.

The baseline-only repetition has now passed the manifest-bound operator deploy,
its Doctor and the complete operator release through `production_verified #4`.
Its encrypted snapshot `3b5e7195` contains five files (529.191 KiB); the full
integrity check reads one snapshot and two packs without errors. Migration,
service readiness, restored write access and the release Doctor pass. The
complete no-build restore preserves all four real data components, and final
independent cleanup confirms absence of every owned project, named backup
resource and all six release-image tags. This empty-erasure baseline does not
replace the nonempty survey recovery proof below.

## Completed survey pilot recovery

The corrected survey run completes the full operator release, including the
four expected promotion events bound to one manifest, explicit RustFS/Twenty/Core
migration, service readiness and the final Doctor. Its encrypted Restic snapshot
`33a8ebf0` contains five files (567.048 KiB); the integrity check reads all data
in one snapshot and two packs without errors.

After that backup, the run deletes survey content and retains a newer
authenticated, content-free deletion checkpoint. It then removes the complete
source Docker project, including its volumes and networks. Wrong restore
confirmation is rejected before source removal. The missing-checkpoint case
restores the old SQL answer and export object while application writers stay
offline; its private log confirms the missing checkpoint/cutoff rejection. A
second fresh restore rejects the occupied target. The test then interrupts
reapplication, resumes the authenticated quarantine without reimporting the
data, preserves a SQL control marker and starts the application. Actual HTTP
checks confirm that the old session and public route cannot retrieve the erased
survey or export. This first target is removed before the next case.

The tampered-checkpoint, wrong-key, wrong-installation and stale cases reject startup
after restoring the old SQL answer and export object offline. Their retained
logs report checkpoint/erasure verification failure, and the targets are
removed. The final valid restore reapplies the deletion checkpoint before
application startup; persisted relational content and the exact export object
version are absent, and both session and public access remain denied after
restart. Final cleanup succeeds for all four owned projects, named backup
resources and six image tags (20 independently read inventories). The final
survey proof has SHA-256
`a8162e3d4acf341ab6231a336748027aa70046f839ffcc7c6a5450e867bf8097`.
Source-project loss on this host does not establish independent physical
source-host loss; newest-checkpoint provenance and preceding-backup compatibility
remain separate open recovery requirements.

## Acceptance still required

- [x] Both complete candidate pilot modes exit zero and independently leave no
  owned containers, volumes, networks, backup resources or release-image tags.
- [x] Survey pilot evidence proves its real release/backup/restore assertions;
  baseline empty-erasure fixtures do not accept survey disaster recovery.
- [x] Promote exactly the reviewed 23 candidate files and preserve all 15 recorded newer main inputs.
- [ ] Verify integrated source, production configuration, actual image scan and
  SBOM selection in the required branch CI and affected regression gates.
- [ ] Attach exact source/image hashes, commands, exit codes and reviewed
  evidence before accepting 100.3i / 100.S2h.

Independent source-host loss remains a separate SURV-090 obligation. Passing
these image or pilot checks cannot accept that requirement or the full spike.

## Branch integration checkpoint

The exact reviewed files are now integrated. [Machine-readable evidence](assets/SURV-100-caddy-integration.json) records both complete candidate runs, promoted file hashes and preserved inputs. Local pin checks (24 images, 89 Python packages), the no-test-doubles policy and all seven gate-controller tests pass. Full branch CI and final repeated aggregate remain required before accepting 100.3i / 100.S2h.
