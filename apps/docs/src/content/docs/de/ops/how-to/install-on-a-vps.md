---
title: LeonAid auf einem frischen VPS installieren
description: Einen leeren Ubuntu- oder Debian-Server vorbereiten und die Erstinstallation mit Mailversand, täglichem Backup, geplanter CRM-Reparatur, Heartbeat und Uptime-Check ausführen.
docId: DOC-P039
audience: [ops]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: ee30ab95b4f0c45d863c5e09fa12783583a3475f
reviewer: Björn Schotte
---

Diese Anleitung führt von einem leeren virtuellen Server zu einer laufenden
LeonAid-Installation für einen Club. Sie endet mit `./leonaid pilot-install`,
einem täglichen Backup-Timer, der geplanten Reparatur der CRM-Abgleichschlüssel
und einem externen Heartbeat. Spätere Releases
folgen [Eine Pilotinstallation bereitstellen](/de/ops/how-to/deploy-pilot/).

:::caution[Entwicklungs- und Pilotstand]
Die Tests im Repository beweisen die Schritte in einem isolierten Stack. Sie
geben deinen Server nicht frei. DNS, TLS, Mail, Backupziel und
Pilotentscheidungen brauchen für jede Installation eine eigene Abnahme.
:::

## Was du brauchst

- **Server:** x86_64 mit Ubuntu 24.04 LTS oder Debian 12. Plane 8 GB RAM,
  4 vCPU (mindestens 2) und 80 GB SSD (mindestens 40 GB). Twenty, zwei
  PostgreSQL-Datenbanken, RustFS, Proxy, API, Worker, drei Weboberflächen und
  das Monitoring teilen sich diesen Speicher.
- **Swap:** 2 bis 4 GB. Swap fängt Spitzen ab; er ersetzt keinen RAM.
- **DNS:** ein Name für das Portal (zum Beispiel `portal.club.org`). Das
  CRM hat keinen öffentlichen Namen; die Systemadministration öffnet es über
  einen SSH-Tunnel (siehe [CRM öffnen](#crm-öffnen)).
- **Backupziel:** ein S3-kompatibler Bucket bei einem anderen Anbieter.
  Backups liegen nie nur auf demselben Server.
- **Mail:** ein SMTP-Zugang für die Absenderdomain des Clubs. LeonAid und
  Twenty CRM versenden beide darüber. Das Relay braucht ein Zertifikat einer
  öffentlichen CA, und der Server muss es ausgehend auf Port 465 (implizites
  TLS) erreichen. Twenty versendet nur über implizites TLS; mit Port 587
  (STARTTLS) versendet nur LeonAid.
- **Alarmierung:** ein Operator-Webhook (Chat oder Incident-Werkzeug), ein
  externer Heartbeat-Check wie healthchecks.io und ein externer
  Uptime-Monitor.
- **Release:** ein freigegebenes Tag `vYYYY.M.N` mit den Dateien
  `release-images.env` und `release-manifest.json` (siehe
  [Eine Version releasen](/de/ops/how-to/release-a-version/)).

Führe die Befehle als Administrator mit `sudo` aus, außer der Schritt sagt
„als `leonaid`“.

## Betriebssystem aktualisieren

```sh
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades git curl ca-certificates gnupg ufw
sudo dpkg-reconfigure --priority=low unattended-upgrades
sudo timedatectl set-ntp true
```

Der Pilot-Doctor lehnt eine Uhr ab, die mehr als fünf Minuten abweicht. Lass
NTP deshalb aktiv. Lege Swap an, wenn das Anbieter-Image keinen hat:

```sh
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Betriebsaccount anlegen

LeonAid läuft unter dem unprivilegierten Account `leonaid`. Die
systemd-Units erwarten diesen Namen.

```sh
sudo adduser --disabled-password --gecos 'LeonAid operator' leonaid
sudo install -d -o leonaid -g leonaid -m 0700 /home/leonaid/.ssh
sudo cp ~/.ssh/authorized_keys /home/leonaid/.ssh/authorized_keys
sudo chown leonaid:leonaid /home/leonaid/.ssh/authorized_keys
```

Behalte deinen eigenen Administrator-Account für `sudo`. Gib `leonaid` keine
sudo-Rechte.

## SSH härten

Erlaube nur Schlüssel und keinen Root-Login. Halte eine zweite SSH-Sitzung
offen, bis die neuen Einstellungen funktionieren.

```sh
sudo tee /etc/ssh/sshd_config.d/10-leonaid.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

## Nur die Ports 22, 80 und 443 öffnen

```sh
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Docker schreibt für veröffentlichte Ports eigene Firewallregeln und umgeht
ufw. LeonAid veröffentlicht nur den Proxy auf 80 und 443. Der Twenty-Server
lauscht für den Admin-SSH-Tunnel auf `127.0.0.1:TWENTY_ADMIN_PORT`
(Standard 3020), den das Internet nicht erreicht. Datenbanken, RustFS und
Monitoring bleiben in internen Docker-Netzen. Nach der Installation zeigt
`docker ps --format '{{.Names}} {{.Ports}}'` den Proxy auf 80/443 und
`twenty-server` nur auf `127.0.0.1`.

## Docker Engine und Compose installieren

Verwende Dockers eigenes Paketrepository, nicht die Pakete der Distribution.
Unter Debian ersetzt du in beiden URLs `ubuntu` durch `debian`.

```sh
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg |
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker leonaid
```

Wer in der Gruppe `docker` ist, hat auf diesem Host Root-Rechte. Nur der
Betriebsaccount bekommt sie.

## Containerlogs rotieren

Die Compose-Dienste von LeonAid rotieren ihre Logs bereits. Diese Vorgabe
deckt auch einmalige Container ab, die `./leonaid` startet:

```sh
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "local",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
EOF
sudo systemctl restart docker
```

## DNS auf den Server zeigen lassen

Lege einen `A`-Record (und einen `AAAA`-Record, wenn der Server IPv6 hat)
für den Portalnamen an. Prüfe ihn vor der Installation:

```sh
dig +short portal.club.org
```

Caddy holt die TLS-Zertifikate beim ersten Start. Dafür muss Port 80 aus dem
Internet erreichbar sein.

## Verzeichnisse anlegen

| Pfad                        | Besitzer  | Modus  | Inhalt                                          |
| --------------------------- | --------- | ------ | ----------------------------------------------- |
| `/opt/leonaid`              | `leonaid` | `0755` | Git-Checkout auf dem Release-Commit             |
| `/etc/leonaid`              | `leonaid` | `0700` | `production.env`, `backup.env`, Bootstrap-Datei |
| `/etc/leonaid/secrets`      | `leonaid` | `0700` | Restic-Passwort, Backup-Zugang, URLs            |
| `/var/lib/leonaid`          | `leonaid` | `0700` | überwachter Datenpfad                           |
| `/var/lib/leonaid/evidence` | `leonaid` | `0700` | aktuelles Backup-Manifest                       |
| `/var/lib/leonaid/releases` | `leonaid` | `0700` | heruntergeladene Release-Dateien                |

```sh
sudo install -d -o leonaid -g leonaid -m 0755 /opt/leonaid
sudo install -d -o leonaid -g leonaid -m 0700 /etc/leonaid /etc/leonaid/secrets \
  /var/lib/leonaid /var/lib/leonaid/evidence /var/lib/leonaid/releases
```

`pilot-install` schreibt den Twenty-Key per atomarem Umbenennen in
`production.env`. Deshalb muss `/etc/leonaid` dem Account `leonaid` gehören.

## Release auschecken

Lade als `leonaid` die Release-Dateien herunter und checke genau den Commit
aus, den `release-images.env` nennt:

```sh
cd /var/lib/leonaid/releases
curl -fsSLO https://github.com/BjoernSchotte/leonaid/releases/download/vYYYY.M.N/release-images.env
curl -fsSLO https://github.com/BjoernSchotte/leonaid/releases/download/vYYYY.M.N/release-manifest.json
git clone https://github.com/BjoernSchotte/leonaid.git /opt/leonaid
commit=$(sed -n 's/^LEONAID_RELEASE_COMMIT=//p' release-images.env)
git -C /opt/leonaid checkout --detach "$commit"
```

Jeder `pilot-*`-Befehl vergleicht den Checkout mit `LEONAID_RELEASE_COMMIT`.

## Produktions-Secrets erzeugen

Als `leonaid` in `/opt/leonaid`:

```sh
./leonaid pilot-secrets --output /etc/leonaid/production.env
```

Der Befehl füllt jedes Zufalls-Secret aus `infra/pilot/production.env.example`
mit einem frischen, eigenen Wert, schreibt die Datei mit Modus `0600` und
überschreibt nie eine vorhandene Datei. Er nennt die Schlüssel, die du von
Hand ausfüllst:

- die Tenant-ID in `LEONAID_COMPOSE_PROJECT`, `RUSTFS_BUCKET` und
  `RESTIC_REPOSITORY`;
- die acht Zeilen aus `release-images.env` (ersetze die Vorlagenzeilen);
- `LEONAID_CLUB_NAME`, den Clubnamen in der Seitenleiste der Verwaltung (ohne
  ihn startet die API in Produktion nicht);
- die Portaldomain, `CADDY_ACME_EMAIL`, `MAIL_*` und den SMTP-Zugang;
- `TWENTY_ADMIN_PORT` nur, wenn Port 3020 auf dem Server belegt ist;
- `TWENTY_MAIL_FROM_ADDRESS` und `TWENTY_MAIL_FROM_NAME`, den Absender der
  Twenty-eigenen Mails (siehe [Mail für LeonAid und Twenty](#mail-für-leonaid-und-twenty));
- S3-Endpunkt und Bucket in `RESTIC_REPOSITORY`.

Lass `TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL` stehen.
`pilot-install` erzeugt den echten Key.

### Mail für LeonAid und Twenty

Das SMTP-Relay konfigurierst du einmal über die Schlüssel `MAIL_SMTP_*`.
Der Core-Worker versendet darüber Login-Codes, Einladungen und Rechnungen.
Twenty versendet über dasselbe Relay Adressbestätigung und Passwort-Reset.
Beide Absender erreichen das Relay nur über das eigene Netz `mail-egress`;
alle anderen internen Netze haben keinen Weg nach draußen.

| `MAIL_SMTP_MODE` | `MAIL_SMTP_PORT` | Core-Worker | Twenty |
| ---------------- | ---------------- | ----------- | ------ |
| `tls` (Vorlagenstandard) | 465 | implizites TLS | implizites TLS |
| `starttls` | nicht 465, meist 587 | verlangt STARTTLS | versendet nichts |
| `plain` | – | in Produktion abgelehnt | in Produktion abgelehnt |

Beide prüfen das Relay-Zertifikat gegen die öffentlichen CAs, deshalb
lehnt der Pilot `MAIL_SMTP_CA_FILE` ab. Pilot Doctor lehnt einen Port ab,
der nicht zum Modus passt: `tls` braucht Port 465, `starttls` einen anderen
Port.

`TWENTY_MAIL_FROM_ADDRESS` muss eine reine Adresse in der Domain von
`MAIL_FROM` sein, zum Beispiel `crm@club.org`. Dann decken SPF, DKIM und
DMARC der Absenderdomain auch die Mails von Twenty ab.

:::caution[Twenty-Mail braucht implizites TLS]
Twenty 2.54 kann STARTTLS nicht erzwingen: Sein SMTP-Client wechselt nur zu
TLS, wenn das Relay STARTTLS anbietet, und ein Angreifer im Netzpfad kann das
Angebot unterdrücken und die Mail mitlesen. Twenty hat keine Einstellung, die
STARTTLS verlangt. LeonAid startet Twenty deshalb nur bei
`MAIL_SMTP_MODE=tls` mit dem SMTP-Treiber. Bei `starttls` nutzt Twenty den
Logger-Treiber und versendet nichts, und `pilot-doctor` gibt eine Warnung
(keinen Fehler) aus. LeonAids eigener Mailversand ist nicht betroffen. Nutze
Port 465, wenn dein Anbieter ihn anbietet.
:::

Lege danach die übrigen Secret-Dateien mit Modus `0600` an:

```sh
umask 077
openssl rand -base64 48 >/etc/leonaid/secrets/restic-password
printf '%s\n' 'AWS_ACCESS_KEY_ID=...' 'AWS_SECRET_ACCESS_KEY=...' \
  'AWS_DEFAULT_REGION=...' >/etc/leonaid/secrets/restic-backend.env
printf '%s\n' 'https://chat.example.net/hooks/...' >/etc/leonaid/secrets/alert-webhook-url
printf '%s\n' 'https://hc-ping.com/<uuid>' >/etc/leonaid/secrets/alert-heartbeat-url
printf '%s\n' 'TWENTY_BOOTSTRAP_EMAIL=crm-admin@club.org' \
  "TWENTY_BOOTSTRAP_PASSWORD=$(openssl rand -hex 24)" >/etc/leonaid/twenty-bootstrap.env
```

Die Bootstrap-Datei wird zum ersten Twenty-Administrator. Verwende eine
kleingeschriebene Adresse und ein Passwort aus mindestens 16 Buchstaben oder
Ziffern. Lege beides im Passwortmanager des Clubs ab.

Alertmanager läuft als Benutzer `nobody` (UID 65534) und muss die beiden
URL-Dateien lesen. Übergib sie schreibgeschützt:

```sh
sudo chown 65534:65534 /etc/leonaid/secrets/alert-webhook-url /etc/leonaid/secrets/alert-heartbeat-url
sudo chmod 0400 /etc/leonaid/secrets/alert-webhook-url /etc/leonaid/secrets/alert-heartbeat-url
```

## An der Container-Registry anmelden

Überspringe diesen Schritt, wenn die Release-Images öffentlich sind. Sonst
meldest du dich als `leonaid` mit einem GitHub-Token an, das nur
`read:packages` darf:

```sh
docker login ghcr.io -u <github-user>
```

## Erstinstallation ausführen

Als `leonaid` in `/opt/leonaid`:

```sh
./leonaid pilot-install \
  --env-file /etc/leonaid/production.env \
  --release-manifest /var/lib/leonaid/releases/release-manifest.json \
  --twenty-bootstrap-file /etc/leonaid/twenty-bootstrap.env \
  --password-file /etc/leonaid/secrets/restic-password \
  --credentials-file /etc/leonaid/secrets/restic-backend.env
```

`pilot-install` bricht ab, wenn das Compose-Projekt schon Volumes oder
Container hat, wenn eine Secret-Datei für andere lesbar ist oder im Checkout
liegt oder wenn der Twenty-Key nicht mehr aussteht. Danach:

- prüft es Konfiguration, Release-Manifest, Pilotentscheidungen und den
  Doctor für eine Erstinstallation;
- startet es nur Twenty und seine Datenspeicher, ohne Proxy und damit ohne
  öffentlichen Zugang (Twenty selbst ist nie öffentlich);
- legt es Twenty-Workspace, Schema, Rollen und den minimal berechtigten
  API-Key an und prüft den Key;
- bestätigt es die E-Mail-Adresse des Administrators über Twentys eigene
  Verifizierung, weil produktives Twenty unbestätigte Benutzer ablehnt;
- schreibt es den Key in `production.env` (Modus `0600` bleibt);
- startet es den vollständigen Stack mit aktiver E-Mail-Verifizierung (und
  Twentys SMTP-Treiber bei `MAIL_SMTP_MODE=tls`) und meldet sich zum Beweis
  als Administrator an;
- erstellt es das erste verschlüsselte Backup, startet das Monitoring und
  führt den vollständigen Doctor aus.

Scheitert ein Schritt, bleiben Container und Volumes zur Diagnose erhalten.
Die Fehlermeldung nennt den Befehl `docker compose ... down --volumes`, der
sie vor einem neuen Versuch entfernt. War der Key schon geschrieben, setze
wieder `TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL`; die Meldung weist
darauf hin.

## CRM öffnen

Das Twenty CRM ist nur für die Systemadministration da. Es hat keine
öffentliche Domain, und der Proxy leitet nicht dorthin weiter.
`twenty-server` lauscht auf `127.0.0.1:TWENTY_ADMIN_PORT` des Servers. Gib
den Tunnelbefehl als `leonaid` aus:

```sh
./leonaid crm-admin --env-file /etc/leonaid/production.env \
  --ssh-target admin@portal.club.org
```

Der Befehl prüft, dass `twenty-server` seinen Port nur auf `127.0.0.1`
veröffentlicht, und nennt die beiden Schritte:

```sh
ssh -N -L 3020:127.0.0.1:3020 admin@portal.club.org
```

Lass den Tunnel offen und rufe auf deinem Arbeitsplatz `http://localhost:3020`
auf. Twenty baut seine Links aus `SERVER_URL=http://localhost:TWENTY_ADMIN_PORT`,
deshalb muss der lokale Port derselbe sein wie auf dem Server. Melde dich mit
dem Bootstrap-Administrator an.

## Tägliches Backup planen

Doctor und der Alarm `LeonAidBackupStale` verlangen ein Backup, das jünger
als 26 Stunden ist. Installiere die systemd-Units aus dem Checkout:

```sh
sudo cp /opt/leonaid/infra/pilot/systemd/leonaid-backup.service \
  /opt/leonaid/infra/pilot/systemd/leonaid-backup.timer /etc/systemd/system/
sudo install -o leonaid -g leonaid -m 0600 \
  /opt/leonaid/infra/pilot/systemd/backup.env.example /etc/leonaid/backup.env
sudo systemctl daemon-reload
sudo systemctl enable --now leonaid-backup.timer
sudo systemctl start leonaid-backup.service
journalctl -u leonaid-backup.service -n 20
systemctl list-timers leonaid-backup.timer
```

Der Timer läuft täglich um 02:30 mit bis zu 45 Minuten Zufallsverzögerung.
Einen verpassten Lauf holt er nach einem Neustart nach. Passe die Pfade in
`/etc/leonaid/backup.env` an, wenn deine Struktur abweicht.

## CRM-Abgleichschlüssel regelmäßig reparieren

LeonAid findet Firmen und Personen in Twenty über einen gespeicherten
Abgleichschlüssel. Datensätze, die jemand direkt in Twenty anlegt oder
umbenennt (Oberfläche, CSV-Import), haben bis zur Reparatur keinen oder
einen veralteten Schlüssel. Zwei Timer führen
`./leonaid pilot-repair-crm-match-keys` im laufenden API-Container aus:

- `leonaid-crm-repair.timer` alle 15 Minuten mit `--changed-within 30`:
  Das Fenster überlappt den vorigen Lauf, ein verspäteter oder
  ausgelassener Lauf verliert also nichts;
- `leonaid-crm-repair-full.timer` täglich um 04:00 (bis zu 30 Minuten
  Zufallsverzögerung) ohne Fenster: Er repariert alles, was das kurze
  Fenster nicht sieht, etwa nach langer Wartung oder einem Serverausfall.

```sh
sudo cp /opt/leonaid/infra/pilot/systemd/leonaid-crm-repair.service \
  /opt/leonaid/infra/pilot/systemd/leonaid-crm-repair.timer \
  /opt/leonaid/infra/pilot/systemd/leonaid-crm-repair-full.service \
  /opt/leonaid/infra/pilot/systemd/leonaid-crm-repair-full.timer \
  /etc/systemd/system/
sudo install -o leonaid -g leonaid -m 0600 \
  /opt/leonaid/infra/pilot/systemd/crm-repair.env.example /etc/leonaid/crm-repair.env
sudo systemctl daemon-reload
sudo systemctl enable --now leonaid-crm-repair.timer leonaid-crm-repair-full.timer
sudo systemctl start leonaid-crm-repair-full.service
journalctl -u leonaid-crm-repair-full.service -n 20
systemctl list-timers 'leonaid-crm-repair*'
```

Ein erfolgreicher Lauf endet mit `crm-match-keys: OK:` und der Zahl der
geprüften und reparierten Datensätze. Im Wartungsmodus (etwa während
`pilot-release`) ist Twenty absichtlich gestoppt. Der Befehl meldet dann
`SKIPPED` und endet erfolgreich, die Unit schlägt also nicht fehl. Beginnt
die Wartung während eines Laufs, endet auch dieser als `SKIPPED`; der
nächste Lauf und der nächtliche Volllauf holen alles nach. Er schlägt
fehl, wenn der API-Container nicht läuft oder Twenty die Anfrage ablehnt;
`journalctl` zeigt den Fehlercode ohne Secrets.

## Heartbeat und Uptime-Check einrichten

Prometheus löst den Alarm `LeonAidWatchdog` ständig aus. Alertmanager schickt
ihn alle fünf Minuten an die Heartbeat-URL und nirgendwohin sonst. Fallen
Server, Prometheus oder Alertmanager aus, bleiben die Pings aus und der
externe Dienst alarmiert.

- **Heartbeat:** Lege einen Check mit 5 Minuten Periode und 10 Minuten
  Karenz an. Seine Ping-URL gehört in `alert-heartbeat-url`.
- **Uptime:** Lass einen externen Monitor alle 1 bis 5 Minuten
  `https://<portal-domain>/_health` abrufen und den Text `ready` erwarten.
  Seine Alarme gehen an einen Kanal, der nicht von diesem Server abhängt.

`pilot-deploy` und `pilot-release` starten das Monitoring nicht neu. Führe
danach `./leonaid pilot-monitoring --env-file /etc/leonaid/production.env`
aus, damit der Exporter das neue Release-Image verwendet.

:::note[Weitere CRM-Benutzer]
Produktives Twenty verlangt bestätigte E-Mail-Adressen. `pilot-install`
bestätigt den ersten Administrator direkt. Ein weiterer Administrator braucht
ebenfalls SSH-Zugang für den Tunnel und erhält die Bestätigungsmail über das
Relay, was `MAIL_SMTP_MODE=tls` voraussetzt. Prüfe den Weg einmal nach der
Installation: Öffne das CRM über den Tunnel, fordere auf der Anmeldeseite
einen Passwort-Reset für den Administrator an und prüfe, dass die Mail von
`TWENTY_MAIL_FROM_ADDRESS` ankommt. Kommt sie nicht, zeigt
`docker compose ... logs twenty-worker` den SMTP-Fehler.
:::

## Nächste Schritte

- Spätere Releases ausrollen: [Eine Pilotinstallation bereitstellen](/de/ops/how-to/deploy-pilot/)
  und das Release-Runbook `infra/pilot/RELEASE-RUNBOOK.md`.
- Restore üben: [Backup und Restore](/de/ops/how-to/backup-and-restore/).
- Upgrades und Rollbacks: [Upgrade und Rollback](/de/ops/how-to/upgrade-and-rollback/).
- Störungen eingrenzen: [Störungen eingrenzen](/de/ops/how-to/troubleshoot/).
