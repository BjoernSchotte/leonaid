# Produktiver Mailtransport

LeonAid versendet transaktionale Nachrichten providerneutral über SMTP. Die
Providerwahl, Domainfreigabe und realen Zugangsdaten bleiben private
Pilotentscheidungen; Mailpit ist ausschließlich Entwicklungs- und
Testinfrastruktur.

## Konfigurationsgrenze

Die API erhält nur `MAIL_HEALTH_URL`. SMTP-Host, sichtbarer Absender,
Envelope-From, Reply-To, Transportmodus und Zugangsdaten werden ausschließlich
in den Worker injiziert. Eine befüllte
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
In Produktion sind außerdem alle drei Versandidentitäten explizit:

- `MAIL_FROM`: sichtbarer Absender in der Nachricht;
- `MAIL_ENVELOPE_FROM`: technische Rücklaufadresse für Bounces;
- `MAIL_REPLY_TO`: betreuter Antwortweg für Rückfragen.

Der Transport weist Nachrichten mit einem abweichenden sichtbaren Absender
oder Reply-To terminal ab und übergibt das Envelope-From separat an SMTP.
Login, Fresh Login, Einladung und Rechnung nennen im Text, dass Rückfragen
durch eine Antwort auf die Nachricht den betreuten Reply-To-Weg erreichen.

## Domainfreigabe

Die bestätigte private Erwartung wird außerhalb des Repositorys aus
`mail-domain.expected.example.json` abgeleitet. Vor Staging, nach jeder
DNS-/Provideränderung und vor Produktionsfreigabe:

```sh
./leonaid mail-domain-check \
  --expectation /etc/leonaid/mail-domain.expected.json \
  --report /var/lib/leonaid/evidence/mail-domain-readiness.json
```

Der Check fragt einen realen öffentlichen Resolver ab und blockiert bei:

- nicht zur bestätigten Domain ausgerichtetem Envelope-From, From oder
  Reply-To;
- fehlendem, mehrfachem oder unvollständigem SPF;
- fehlendem, widerrufenem oder unerwartetem DKIM-Schlüssel;
- fehlendem DMARC, falscher Policy oder weniger als 100 Prozent Abdeckung.

Der Report enthält keine Mailadressen und keine DNS-TXT-Inhalte, sondern nur
Domain, Selector, boolesche Ergebnisse, Zähler und SHA-256-Fingerprints.
`./leonaid test-mail-domain` beweist den Vertrag in CI an einer öffentlichen,
nicht von LeonAid kontrollierten DNS-Fixture und mit vier fail-closed
Mutationen. Der CI-Nachweis ersetzt nicht den privaten Lauf gegen die
tatsächliche Pilotdomain.

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
7. sichtbarer From, Reply-To, Envelope-From und Message-ID beim empfangenden
   System kontrolliert;
8. mindestens je ein kontrolliertes Postfach bei zwei unterschiedlichen
   Mailanbietern empfängt Magic Link/Code, Einladung und Rechnung; Ergebnis,
   Zeitpunkt und Anbieter werden nur privat belegt.

`./leonaid test-mail-relay` beweist lokal mit gepinnten realen Diensten
STARTTLS, Authentifizierung, Zertifikatsfehler, Timeout, Provider-Limit und
einen exakt einmal angenommenen Retry. Dieser Vertrag ersetzt nicht den
separaten realen Provider-Nachweis.

## Verantwortung und Zustellfehler

Vor Freigabe werden im privaten Entscheidungsprotokoll eine primäre
Mail-Operatorin oder ein primärer Mail-Operator sowie eine Vertretung
namentlich bestätigt. Im Repository stehen absichtlich keine privaten Namen.
Diese Rolle:

1. beobachtet Providerstatus, LeonAid-Operations und Dead Letter Queue;
2. korreliert einen Fehler ausschließlich über Zeitfenster, sicheren
   Fehlercode, Ereignistyp und interne ID;
3. prüft vor einem Retry, ob der Provider die Nachricht bereits angenommen
   hat;
4. startet nur das ausgewählte fehlgeschlagene Ereignis erneut;
5. informiert Betroffene bei Bedarf über einen zuvor autorisierten
   alternativen Kanal, ohne Magic Link, Code, Rechnung oder Mailinhalt in
   Tickets zu kopieren;
6. dokumentiert Entscheidung und Ergebnis im privaten Pilot-Evidence-Store.

Temporäre `4xx`, Limits, Timeouts und Verbindungsfehler dürfen bis zum
konfigurierten Outbox-Maximum automatisch wiederholt werden. Danach bleiben
sie sichtbar im Dead Letter. Permanente Empfängerablehnung, Authentifizierungs-
und Zertifikatsfehler sind terminal und werden nicht automatisch endlos
wiederholt.

Provider-Bounces und Complaints werden bis zu einer späteren
Webhook-Integration im geschützten Provider-Portal durch die benannte Rolle
bearbeitet. Ein Hard Bounce oder eine Complaint führt zu keinem manuellen
Blind-Retry. Zuerst werden Ursache, Einwilligung beziehungsweise fachlich
gültiger Kontaktweg geklärt. Provider-spezifische Bounce-Klassen,
Complaint-Kanal, Aufbewahrung und Reaktionsfrist werden im privaten
Providerentscheid ergänzt; ohne diesen Nachweis bleibt die produktive
Mailfreigabe offen.

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

## Rotation

### SMTP-Zugang

1. neues Secret beim Provider anlegen, bisheriges noch nicht widerrufen;
2. Worker-only Secret Store aktualisieren;
3. Worker kontrolliert neu starten und Readiness prüfen;
4. synthetischen Login und eine kontrollierte Rechnung zustellen;
5. erst danach altes Secret widerrufen und Evidence privat ablegen.

### DKIM

1. neuen Selector parallel publizieren;
2. `mail-domain-check` mit dem neuen Selector grün ausführen;
3. Provider-Signierung auf den neuen Selector umstellen;
4. Zustellung und DKIM-Ergebnis bei beiden Testanbietern prüfen;
5. alten Selector erst nach dem vereinbarten Überlappungsfenster entfernen.

Änderungen an From, Envelope-From, Reply-To, SPF oder DMARC werden zuerst bei
Domain-Owner und Provider vorbereitet, anschließend öffentlich geprüft und
erst dann in den Worker übernommen. Ein DNS- oder Identitätswechsel ohne
grünen Check ist ein STOP.

## Provider-Ausfall und Rückkehr

Bei einem Ausfall bleiben Core, Dokumente und Akquise verfügbar. Der Operator:

1. bestätigt Auswirkung über Providerstatus, Operations und sichere
   Fehlercodes;
2. stoppt wiederholte manuelle Retries und dokumentiert Beginn privat;
3. lässt automatische, begrenzte Outbox-Retries bestehen, sofern der Fehler
   temporär ist;
4. informiert Pilotverantwortung und betroffene Nutzer über den vereinbarten
   Alternativkanal;
5. wechselt den Provider nur nach neuer Domain-, TLS-, Identitäts- und
   Zustellfreigabe.

Nach Provider-Rückkehr werden Health, Zertifikat und `mail-domain-check`
geprüft. Danach folgen je eine kontrollierte Login-/Einladungsnachricht und
Rechnung. Erst wenn Message-ID, Identitäten, PDF-Hash und exakt eine Annahme
stimmen, werden ausgewählte Dead Letters sicher wiederholt. Abschlusszeit,
Anzahl, Fehlerklassen und Ergebnis landen ausschließlich im privaten
Evidence-Store; anschließend wird der Mailstatus auf normal gesetzt.
