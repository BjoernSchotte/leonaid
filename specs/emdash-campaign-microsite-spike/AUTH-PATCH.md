# Pinned external-identity seam

Scope: EmDash 0.36.0, reviewed source commit
`603062902369d9695608e85c2d034d4f66f7a1f1`.

`apps/campaign-site/emdash-auth-patch.mjs` transforms the installed
`emdash/middleware/auth` module during this application's build. The complete
module SHA-256 must match
`37ca9a59ddebdce5cf597e7115dd2684e74ed131b4a9151a5b6ab37c5f822094`;
both insertion anchors must occur exactly once. The build fails if the transform
is skipped. No dependency files are edited and no middleware copy is maintained.

For the `leonaid-core` provider only, the inserted branch resolves the CMS user
ID produced by the transactionally persisted Core UUID mapping. It rejects a
missing, disabled or concurrently changed profile. It bypasses upstream email
lookup, first-user promotion and local session creation. Errors are sanitized;
no external identity profile is logged. Other providers retain upstream behavior
but are not configured by this application.

The outer guard validates Core before EmDash initialization, then the external
adapter validates Core again inside upstream middleware. There is deliberately
no identity cache. Bearer headers and development-mode fallback are refused.
Only GET `/_emdash/api/auth/me` is currently admitted, for Core System Admins.
Editor, non-setup mutations, public previews and all other CMS paths remain closed.
The later `BOOTSTRAP.md` gate separately admits one operator-authorized setup
attempt through verified Core identity and the configured HTTPS origin.
This is not proof of browser SSO or campaign authorization.

Verification: `./leonaid test-emdash-spike --case auth-runtime` uses the actual
production image, Core HTTP and PostgreSQL. The source-integrity proof uses
the installed module and rejects byte drift, semantic drift and double patching.
No authentication adapter or HTTP service is replaced with a test double.

Upgrade procedure: review the new upstream source and its callers, reassess the
need for the seam, update its hash and anchors explicitly, then repeat integrity,
production HTTP and all later browser/authorization gates. Never update the hash
solely to make a failing build pass. A broader fork remains a STOP condition.

An upstream extension proposal is still pending; this document is local patch
provenance, not evidence that a proposal was submitted or accepted.
