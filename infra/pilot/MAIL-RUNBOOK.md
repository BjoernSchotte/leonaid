# Produktiver Mailtransport

LeonAid versendet transaktionale Nachrichten providerneutral über SMTP. Die
Providerwahl, Domainfreigabe und realen Zugangsdaten bleiben private
Pilotentscheidungen; Mailpit ist ausschließlich Entwicklungs- und
Testinfrastruktur.

## Konfigurationsgrenze

Die API erhält nur `MAIL_HEALTH_URL`. SMTP-Host, Absender, Transportmodus und
Zugangsdaten werden ausschließlich in den Worker injiziert. Eine befüllte
Kopie von `mail.env.example`, Providerverträge, Zugangsdaten und
Testpostfach-Inhalte dürfen weder in Git noch in öffentliche CI-Artefakte
gelangen.

Unterstützte Modi:

- `starttls`: Verbindung wird nach `EHLO` verpflichtend auf TLS angehoben;
- `tls`: TLS besteht ab Verbindungsaufbau;
- `plain`: nur für lokale/isolierte Tests, in Produktion abgewiesen.

In Produktion ist Zertifikatsprüfung zwingend. Eine private CA kann als
Worker-only-Datei gemountet und über `MAIL_SMTP_CA_FILE` referenziert werden.
Benutzername und Passwort müssen gemeinsam gesetzt oder gemeinsam leer sein.

## Freigabe

Vor dem produktiven Versand müssen erledigt und privat belegt sein:

1. Relay, Domain-Owner und kontrolliertes Testpostfach ausgewählt;
2. SPF, DKIM und DMARC beim produktiven DNS geprüft;
3. STARTTLS oder implizites TLS samt Zertifikatsprüfung erfolgreich;
4. Login, Einladung, E-Mail-Korrektur und Rechnung im Provider-Sandbox- oder
   Testmodus zugestellt;
5. Provider-Limits, Bounce-/Abuse-Weg, Alarmierung und Incident-Owner
   festgelegt;
6. keine Adresse, kein Token, kein Providertext und kein Mailinhalt in Logs
   oder öffentlichen Evidence-Dateien.

`./leonaid test-mail-relay` beweist lokal mit gepinnten realen Diensten
STARTTLS, Authentifizierung, Zertifikatsfehler, Timeout, Provider-Limit und
einen exakt einmal angenommenen Retry. Dieser Vertrag ersetzt nicht den
separaten realen Provider-Nachweis.

## Betrieb und Störung

Die Core-Readiness hängt nicht vom Relay ab: Akquise, Aktionen und
Dokumentzugriff bleiben bei Mailausfall verfügbar. Die Operations-Ansicht
meldet den Mailweg separat als degradiert; Outbox-Ereignisse bleiben
dauerhaft erhalten und können nach Behebung sicher erneut verarbeitet
werden.

Fehlercodes sind bewusst provider- und personenbezugsfrei:

- `mail_authentication_failed`
- `mail_certificate_invalid`
- `mail_timeout`
- `mail_provider_limited`
- `mail_temporary_rejection`
- `mail_permanent_rejection`
- `mail_recipient_rejected`
- `mail_transport_unsupported`
- `mail_tls_failed`
- `mail_protocol_failed`
- `mail_unavailable`

Bei Auth- oder Zertifikatsfehlern werden zuerst Secret-/Zertifikats-Rotation
und Providerstatus geprüft. Bei temporären Limits oder Timeouts bleibt der
Outbox-Retry aktiv. Ein fachlich bewusster Neuversand einer bereits
zugestellten Rechnung ist von einem technischen Retry getrennt.
