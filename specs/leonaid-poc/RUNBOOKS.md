# LeonAid PoC – Betriebs- und Benutzer-Runbooks

Stand: 2026-07-27

## Runbook-Index

| Situation | Verbindliche Anleitung |
| --- | --- |
| lokaler Start, Profile und Ports | [Compose](../../infra/compose/README.md) |
| Systemsignale und Dead Letter | [Observability](../../infra/observability/README.md) |
| verschlüsseltes Backup und Restore | [Backup/Recovery](../../infra/backup/README.md) |
| Upgrade, Wartungsmodus und Rollback | [Upgrade/Rollback](../../infra/upgrade/README.md) |
| Twenty-Schema und CRM-Key | [Twenty](../../infra/twenty/README.md) |
| RustFS und S3-Port | [RustFS](../../infra/rustfs/README.md) |
| TLS, Caddy und Browserrouten | [Proxy](../../infra/proxy/README.md) |
| Entwicklerworkflow | [Development Guide](DEVELOPMENT.md) |

## Normalbetrieb

Start und Readiness:

```sh
./leonaid doctor
./leonaid dev
./leonaid seed
```

`seed` provisioniert Twenty und startet API/Worker mit dem frisch
verifizierten Integrationsschlüssel neu, bevor Golden Data eingespielt wird.

Danach müssen `http://127.0.0.1:8080/_health` und
`http://127.0.0.1:8080/api/health/ready` erfolgreich antworten. Der
System-Admin prüft zusätzlich `/admin/system`: CRM, Dateiablage und E-Mail
müssen getrennt sichtbar sein.

Ein geordneter Stopp ohne Datenlöschung:

```sh
docker compose --env-file .env.local \
  --file infra/compose/compose.yml stop
```

`down --volumes`, `./leonaid reset` und Restore-Befehle sind keine
Normalbetriebsbefehle. Sie dürfen nur im jeweils dokumentierten,
explizit bestätigten Zielprojekt ausgeführt werden.

## Benutzerverwaltung

### Mitglied aufnehmen

1. Als Charity-Admin oder System-Admin frisch anmelden.
2. `/admin/members` öffnen.
3. Nur eine selbst verwaltete Aktion, Name, Login-E-Mail und Aktionsrolle
   auswählen.
4. Einladung senden.
5. Das Mitglied nimmt Link oder Code innerhalb von 30 Minuten an.
6. Gemeinsam prüfen, dass die richtige Aktion und Rolle im Arbeitskontext
   erscheinen.

Ein Charity-Admin sieht serverseitig nur selbst verwaltete Aktionen. Die
Annahme aktiviert Account und Membership atomar. Testcodes werden lokal über
`/mail/` eingesehen; produktiv kommen sie ausschließlich über den
konfigurierten Relay.

### Weitere Aktion oder Rolle hinzufügen

Die vorhandene Login-E-Mail wird erneut in die gewünschte Aktion eingeladen.
Nach Annahme entsteht keine zweite Identität, sondern eine zusätzliche
Aktionsmitgliedschaft. Die sichtbaren Arbeitskontexte sind danach gemeinsam
zu prüfen.

### Offene Einladung widerrufen

Der kanonische, Fresh-Login-geschützte Vertrag ist
`DELETE /api/v1/invitations/{invitation_id}`. Die aktuelle PoC-Oberfläche
besitzt noch keine vollständige Einladungsliste; siehe
[`KNOWN-LIMITS.md`](KNOWN-LIMITS.md). Ohne eindeutig bekannte
Einladungs-ID wird nicht in PostgreSQL gesucht oder geändert.

### Sitzung sofort entziehen

Bei verlorenem Gerät oder vermutetem Sessionmissbrauch:

1. System-Admin frisch anmelden.
2. Die eindeutige Benutzer-ID aus einem bereits autorisierten
   Administrationsvorgang bestimmen.
3. `DELETE /api/v1/admin/users/{user_id}/sessions` über den generierten
   API-Client ausführen.
4. `revoked_count` und das AuditEvent prüfen.
5. Betroffene Person informieren und neuen Login beobachten.

Die aktuelle PoC-UI bietet dafür noch keinen vollständigen
Benutzerlisten-Workflow. Ist die ID nicht belastbar bestimmbar, wird der
Zugriff über Wartungsmodus beziehungsweise Proxy vorübergehend gesperrt und
als Incident behandelt. Direkte Datenbankänderung ist verboten.

### Austritt, Rollenwechsel und E-Mail-Änderung

Diese Vorgänge besitzen im PoC noch keinen vollständigen Operator-Workflow.
Vor einem realen Pilot müssen Account-Sperre, Membership-Entzug,
Rollenwechsel und kontrollierte E-Mail-Korrektur mit Audit und Fresh Login
ergänzt werden. Bis dahin ist der PoC nicht für reale Offboarding-Fälle
freigegeben.

## Incident-Runbook

### Priorität

| Stufe | Beispiel | Reaktion |
| --- | --- | --- |
| P0 | vermuteter Datenabfluss, zerstörte Primär- und Backupdaten | sofort Schreibzugriff stoppen, Betreiber und Datenschutzverantwortliche alarmieren |
| P1 | falsche Autorisierung, verlorene Rechnungen, nicht restaurierbarer Kernablauf | sofort Wartungsmodus, Bearbeitung bis zur Freigabe |
| P2 | einzelner Dienst ausgefallen, Jobs im Dead Letter, Workaround vorhanden | am selben Arbeitstag bearbeiten |
| P3 | kosmetischer Fehler oder nicht kritische Verbesserung | normal priorisieren |

### Erste 15 Minuten

1. Zeitpunkt, meldende Person und beobachtete Auswirkung notieren.
2. Keine Payloads, E-Mails, Tokens oder Dokumentbytes in Chat oder Ticket
   kopieren.
3. `/health/live`, `/health/ready` und `/admin/system` prüfen.
4. Bei möglicher Daten- oder Autorisierungsverletzung Wartungsmodus
   aktivieren:

   ```sh
   infra/upgrade/maintenance.sh enable
   ```

5. Betroffene Request-, Job-, Action- und Objekt-IDs sowie Containerstatus
   sichern.
6. Den letzten erfolgreichen externen Recovery Point gegen
   `restic check --read-data` prüfen, aber keinen Restore in die
   Quellumgebung starten.

### Dienstspezifische Behandlung

- **Twenty:** LeonAid-Liveness kann grün bleiben, Readiness wird rot.
  Keine CRM-Schreibvorgänge wiederholen, bis Twenty bereit ist.
- **RustFS:** Rechnungsausgabe und -versand nicht als erfolgreich behandeln.
  Metadaten bleiben in Core PostgreSQL; Objekt und SHA nach Wiederanlauf
  prüfen.
- **Mail:** Fachschreibvorgänge können weiterlaufen. Dead-Letter-Ursache
  beheben und nur über `/admin/system` sicher wiederholen.
- **Core PostgreSQL:** alle Writer stoppen. Keine Reparatur am Original;
  Recovery Point in ein frisches Ziel restaurieren.
- **Verdächtige Sitzung:** Zugriff begrenzen, Sitzungen entziehen und
  Auth-/Audit-Signale korrelieren.

### Wiederfreigabe

Schreibzugriffe werden erst freigegeben, wenn:

- Ursache und betroffener Zeitraum bekannt sind;
- Healthchecks und Abhängigkeitssignale grün sind;
- relevante Fachsummen und Dokument-SHAs stimmen;
- die betroffene Browser-Journey erfolgreich ist;
- Verantwortlicher, Ergebnis und verbleibendes Risiko protokolliert sind.

Bei Restore oder Upgrade gelten ausschließlich die verlinkten
Spezialrunbooks. Ein Incident endet mit Ursachenanalyse, konkreter
Präventionsmaßnahme und Prüfung, ob Datenschutz-, Rechts- oder
Versicherungsmeldungen erforderlich sind.
