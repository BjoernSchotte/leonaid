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
