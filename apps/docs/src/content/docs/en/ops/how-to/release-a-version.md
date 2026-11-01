---
title: Release a version
description: Cut a CalVer release that publishes digest-pinned images and a release manifest.
docId: DOC-P038
audience: [ops, dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 86b4e396de4569cbc7dbd03cdb2153a8698bb0d1
reviewer: Björn Schotte
---

LeonAid versions use CalVer. A release is `vYYYY.M.N`: the UTC year and month
without a leading zero, and `N` counting the releases in that month from 1. A
fix release is `vYYYY.M.N.P` on top of exactly one release. Tags are annotated
and are never moved, deleted or reused.

## Release from main

1. Merge everything for the release into `main`, pull it and wait until CI on
   the last commit is green.
2. Run `./leonaid release --dry-run`. It shows the next version and the notes
   grouped from the Conventional Commits since the previous release.
3. Run `./leonaid release`. It checks a clean tree, that `HEAD` equals
   `origin/main`, green CI and a `gh` login, then pushes the tag.
4. The tag starts the `Release` workflow. It builds the six LeonAid images,
   pushes them to `ghcr.io/<owner>/leonaid/<name>:<version>` and publishes the
   GitHub release with three files:
   - `release-images.env`: the version, the commit and the six image
     references with tag and digest;
   - `release-manifest.json`: the production release manifest;
   - `SHA256SUMS` for both files.

The workflow refuses to overwrite images that already exist for a version.

## Fix release

1. Land the fix on `main` first through a pull request.
2. Create the release branch once from its tag:
   `git switch -c release/2026.11.1 v2026.11.1`.
3. Apply the fix with `git cherry-pick -x <commit>` and push the branch.
4. Run `./leonaid release` on the branch. The result is `v2026.11.1.1`. Fix
   releases are not marked as the latest GitHub release.

## Resume a stopped release

If the tag exists but the GitHub release is missing, run `./leonaid release`
again on the tagged commit. It pushes the tag again and starts the workflow
for it; it never creates a second tag.

## Deploy the release

Copy the lines of `release-images.env` unchanged into the private environment
file and continue with
[Deploy a pilot installation](/en/ops/how-to/deploy-pilot/) using
`release-manifest.json`.
