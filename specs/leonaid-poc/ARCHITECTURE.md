# LeonAid PoC – verbindlicher Architekturindex

Stand: 2026-07-27

Dieses Dokument ist der kurze Einstieg in den implementierten Stand. Das
fachliche Zielbild bleibt der
[Produkt- und Architekturvorschlag](../produkt-und-architekturvorschlag.md).
Konkrete, bereits umgesetzte Entscheidungen stehen in den
[ADRs](decisions/).

## Laufzeitbild

| Baustein | Verantwortung | Persistenz |
| --- | --- | --- |
| Caddy | einziger veröffentlichter HTTP-/HTTPS-Einstieg | keine Fachdaten |
| Web | React-Portal für Charity- und System-Administration | keine Fachdaten |
| PWA | mobile Akquisiteur-Oberfläche und installierbare Shell | nur Browsercache, keine führenden Daten |
| Public Web | Astro-Aktionsseiten und öffentliche Standardformulare | keine führenden Daten |
| FastAPI Core | Authentifizierung, Policies und sämtliche Fachoperationen | Core PostgreSQL |
| Outbox-Worker | idempotente Dokument- und Mailjobs | Core PostgreSQL |
| Twenty | Firmen und Personen als CRM-System of Record | Twenty PostgreSQL und Dateien |
| RustFS | private, unveränderliche Dokumentbytes über S3-Port | RustFS-Volume |
| Mail-Relay | Zustellung von Login-, Einladungs- und Rechnungs-E-Mails | extern; lokal Mailpit |

Browser und Astro Actions besitzen keine maßgebliche Fachlogik. Web, PWA,
Public Web und eine spätere Tauri-App verwenden den generierten
`@leonaid/api-client`; FastAPI ist Owner des HTTP-Vertrags.

## Daten- und Transaktionsgrenzen

- Core PostgreSQL besitzt Identitäten, Aktionsmitgliedschaften,
  Charity-Aktionen, Zuordnungen, Aktivitäten, Bestellungen, Rechnungen,
  Dokumentmetadaten, Zahlungen, Audit und Outbox.
- Twenty besitzt Firmen und Personen. LeonAid speichert nur stabile
  Twenty-IDs und fachliche Snapshots, wo spätere Änderungen Historie nicht
  verändern dürfen.
- RustFS besitzt ausschließlich Dokumentbytes. Core PostgreSQL hält
  Object-Key, Version, SHA-256, Größe und Fachreferenzen.
- Rechnungsnummer, Rechnungssnapshot und Outbox-Ereignis entstehen in einer
  Core-Transaktion. Rendering und Versand sind idempotente Folgejobs.
- Eine Installation bildet einen Club beziehungsweise Träger ab.
  Mandantenfähigkeit entsteht durch getrennte Installationen.

Das versionierte Golden-Datenmodell steht unter
[`tests/fixtures/golden/v1`](../../tests/fixtures/golden/v1/README.md).
Core-Migrationen stehen unter [`migrations`](../../migrations/README.md);
das deklarative Twenty-Schema unter
[`infra/twenty`](../../infra/twenty/README.md).

## API- und Sicherheitsvertrag

- Der kanonische OpenAPI-Vertrag ist
  [`packages/api-client/openapi.json`](../../packages/api-client/openapi.json).
- Änderungen entstehen ausschließlich über FastAPI und
  `./leonaid generate-api-client`.
- Authentifizierung verwendet einmalige Magic Links oder Codes, absolute
  90-Tage-Sitzungen und Fresh Login für sensible Aktionen.
- Row-Level-Policies werden zentral im Core pro Request ausgewertet. Interne
  Rollen erhalten keinen direkten Twenty-Key.
- Der Twenty-Integrations-Key ist auf notwendige Objekte und Felder
  beschränkt.
- Browsergrenzen umfassen Secure-/HttpOnly-/SameSite-Cookies, CSRF-Schutz,
  CSP, TLS, Rate Limits und generische Auth-Antworten.
- Logs enthalten technische Korrelation, aber keine Payloads, Tokens,
  E-Mail-Adressen oder Dokumentbytes.

Der aktuelle Rollenvertrag steht in [`PERSONAS.md`](../../PERSONAS.md).
Security-, Betriebs- und Recoveryentscheidungen sind in
[`DECISIONS.md`](DECISIONS.md) und den ADRs nachvollziehbar.

## Verbindliche Entscheidungen

| Thema | Entscheidung |
| --- | --- |
| PoC-Scope und Beweis | [ADR-0001](decisions/ADR-0001-poc-scope.md), [ADR-0002](decisions/ADR-0002-proof-and-delivery.md) |
| Core- und API-Grenze | [ADR-0003](decisions/ADR-0003-core-architecture.md) |
| Rechnung und Typst | [ADR-0004](decisions/ADR-0004-invoice-issuing.md), [ADR-0005](decisions/ADR-0005-typst-invoice-renderer.md) |
| Dokumente und S3 | [ADR-0006](decisions/ADR-0006-provider-neutral-object-storage.md), [ADR-0007](decisions/ADR-0007-contextual-document-access.md) |
| Mail und Zahlung | [ADR-0008](decisions/ADR-0008-durable-invoice-delivery.md), [ADR-0009](decisions/ADR-0009-exact-invoice-settlement.md) |
| Feature Flags | [ADR-0010](decisions/ADR-0010-openfeature-rollout-controls.md) |
| Recovery und Upgrade | [ADR-0011](decisions/ADR-0011-encrypted-cross-system-backups.md), [ADR-0012](decisions/ADR-0012-pinned-upgrades-and-backup-rollback.md) |
| Betriebssignale | [ADR-0013](decisions/ADR-0013-operational-signals-and-safe-retry.md) |

## Änderungsregel

Eine Änderung an Datenhoheit, Transaktionsgrenze, Authentifizierung,
Autorisierung, externem System oder öffentlichem Vertrag benötigt:

1. einen aktualisierten Eintrag in `DECISIONS.md`;
2. bei dauerhafter Architekturwirkung eine neue oder ersetzende ADR;
3. aktualisierte OpenAPI-, Golden- und Policy-Verträge;
4. einen realen Integration- oder E2E-Nachweis ohne Mocks.
