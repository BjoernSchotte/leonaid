# `@leonaid/api-client`

Host-neutral TypeScript client for the LeonAid Core API.

- `openapi.json` is generated directly from FastAPI.
- `src/generated.ts` is generated deterministically from this contract.
- `src/index.ts` is the only import path for web, PWA, Public Web and a later
  Tauri app.

Both generated files are committed. Manual changes are not allowed;
`tools/openapi/generate.py --check` detects drift.

The generator supports the required JSON request bodies, required path
parameters and typed scalar query parameters used in the PoC. Path and query
values are URL-encoded, Content-Type headers are merged with call options, and
unsupported OpenAPI shapes are still rejected explicitly.

Since POC-042, the contract also contains login request and completion,
fresh-login status and completion, logout and administrative session
revocation. The session token itself stays only in the `HttpOnly` cookie and is
therefore not a value of the TypeScript client.

Since POC-043, the contract covers the server-side scoped acquisition
endpoints for list, count, CSV export, detail, activities and document
metadata. The client sends no actor, role or assignee ID; the Core session is
the only source of identity.

Since POC-050, the contract also covers creating and reading neutral charity
actions and typed changes to goal, capabilities, beneficiaries and lifecycle.
Decimal values are transferred losslessly as canonical strings. Writes stay
bound on the server side to a fresh session and the central action
permission.
