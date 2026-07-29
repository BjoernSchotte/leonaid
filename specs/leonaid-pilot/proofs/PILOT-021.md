# PILOT-021 – Technischer Mail-Domain- und Betriebsnachweis

Task-ID: `PILOT-021`

Nachweisdatum: 29. Juli 2026

Status: technische Basis bewiesen, externe Freigabe offen

## Ergebnis

LeonAid besitzt jetzt einen fail-closed Vertrag für die produktiven
Mailidentitäten und die öffentliche Domainzustellung:

- sichtbarer Absender, SMTP-Envelope-From und Reply-To sind getrennte,
  Worker-only Produktionswerte;
- Produktion startet ohne explizites Envelope-From und Reply-To nicht;
- jede Nachricht muss exakt den konfigurierten sichtbaren Absender und
  Reply-To tragen; ein abweichender Wert wird terminal abgewiesen;
- das Envelope-From wird separat im SMTP-Befehl übergeben;
- der empfangende reale Testserver bestätigt From, Reply-To, Return-Path und
  Message-ID für Plain SMTP, STARTTLS und implizites TLS;
- ein neuer DNS-Gate prüft bestätigte Identitäten, SPF, aktiven DKIM-Schlüssel
  und DMARC über einen echten öffentlichen Resolver;
- sein öffentlicher Report enthält weder Mailadressen noch DNS-TXT-Inhalte;
- Login, Fresh Login, Einladung und Rechnung besitzen unterschiedliche,
  verständliche Betreffe und Texte sowie einen betreuten Antwort-Hinweis;
- der Rechnungsvertrag prüft Reply-To, Message-ID, Text, MIME und den
  byteidentischen SHA-256 des Typst-PDF;
- das Mail-Runbook beschreibt Domainfreigabe, technische und fachliche
  Fehlerklassen, sicheren Retry, Bounce/Complaint, Secret- und DKIM-Rotation,
  Provider-Ausfall und kontrollierte Rückkehr.

Die Produktionsvorlagen und die produktionsnahe Compose-Topologie verlangen
`MAIL_FROM`, `MAIL_ENVELOPE_FROM` und `MAIL_REPLY_TO`. API und Browser erhalten
diese Werte nicht.

## Automatische Nachweise

```sh
./leonaid test-unit
./leonaid test-mail-domain
./leonaid test-mail-relay
./leonaid test-sessions
./leonaid test-invitations
./leonaid test-invoice-delivery
./leonaid test-pilot-deployment
/bin/sh tools/ci/lint-types.sh
```

Ergebnis:

```text
201 passed
mail-domain-test: OK: real public DNS resolver, aligned identities,
SPF, active DKIM, DMARC, privacy and four fail-closed mutations proven
mail-relay-test: OK: Plain-SMTP, STARTTLS/TLS/Auth, Zertifikat,
Provider-Limit, Timeout und exakt-einmal Retry bewiesen
2 passed in Chromium
session-test: OK: Login, 90 Tage, Fresh Login und Widerruf real bewiesen
6 passed in Chromium
invitation-test: OK: Berechtigung, Link/Code und echte Mailzustellung bewiesen
1 passed in Chromium
invoice-delivery-test: OK: echter SMTP-Ausfall, sichtbarer Retry,
MIME/PDF-Hash und bewusster Neuversand bewiesen
pilot-deployment-test: OK: Contract, Leerstart und realer Deployment Doctor
bewiesen
ci-lint-types: OK
```

Der öffentliche DNS-Smoke verwendet eine reale, fremdverwaltete Domain und
prüft dieselbe Antwort zweimal auf einen reproduzierbaren sanitizten Report.
Zusätzlich werden die realen Antworten deterministisch so verändert, dass
falsche DMARC-Policy, fehlender SPF-Term, widerrufener DKIM-Schlüssel und ein
fehlgerichteter sichtbarer Absender jeweils fail-closed blockieren. Die
tatsächliche Pilotdomain wird später mit einer privaten Erwartungsdatei über
denselben Befehl geprüft:

```sh
./leonaid mail-domain-check \
  --expectation /etc/leonaid/mail-domain.expected.json \
  --report /var/lib/leonaid/evidence/mail-domain-readiness.json
```

Der automatisierte Wrapper-Nachweis liest die Erwartung über einen expliziten
read-only Host-Pfad, schreibt den sanitizten Report an den angeforderten
Host-Pfad zurück und bestätigt Dateimodus `0600`.

## Reale Daten- und Systemgrenze

Die automatischen Verträge verwenden ausschließlich synthetische
`*.invalid`-Empfänger und frisch gestartete gepinnte Dienste. Es wurden weder
die laufende lokale Mailbox noch reale Postfachinhalte, Tokens oder
Providerzugänge gelesen. Private Erwartungsdatei, reale Adressen,
Providerberichte und manuelle Zustellnachweise gehören ausschließlich in den
privaten Pilot-Evidence-Store.

## Docker-Ressourcen

Die ausgeführten Verträge verwendeten die Projekte
`leonaid-pilot020-test`, `leonaid-poc041-test`, `leonaid-poc042-test`,
`leonaid-poc094-test` und `leonaid-pilot040-test`. Nach Abschluss bestätigte
die Inventur für jedes Projekt jeweils null Container, Netze und Volumes.
Der Mail-Relay-Vertrag entfernt zusätzlich sein lokal gebautes Testimage.
Der kanonische Entwicklungsstack blieb erhalten.

## Offene formale Gates

`PILOT-021` bleibt formal offen:

- Pilotdomain, sichtbarer Absender, Envelope-From und Reply-To sind noch nicht
  fachlich bestätigt.
- Der reale Provider und dessen SPF-Term, DKIM-Selector,
  Bounce-/Complaint-Klassen und Eskalationsweg sind noch nicht ausgewählt
  beziehungsweise privat belegt.
- Eine primäre Mail-Operatorin oder ein primärer Mail-Operator sowie
  Vertretung sind noch nicht namentlich im privaten Entscheidungsprotokoll
  bestätigt.
- Magic Link, Code, Einladung und Rechnung wurden noch nicht an kontrollierte
  externe Postfächer versendet.
- Der manuelle Zustellbarkeitssmoke bei zwei unterschiedlichen Mailanbietern
  fehlt.
- Die Abhängigkeit `PILOT-020` bleibt wegen der noch offenen realen
  Providerfreigabe formal offen.

Diese externen Kriterien werden nicht durch den öffentlichen DNS-Smoke oder
lokale Mailpit-Zustellung ersetzt.
