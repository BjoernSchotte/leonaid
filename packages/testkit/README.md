# LeonAid Testkit

Das Testkit prüft den PoC ausschließlich gegen reale, frisch gestartete
Systeme. Es enthält schmale Clients für:

- LeonAid/FastAPI einschließlich echtem Magic-Link-Login,
- Twenty über die unterstützte REST Data API,
- RustFS über die S3-API,
- Mailpit über SMTP und die HTTP-API,
- PostgreSQL in explizit read-only ausgeführten Transaktionen.

Alle Clients erhalten einen `TestContext`. Dadurch nennen Fehler immer
Request-ID, Persona, Charity-Aktion und Golden-Dataset. Asynchrone Zustände
werden über `poll_until` anhand eines fachlichen Zielzustands und einer
Deadline geprüft; pauschale Sleeps sind außerhalb dieses Pollers nicht
zulässig.

Der vollständige Echt-System-Smoke-Test läuft Docker-basiert:

```sh
./leonaid test-testkit
```

Die dabei erzeugte Persona-Sitzung stammt aus dem echten Login-Prozess. Der
Browser liest denselben Sponsor wie API und Twenty und vergleicht die
Twenty-ID. Zusätzlich versendet der Test eine reale SMTP-Mail an Mailpit und
führt einen RustFS-Schreib-/Lesezyklus mit SHA-256-Prüfung aus.
