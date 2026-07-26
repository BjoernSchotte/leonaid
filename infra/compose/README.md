# Compose

`compose.yml` ist die einzige Definition für lokale Entwicklung und
Integrationstests.

Der Standardstart enthält Caddy, FastAPI, Core-Worker/-PostgreSQL, Web, PWA,
Public Web, Twenty Server/Worker/PostgreSQL/Redis und RustFS:

```sh
./leonaid dev
```

Die Mitgliederoberflächen sind anschließend unter
`https://localhost:8443` erreichbar. Caddy erzeugt für die lokale Entwicklung
ein internes Zertifikat; Diagnosezugriffe bleiben zusätzlich auf
`http://localhost:8080` möglich. Ausschließlich der Proxy veröffentlicht diese
beiden Ports am Loopback-Interface.

Optionale Dienste werden explizit zugeschaltet:

```sh
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile dev-mail up -d --wait
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile mailing up -d --wait
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile observability up -d --wait
```

`./leonaid test-integration` verwendet ein isoliertes Compose-Projekt und
räumt nur dessen Container, Netze und Volumes auf. Der Test startet aus
leeren Volumes, prüft sämtliche Healthchecks und Host-Portbindungen, schreibt
Golden Data über PostgreSQL und die echte S3-API und verifiziert sie nach
einem Neustart aller Standardcontainer. Anschließend beweist er
Reset-Sicherheit, idempotentes Seeding über die offizielle Twenty API, echte
Typst-PDFs in RustFS, einen leeren Mailpit-Stand sowie die exakte
Wiederherstellung nach realen Mutationen aller vier Systeme.

Der gezielte Identitätsnachweis läuft mit:

```sh
./leonaid test-identity
```

Er startet ebenfalls aus leeren Volumes, sät Golden-Benutzer und -Aktionen,
prüft serverseitige Sitzungen, Rollenänderungen und AuditEvents gegen
PostgreSQL/FastAPI und bedient anschließend Admin- und PWA-Shell mit einem
echten Chromium. Laufzeit-Sitzungstoken liegen nur in einer temporären Datei
mit Modus `0600`; die geheimnisfreien Screenshots bleiben ignoriert unter
`.artifacts/poc040/`.

Der gezielte Einladungsnachweis läuft mit:

```sh
./leonaid test-invitations
```

Er startet PostgreSQL, FastAPI, Worker, Mailpit, Caddy und die Web-Oberflächen
aus leeren isolierten Volumes. Der Vertrag lädt echte Einladungsmails aus
Mailpit, nimmt getrennte Einladungen per Link und Code an und prüft Ablauf,
Widerruf, Wiederverwendung, Fehlversuchssperre, atomare
Account-/Membership-Aktivierung und AuditEvents. Anschließend beweist Chromium
bei Desktop- und Mobilbreite die serverseitig begrenzte Aktionsauswahl sowie
die öffentliche Code-Eingabe. Geheimnisfreie Screenshots bleiben unter
`.artifacts/poc041/`.

Der gezielte Sitzungsnachweis läuft mit:

```sh
./leonaid test-sessions
```

Er startet PostgreSQL, FastAPI, Worker, Mailpit und die Oberflächen mit echtem
HTTPS aus leeren, isolierten Volumes. Vertrag und Chromium beweisen den
generischen passwortlosen Login, das geschützte `__Host-`-Cookie, das absolute
90-Tage-Ende, normalen Zugriff nach abgelaufener Fresh-Frist, die erneute
Code-Anmeldung für eine sensible Admin-Aktion, Tokenrotation, Logout und
administrativen Sofortwiderruf. Geheimnisfreie Screenshots bleiben unter
`.artifacts/poc042/`.

Der gezielte Row-Level-Policy-Nachweis läuft mit:

```sh
./leonaid test-policy
```

Er provisioniert eine neue gepinnte Twenty-Instanz samt eingeschränktem
Integrations-Key, sät das vollständige Golden Dataset mit echten
Typst-Dokumenten und prüft den gemeinsamen serverseitigen Scope für Listen,
Suche, Counts, Export, Aktivität und Dokumente. Akquisiteure authentifizieren
sich ausschließlich am LeonAid Core; der Twenty-Key wird nur in den
Core-Container injiziert. Entfernte Memberships und Assignments wirken im
nächsten Request ohne neue Anmeldung.

Der gezielte Nachweis des neutralen Charity-Aktionskerns läuft mit:

```sh
./leonaid test-actions
```

Er startet die gepinnten Standarddienste aus leeren isolierten Volumes,
persistiert Lifecycle, Capabilities, Zielwerte, mehrere Begünstigte und
AuditEvents über FastAPI/PostgreSQL und erstellt anschließend mit echtem
Chromium eine vollständige Aktion unter `/admin/actions/new`. Der Browser
verifiziert das Ergebnis ausschließlich über die Core-API. Der
geheimnisfreie Screenshot bleibt unter `.artifacts/poc050/`.

Der gezielte Nachweis der versionierten Aktionstemplates läuft mit:

```sh
./leonaid test-templates
```

Er startet Twenty, Core-PostgreSQL, FastAPI und RustFS aus leeren isolierten
Volumes. Ein echter API-/PostgreSQL-Vertrag beweist die neutrale und die
Krapfentaxi-Vorlage, unveränderliche publizierte Versionen, historisch stabile
Konfigurations-Snapshots sowie eine Vorjahreskopie ohne Bestellungen,
Rechnungen, Dokumente, laufende Nummern oder fremde Aktionszuordnungen.

`./leonaid provision-twenty` legt den lokalen Integrations-Key mit restriktiven
Dateirechten unter `.local/twenty/integration.env` ab. Alle folgenden
`./leonaid`-Compose-Kommandos lesen ihn automatisch ein, ohne ihn in
`.env.local`, Prozessargumente oder Browserkonfiguration zu kopieren. Eine
explizite Prozessvariable `TWENTY_INTEGRATION_API_KEY` hat für CI weiterhin
Vorrang.
