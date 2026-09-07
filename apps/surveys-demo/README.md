# Independent surveys consumer

This synthetic demo consumes a packed `@leonaid/surveys` artifact from `/artifact`
inside a clean `/consumer` container. It has no LeonAid source tree, workspace
resolution, API credentials or PostgreSQL connection. A minimal Bun/SQLite host
implements the participation adapter, with persisted version/answer snapshots,
revision checks, idempotent writes and terminal completion. Its fixed two-page
questionnaire has its own bounded server validation.

`package.template.json` becomes the external consumer's `package.json` during
the build; this folder is deliberately not a Bun workspace package. All direct
dependencies and the scheduler override use exact tested versions. The build
installs against `consumer.lock` with `--frozen-lockfile` and records the installed
lockfile; package publication and own OSS license
selection remain outside this spike.

The host uses English runner messages and its own green/brown theme. The test
must save, close the browser, restart the process with the same private SQLite
volume, restore and complete through the actual packed runner. Demo credentials
and browser state are ephemeral test artifacts. No host port is published.
The browser shares the demo container's private network namespace and uses
`localhost`, a browser secure context that supports `crypto.randomUUID()`.
Remote hosts must provide HTTPS; the demo does not weaken browser security.

The demo backend supports only its fixed synthetic questionnaire, not arbitrary
SurveyJS definitions, authoring/publication or a production participant service.
The broader package/editor and SSR acceptance remain separate work items.

## Independent export adapter

`/exports` consumes the packed `exports` entrypoint in a separate browser bundle.
The host offers response CSV only, using its own current-participation session,
SQLite export table, immutable captured response content and operation-ID replay.
It creates a small file synchronously and returns a completed job; this demo
does not reproduce LeonAid's background worker, other file formats or admin
permissions. The neutral component supports host-selected products and job states.

The browser proof creates/downloads the file, retries the identical operation
after a lost acknowledgement, then verifies job and download persistence after
the actual backend process restarts. An anonymous download is rejected. Separate
bundle inspection proves exports do not enter the respondent bundle and do not
import the SurveyJS renderer/editor. Host copy, filename and green theme remain
independent of LeonAid. Both desktop and mobile export views are exercised.
