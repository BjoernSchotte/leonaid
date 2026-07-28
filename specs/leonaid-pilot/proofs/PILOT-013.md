# PILOT-013 – Einladungen und E-Mail-Korrektur betreibbar machen

Task-ID: `PILOT-013`

Nachweisdatum: 28. Juli 2026

Status: technisch vollständig bewiesen, formaler Abschluss blockiert

## Ergebnis

Die Mitgliederverwaltung deckt den vollständigen Einladungs- und
E-Mail-Korrekturzyklus ab:

- System-Admins sehen alle Einladungen; Charity-Admins ausschließlich
  Einladungen eigener Aktionen.
- Offene Einladungen können widerrufen, rate-limitiert erneut versendet oder
  durch Widerruf plus unveränderliche neue Einladung auf eine andere Adresse
  korrigiert werden.
- Die Liste unterscheidet offen, angenommen, abgelaufen und widerrufen und
  zeigt bei ersetzten Einladungen die nachvollziehbare Verbindung.
- Nur der System-Admin kann nach frischer Anmeldung die aktive Login-E-Mail
  eines Mitglieds korrigieren.
- Bis zur Bestätigung bleibt die alte Adresse aktiv. Link und Code an die neue
  Adresse sind einmalig und zeitlich begrenzt.
- Bei Bestätigung werden Adresse und Verifikationszeitpunkt atomar geändert,
  alle Sitzungen und offenen Login-Challenges des Zielkontos widerrufen und
  alte wie neue Adresse informiert.
- Bereits belegte Adressen, konkurrierende Pending Changes, abgelaufene
  Bestätigungen, falsche Codes und Replay werden ohne Enumeration
  verständlich beziehungsweise öffentlich generisch abgewiesen.
- Mitglieder besitzen weiterhin keinen Self-Service zur Änderung ihrer
  Login-E-Mail.

Der Workflow verwendet unveränderliche PostgreSQL-Snapshots, PII-arme
AuditEvents und die providerneutrale Outbox-/Worker-Zustellung aus
`PILOT-020`.

## Automatische Nachweise

```sh
./leonaid test-invitations
```

Ergebnis:

```text
invitation-contract: Link, Code, Ablauf, Widerruf, atomare Aktivierung,
Lifecycle-Liste, Neuversand, Adresskorrektur und bestätigten
Login-E-Mail-Wechsel mit Sessionentzug sowie echten Outbox/SMTP-Versand
bewiesen
6 passed in Chromium
invitation-test: OK: Berechtigung, Link/Code und echte Mailzustellung bewiesen
```

Der isolierte Realtest startet FastAPI, PostgreSQL, Worker, Mailpit, Web- und
Public-Frontend sowie den Proxy aus leeren Volumes. Er belegt insbesondere:

1. autorisierte Aktionsscopes für System- und Charity-Admin;
2. unveränderliche Einladungsverläufe, Resend-Mindestabstand, Widerruf und
   Adresskorrektur;
3. atomare Annahme per Link und Code sowie Ablauf und Fünf-Versuche-Sperre;
4. generische Fehler und Rate Limits gegen Enumeration;
5. Fresh-Login- und System-Admin-Grenze des Login-E-Mail-Wechsels;
6. Ablehnung belegter, konkurrierender und abgelaufener Änderungen;
7. atomaren Wechsel mit Entzug von zwei Ziel-Sitzungen und einer offenen
   Login-Challenge;
8. Replay-Schutz, angemessene Nachrichten an alte und neue Adresse und echte
   SMTP-Zustellung;
9. Fortbestand einer unabhängigen System-Admin-Sitzung, auch wenn die
   öffentliche Bestätigung im selben Browser erfolgt.

Die sechs Chromium-Abläufe beweisen die Scopes beider Admin-Personas, den
vollständigen Einladungsverlauf, die mobile Code-Annahme, den geführten
Admin-Dialog zur E-Mail-Korrektur und die mobile öffentliche Bestätigung.
Die privaten Screenshots liegen unter `.artifacts/poc041/` und werden nicht
versioniert.

## Sichtbarer In-App-Browser-Nachweis

Der kanonische Entwicklungsstack wurde zusätzlich sichtbar im
In-App-Browser bedient:

1. System-Admin suchte das synthetische Mitglied Klara Kern und öffnete
   „Login-E-Mail korrigieren“.
2. Der abgelaufene Fresh Login führte über eine echte Worker-/SMTP-/
   Mailpit-Nachricht und einen sechsstelligen Code zurück zur begonnenen
   Admin-Aktion.
3. Die Pending-Meldung bestätigte, dass die bisherige Adresse aktiv bleibt
   und beide Adressen informiert wurden.
4. Die öffentliche Astro-Seite bestätigte den Magic Link und meldete den
   Sitzungsentzug des Zielkontos.
5. Nach Reload zeigte die Mitgliederverwaltung die neue Adresse.

Dieser sichtbare Lauf fand zusätzlich einen Randfall: Die Public-Route löschte
anfangs pauschal die Browser-Session-Cookie und meldete dadurch einen
unbeteiligten System-Admin im selben Browser ab. Die Cookie-Löschung wurde
entfernt, weil die Ziel-Sitzungen bereits atomar serverseitig widerrufen
werden. Der zweite sichtbare Durchlauf belegte anschließend sowohl die neue
Mitgliedsadresse als auch die weiterhin aktive, unabhängige Admin-Sitzung.
Der Realvertrag schützt diesen Befund dauerhaft.

## Docker-Ressourcen

Der Test verwendet exakt das Compose-Projekt `leonaid-poc041-test`. Nach dem
erfolgreichen Lauf lieferten die Inventuren jeweils null Container, Netze und
Volumes mit diesem Projektlabel. Der kanonische Entwicklungsstack `leonaid`
blieb für die sichtbare Abnahme aktiv.

## Formale Taskgrenze

Alle Kriterien von `PILOT-013` sind technisch bewiesen. Der Task bleibt im
Plan formal offen, weil `PILOT-020` bis zur realen
Produktionsprovider-Konfiguration und externen Zustellabnahme formal offen
ist. Der lokale Mailpit-Nachweis ersetzt diese produktive Abhängigkeit nicht.
