# LeonAid documentation authoring

The documentation is bilingual German/English and organized by audience and
Diátaxis. The implementation is always the source of truth. Existing specs,
READMEs, and proofs locate intent and history; verify every behavioral claim
against the current code path and an executable contract before publishing it.

## Authoring workflow

1. Pick a page ID from
   `specs/multilingual-documentation/CONTENT-INVENTORY.md`.
2. Copy the matching template from `apps/docs/templates/` into the same
   relative path below both `de/` and `en/`.
3. Write or update German first. Increase `contentRevision` for a factual
   source change, then translate and set both `reviewedRevision` values to the
   same number after review.
4. Set `verifiedAgainst` to the full product commit that was inspected and
   tested. Formatting-only edits do not change the content revision.
5. Run `./leonaid docs-check`, `./leonaid docs-build`, and the relevant product
   contract. Preview the built result with `./leonaid docs-preview`.
6. Record fachliches review and language review in the inventory. A generated
   green build cannot approve meaning.

## Content rules

- Tutorials teach one reproducible path with synthetic data.
- How-to guides solve one concrete task and state role, prerequisites,
  observable success, diagnosis, and recovery where needed.
- Reference pages enumerate the implemented contract. Explanation pages show
  why its parts relate.
- Use actual UI labels and command names. Do not translate a label that the
  product does not translate.
- Keep links inside the current locale. The homepage language links are the
  only editorial cross-locale exception.
- Set `draft: true`, `pagefind: false`, and `sidebar.hidden: true` for work that
  must remain unpublished. Drafts cannot satisfy an inventory entry.
- Screenshots may contain only approved synthetic data and must include useful
  alt text. Never publish sessions, codes, secrets, `.local` content, or
  customer data.

## Commands

```sh
./leonaid docs-dev
./leonaid docs-check
./leonaid docs-build
./leonaid docs-preview
./leonaid test-docs
```

The first four commands use the locked Bun container. `docs-check` also proves
that the checked-in OpenAPI contract matches the current Core generator.
`test-docs` serves the exact production build and checks its manifest, German
and English navigation, language switch, search, keyboard path, responsive
layouts, and accessibility in the locked Playwright container. Set
`LEONAID_DOCS_BASE_URL=http://host.docker.internal:4321` to reuse an already
running `docs-preview` process.

Every build writes `apps/docs/dist/build-manifest.json` with the source SHA,
build time, artifact ID, documented product revisions, content hash, and
OpenAPI hash. Only the allowlisted static site files may be uploaded.

`bun run --filter @leonaid/docs generate:api` reads the checked-in
`packages/api-client/openapi.json` contract and writes the stable, sorted
reference model to the ignored `apps/docs/src/generated/` directory. The
German and English API entry pages add curated context around that same model;
they do not maintain a second API contract.

`bun run --filter @leonaid/docs check:external` performs the networked nightly
external-link check. It retries timeouts, HTTP 408/425/429, and 5xx responses;
remaining temporary failures are reported separately from permanent 4xx
failures.
