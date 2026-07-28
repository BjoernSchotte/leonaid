# PILOT-020 – Providerneutraler produktiver Mail-Adapter

Task-ID: `PILOT-020`

Nachweisdatum: 28. Juli 2026

Status: technische Basis bewiesen, externe Providerfreigabe offen

## Ergebnis

Login, Einladungen und Rechnungen laufen über eine gemeinsame
providerneutrale SMTP-Schicht im Worker. Der Produktcode verwendet nur noch
generische `MAIL_*`-Namen:

- `plain`, `starttls` und implizites `tls` sind getrennte Transportmodi;
- Authentifizierung, Timeout, Zertifikatsprüfung und optionale private CA
  sind typisiert;
- Produktion lehnt Klartext-SMTP und abgeschaltete Zertifikatsprüfung schon
  beim Konfigurationsstart ab;
- API und Worker erhalten getrennte Konfiguration: Die API kennt nur den
  nicht geheimen Health-Endpunkt, SMTP-Secrets ausschließlich der Worker;
- allgemeine Nachrichten und Rechnungen verwenden dieselbe
  `SmtpTransport`-Instanz;
- Rechnungs-PDF, Message-ID, Idempotenzledger, Retry und bewusster Neuversand
  bleiben unverändert;
- Providerantworten, Empfänger, Betreff, Inhalt und Zugangsdaten gelangen
  nicht in Fehlercodes oder strukturierte Logs;
- nicht wiederholbare Auth-/Zertifikatsfehler gehen unmittelbar ins Dead
  Letter, temporäre Limits und Timeouts bleiben wiederholbar.

Mailpit bleibt unter dem expliziten Profil `dev-mail`. Das zusätzliche Profil
`mail-contract` startet ausschließlich isolierte, gepinnte reale
Testdienste. Produktionsvorlage und Betriebsanleitung liegen unter
`infra/pilot/`.

## Automatische Nachweise

```sh
./leonaid test-unit
./leonaid test-mail-relay
./leonaid test-invitations
./leonaid test-sessions
./leonaid test-invoice-delivery
/bin/sh tools/ci/lint-types.sh
```

Ergebnis:

```text
181 passed
mail-relay-test: OK: Plain-SMTP, STARTTLS/TLS/Auth, Zertifikat,
Provider-Limit, Timeout und exakt-einmal Retry bewiesen
3 passed in Chromium
invitation-test: OK: Berechtigung, Link/Code und echte Mailzustellung bewiesen
2 passed in Chromium
session-test: OK: Login, 90 Tage, Fresh Login und Widerruf real bewiesen
1 passed in Chromium
invoice-delivery-test: OK: echter SMTP-Ausfall, sichtbarer Retry,
MIME/PDF-Hash und bewusster Neuversand bewiesen
ci-lint-types: OK
```

Der neue Mailvertrag verwendet keine Test-Doubles:

1. normales Mailpit nimmt den erfolgreichen Plain-SMTP-Retry an;
2. ein zweites Mailpit verlangt STARTTLS und echte SMTP-Authentifizierung;
3. ein drittes Mailpit verlangt implizites TLS ab Verbindungsaufbau;
4. das Self-signed-Zertifikat erzeugt bei aktiver Prüfung einen realen
   Zertifikatsfehler;
5. falsche Zugangsdaten erzeugen einen realen SMTP-Authfehler;
6. Mailpit Chaos weist den ersten Zustellversuch mit SMTP `452` ab;
7. ein gepinnter Alpine-TCP-Dienst nimmt die Verbindung an, antwortet aber
   nicht und erzeugt einen echten Timeout;
8. nach dem abgewiesenen Erstversuch wird dieselbe Message-ID genau einmal
   vom gesunden Server angenommen.

## Sichtbarer In-App-Browser-Nachweis

In der kanonischen Entwicklungsinstanz zeigte die Seite „System & Betrieb“
zunächst `3/3 Dienste bereit` und E-Mail `Bereit`. Nach dem realen Stoppen
von Mailpit blieb das Portal bedienbar und zeigte nach „Aktualisieren“
`2/3 Dienste bereit`, während CRM und Dateiablage bereit blieben und nur
E-Mail als `Nicht erreichbar` markiert wurde. Nach dem Wiederstart und einem
weiteren sichtbaren Refresh war E-Mail erneut `Bereit` und der Gesamtstatus
`3/3 Dienste bereit`.

Damit ist die Trennung zwischen fachkritischem Core und degradierter
Mailzustellung sichtbar belegt.

## Docker-Ressourcen

Der neue Vertrag verwendet das Compose-Projekt `leonaid-pilot020-test`.
Nach dem erfolgreichen Lauf bestätigte die Inventur jeweils null Container,
Netze und Volumes mit diesem Projektlabel. Auch die bestehenden Projekte
`leonaid-poc041-test`, `leonaid-poc042-test` und `leonaid-poc094-test`
werden durch ihre Test-Traps vollständig entfernt. Der kanonische
Entwicklungsstack blieb erhalten; sein kurz gestopptes Mailpit wurde
anschließend wieder gesund gestartet.

## Offene formale Gates

PILOT-020 bleibt formal offen:

- Der reale produktive Relay ist in `PILOT-001` noch nicht ausgewählt.
- Deshalb können Transportmodus und Zugangsdaten des ausgewählten Providers
  sowie dessen offizieller Sandbox-/Testmodus noch nicht belegt werden.
- Der providerneutrale Pending-Change-Workflow zur E-Mail-Korrektur ist
  inzwischen unter `PILOT-013` technisch gegen denselben Outbox-Pfad
  bewiesen. Sein produktiver Abschluss bleibt von der hier noch offenen
  Providerkonfiguration und dem externen Zustelllauf abhängig.
- Die Abhängigkeiten `PILOT-001` und `PILOT-002` sind formal offen.

Diese externen beziehungsweise nachgelagerten Kriterien werden nicht durch
einen verfrühten Task-Haken ersetzt.
