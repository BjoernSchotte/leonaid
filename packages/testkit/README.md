# LeonAid Testkit

The testkit checks the PoC only against real, freshly started systems. It
contains thin clients for:

- LeonAid/FastAPI, including real magic-link login,
- Twenty through the supported REST Data API,
- RustFS through the S3 API,
- Mailpit through SMTP and the HTTP API,
- PostgreSQL in transactions that run explicitly read-only.

All clients receive a `TestContext`. This way, errors always name the request
ID, persona, charity action and golden dataset. Asynchronous states are checked
with `poll_until` against a business target state and a deadline; blanket
sleeps are not allowed outside this poller.

The complete real-system smoke test runs on Docker:

```sh
./leonaid test-testkit
```

The persona session it creates comes from the real login process. The browser
reads the same sponsor as the API and Twenty and compares the Twenty ID. The
test also sends a real SMTP mail to Mailpit and runs a RustFS write/read cycle
with a SHA-256 check.
