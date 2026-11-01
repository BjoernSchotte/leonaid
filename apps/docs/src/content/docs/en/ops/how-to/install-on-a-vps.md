---
title: Install LeonAid on a fresh VPS
description: Prepare an empty Ubuntu or Debian server and run the first installation with daily backups, a heartbeat and an uptime check.
docId: DOC-P039
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 23a9e097deca6adb75a1c460a144f9354d403b6d
reviewer: Björn Schotte
---

This guide takes an empty virtual server to a running LeonAid installation for
one club. It ends with `./leonaid pilot-install`, a daily backup timer and an
external heartbeat. Later releases follow
[Deploy a pilot installation](/en/ops/how-to/deploy-pilot/).

:::caution[Development and pilot status]
The repository tests prove the steps in an isolated stack. They do not approve
your server. DNS, TLS, mail, the backup target and the pilot decisions need
their own acceptance for every installation.
:::

## What you need

- **Server:** x86_64 with Ubuntu 24.04 LTS or Debian 12. Use 8 GB RAM, 4 vCPU
  (2 at minimum) and an 80 GB SSD (40 GB at minimum). Twenty, two PostgreSQL
  databases, RustFS, the proxy, the API, the worker, three web front ends and
  monitoring share this memory.
- **Swap:** 2 to 4 GB. Swap catches peaks; it does not replace RAM.
- **DNS:** two names, one for the portal (for example `portal.club.org`) and
  one for the CRM (for example `crm.club.org`).
- **Backup target:** an S3-compatible bucket at another provider. Never store
  backups only on the same server.
- **Mail:** an SMTP account for the club's sender domain.
- **Alerting:** an operator webhook (chat or incident tool), an external
  heartbeat check such as healthchecks.io and an external uptime monitor.
- **Release:** an approved tag `vYYYY.M.N` with the files `release-images.env`
  and `release-manifest.json` (see
  [Release a version](/en/ops/how-to/release-a-version/)).

Run the commands as an administrator with `sudo` unless the step says
"as `leonaid`".

## Update the operating system

```sh
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades git curl ca-certificates gnupg ufw
sudo dpkg-reconfigure --priority=low unattended-upgrades
sudo timedatectl set-ntp true
```

The pilot doctor refuses a clock that differs by more than five minutes, so
keep NTP active. Add swap when the provider image has none:

```sh
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Create the operator account

LeonAid runs as the unprivileged account `leonaid`. The systemd units expect
this name.

```sh
sudo adduser --disabled-password --gecos 'LeonAid operator' leonaid
sudo install -d -o leonaid -g leonaid -m 0700 /home/leonaid/.ssh
sudo cp ~/.ssh/authorized_keys /home/leonaid/.ssh/authorized_keys
sudo chown leonaid:leonaid /home/leonaid/.ssh/authorized_keys
```

Keep your own administrator account for `sudo`. Do not give `leonaid` sudo
rights.

## Harden SSH

Allow keys only and no root login. Keep a second SSH session open until the
new settings work.

```sh
sudo tee /etc/ssh/sshd_config.d/10-leonaid.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

## Open only ports 22, 80 and 443

```sh
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Docker writes its own firewall rules for published ports and bypasses ufw.
LeonAid publishes only the proxy on 80 and 443; all databases, Twenty,
RustFS and monitoring stay on internal Docker networks. After the installation,
`docker ps --format '{{.Names}} {{.Ports}}'` must show host ports only for the
proxy.

## Install Docker Engine and Compose

Use Docker's own package repository, not the distribution packages. On Debian,
replace `ubuntu` with `debian` in both URLs.

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

Membership in the `docker` group equals root access on this host. Only the
operator account gets it.

## Rotate container logs

LeonAid's Compose services already rotate their logs. This default also
covers one-off containers that `./leonaid` starts:

```sh
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "local",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
EOF
sudo systemctl restart docker
```

## Point DNS to the server

Create `A` records (and `AAAA` records if the server has IPv6) for the portal
and the CRM name. Check both before the installation:

```sh
dig +short portal.club.org
dig +short crm.club.org
```

Caddy requests the TLS certificates on the first start. Port 80 must be
reachable from the internet for that.

## Create the directories

| Path                        | Owner     | Mode   | Content                                        |
| --------------------------- | --------- | ------ | ---------------------------------------------- |
| `/opt/leonaid`              | `leonaid` | `0755` | Git checkout at the release commit             |
| `/etc/leonaid`              | `leonaid` | `0700` | `production.env`, `backup.env`, bootstrap file |
| `/etc/leonaid/secrets`      | `leonaid` | `0700` | Restic password, backup credentials, URLs      |
| `/var/lib/leonaid`          | `leonaid` | `0700` | monitored data path                            |
| `/var/lib/leonaid/evidence` | `leonaid` | `0700` | latest backup manifest                         |
| `/var/lib/leonaid/releases` | `leonaid` | `0700` | downloaded release files                       |

```sh
sudo install -d -o leonaid -g leonaid -m 0755 /opt/leonaid
sudo install -d -o leonaid -g leonaid -m 0700 /etc/leonaid /etc/leonaid/secrets \
  /var/lib/leonaid /var/lib/leonaid/evidence /var/lib/leonaid/releases
```

`pilot-install` writes the Twenty key into `production.env` with an atomic
rename, so `leonaid` must own `/etc/leonaid`.

## Check out the release

As `leonaid`, download the release files and check out exactly the commit
named in `release-images.env`:

```sh
cd /var/lib/leonaid/releases
curl -fsSLO https://github.com/BjoernSchotte/leonaid/releases/download/vYYYY.M.N/release-images.env
curl -fsSLO https://github.com/BjoernSchotte/leonaid/releases/download/vYYYY.M.N/release-manifest.json
git clone https://github.com/BjoernSchotte/leonaid.git /opt/leonaid
commit=$(sed -n 's/^LEONAID_RELEASE_COMMIT=//p' release-images.env)
git -C /opt/leonaid checkout --detach "$commit"
```

Every `pilot-*` command compares the checkout with `LEONAID_RELEASE_COMMIT`.

## Generate the production secrets

As `leonaid` in `/opt/leonaid`:

```sh
./leonaid pilot-secrets --output /etc/leonaid/production.env
```

The command fills every random secret of `infra/pilot/production.env.example`
with a fresh, distinct value, writes the file with mode `0600` and never
overwrites an existing file. It lists the keys that you still fill in by hand:

- the tenant ID in `LEONAID_COMPOSE_PROJECT`, `RUSTFS_BUCKET` and
  `RESTIC_REPOSITORY`;
- the eight lines from `release-images.env` (replace the template lines);
- domains, `CADDY_ACME_EMAIL`, `MAIL_*` and the SMTP account;
- the S3 endpoint and bucket in `RESTIC_REPOSITORY`.

Keep `TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL`. `pilot-install`
creates the real key.

Then create the remaining secret files with mode `0600`:

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

The bootstrap file becomes the first Twenty administrator. Use a lower-case
address and a password of at least 16 letters or digits. Store both in the
club's password manager.

Alertmanager runs as user `nobody` (UID 65534) and must read the two URL
files. Hand them over read-only:

```sh
sudo chown 65534:65534 /etc/leonaid/secrets/alert-webhook-url /etc/leonaid/secrets/alert-heartbeat-url
sudo chmod 0400 /etc/leonaid/secrets/alert-webhook-url /etc/leonaid/secrets/alert-heartbeat-url
```

## Log in to the container registry

Skip this step when the release images are public. Otherwise, as `leonaid`,
log in with a GitHub token that has only `read:packages`:

```sh
docker login ghcr.io -u <github-user>
```

## Run the first installation

As `leonaid` in `/opt/leonaid`:

```sh
./leonaid pilot-install \
  --env-file /etc/leonaid/production.env \
  --release-manifest /var/lib/leonaid/releases/release-manifest.json \
  --twenty-bootstrap-file /etc/leonaid/twenty-bootstrap.env \
  --password-file /etc/leonaid/secrets/restic-password \
  --credentials-file /etc/leonaid/secrets/restic-backend.env
```

`pilot-install` refuses to run when the Compose project already has volumes
or containers, when a secret file is readable by others or lies in the
checkout, or when the Twenty key is no longer pending. It then:

- checks the configuration, the release manifest, the pilot decisions and the
  doctor for a first install;
- starts only Twenty and its datastores, without the proxy and therefore
  without public access;
- creates the Twenty workspace, schema, roles and the least-privilege API key
  and verifies the key;
- confirms the administrator's e-mail address through Twenty's own
  verification, because production Twenty refuses unverified users;
- writes the key into `production.env` (mode `0600` stays);
- starts the full stack with e-mail verification on and signs in as the
  administrator to prove it;
- creates the first encrypted backup, starts monitoring and runs the full
  doctor.

When a step fails, the containers and volumes stay for diagnosis. The error
message shows the `docker compose ... down --volumes` command that removes
them before a new attempt. If the key was already written, set
`TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL` again; the message says so.

## Schedule the daily backup

The doctor and the `LeonAidBackupStale` alert require a backup younger than
26 hours. Install the systemd units from the checkout:

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

The timer runs daily at 02:30 with up to 45 minutes of random delay. It
catches up a missed run after a reboot. Adjust the paths in
`/etc/leonaid/backup.env` if your layout differs.

## Set up the heartbeat and the uptime check

Prometheus raises the alert `LeonAidWatchdog` all the time. Alertmanager
sends it every five minutes to the heartbeat URL and nowhere else. When the
server, Prometheus or Alertmanager stops, the pings stop and the external
service alarms.

- **Heartbeat:** create a check with a period of 5 minutes and a grace time of
  10 minutes. Its ping URL belongs in `alert-heartbeat-url`.
- **Uptime:** let an external monitor request `https://<portal-domain>/_health`
  every 1 to 5 minutes and expect the body `ready`. Send its alarms to a
  channel that does not depend on this server.

`pilot-deploy` and `pilot-release` do not restart monitoring. Afterwards, run
`./leonaid pilot-monitoring --env-file /etc/leonaid/production.env` so the
exporter uses the new release image.

:::note[Further CRM users]
Production Twenty requires verified e-mail addresses but has no mail
transport configured in this release. `pilot-install` verifies only the
first administrator. Plan a mail transport for Twenty before you invite
further CRM users.
:::

## Next steps

- Deploy later releases: [Deploy a pilot installation](/en/ops/how-to/deploy-pilot/)
  and the release runbook `infra/pilot/RELEASE-RUNBOOK.md`.
- Practise a restore: [Back up and restore](/en/ops/how-to/backup-and-restore/).
- Upgrades and rollbacks: [Upgrade and roll back](/en/ops/how-to/upgrade-and-rollback/).
- Diagnose problems: [Troubleshoot](/en/ops/how-to/troubleshoot/).
