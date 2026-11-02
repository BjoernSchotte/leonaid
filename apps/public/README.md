# Public Web

Server-rendered public Astro action pages and the passwordless entry points for
members.

POC-041 provides a responsive activation page under `/invite` for magic link
and six-digit code. To protect against mail scanners, a link never runs a
writing action automatically: the token is removed from the visible URL and
sent to the Core API only after explicit confirmation. Successful completion
activates the account and the action role and immediately starts a secure
90-day session.

POC-042 adds passwordless member login under `/login` by magic link or
six-digit code. The response does not reveal whether an email is registered.
`/fresh-login` confirms sensitive actions again, removes magic-link tokens from
the visible URL before confirmation and then leads only to a checked internal
return target.

POC-071 delivers the public action presentation for alias and archive
addresses. Astro queries only the FastAPI Core through the generated client.
The business decision about publication, archive and public offers stays
entirely in the Core. Action pages contain no client JavaScript; fonts and
images are served locally.

The public order form follows in POC-072. Its Astro Action may validate
transport data, record spam signals and forward to the Core. Prices,
availability, order windows and all other business rules are decided again
there.
