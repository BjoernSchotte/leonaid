---
title: Install LeonAid on a fresh VPS
description: Prepare an empty Ubuntu or Debian server and run the first installation with mail, daily backups, the scheduled CRM repair, a heartbeat and an uptime check.
docId: DOC-P039
audience: [ops]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: ee30ab95b4f0c45d863c5e09fa12783583a3475f
reviewer: Björn Schotte
---

This guide takes an empty virtual server to a running LeonAid installation for
one club. It ends with `./leonaid pilot-install`, a daily backup timer, the
scheduled CRM match key repair and an external heartbeat. Later releases follow
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
- **DNS:** one name for the portal (for example `portal.club.org`). The CRM
  has no public name; the system administrator opens it through an SSH
  tunnel (see [Open the CRM](#open-the-crm)).
- **Backup target:** an S3-compatible bucket at another provider. Never store
  backups only on the same server.
- **Mail:** an SMTP account for the club's sender domain. LeonAid and
  Twenty CRM both send through it. The relay needs a certificate from a
  public CA, and the server must reach it outbound on port 465 (implicit
  TLS). Twenty sends mail only over implicit TLS; with port 587 (STARTTLS)
  only LeonAid sends mail.
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
LeonAid publishes only the proxy on 80 and 443. The Twenty server listens on
`127.0.0.1:TWENTY_ADMIN_PORT` (default 3020) for the admin SSH tunnel, which
the internet cannot reach. All databases, RustFS and monitoring stay on
internal Docker networks. After the installation,
`docker ps --format '{{.Names}} {{.Ports}}'` must show the proxy on 80/443 and
`twenty-server` only on `127.0.0.1`.

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

Create an `A` record (and an `AAAA` record if the server has IPv6) for the
portal name. Check it before the installation:

```sh
dig +short portal.club.org
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
- `LEONAID_CLUB_NAME`, the club name the admin rail shows (the API does not
  start in production without it);
- the portal domain, `CADDY_ACME_EMAIL`, `MAIL_*` and the SMTP account;
- `TWENTY_ADMIN_PORT` only if port 3020 is taken on the server;
- `TWENTY_MAIL_FROM_ADDRESS` and `TWENTY_MAIL_FROM_NAME`, the sender of
  Twenty's own mail (see [Mail for LeonAid and Twenty](#mail-for-leonaid-and-twenty));
- the S3 endpoint and bucket in `RESTIC_REPOSITORY`.

Keep `TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL`. `pilot-install`
creates the real key.

### Mail for LeonAid and Twenty

You configure the SMTP relay once with the `MAIL_SMTP_*` keys. The core
worker sends login codes, invitations and invoices through it. Twenty
sends address verification and password reset mail through the same
relay. Both senders reach the relay only through the dedicated
`mail-egress` network; all other internal networks have no route out.

| `MAIL_SMTP_MODE` | `MAIL_SMTP_PORT` | Core worker | Twenty |
| ---------------- | ---------------- | ----------- | ------ |
| `tls` (template default) | 465 | implicit TLS | implicit TLS |
| `starttls` | not 465, usually 587 | requires STARTTLS | sends no mail |
| `plain` | – | refused in production | refused in production |

Both verify the relay certificate against the public CA store, so
`MAIL_SMTP_CA_FILE` is refused in the pilot. Pilot Doctor refuses a port
that does not match the mode: `tls` needs port 465, `starttls` any other
port.

`TWENTY_MAIL_FROM_ADDRESS` must be a bare address in the domain of
`MAIL_FROM`, for example `crm@club.org`. Then the SPF, DKIM and DMARC
records of the sender domain cover Twenty's mail as well.

:::caution[Twenty mail needs implicit TLS]
Twenty 2.54 cannot enforce STARTTLS: its SMTP client upgrades only when the
relay offers STARTTLS, and an attacker on the path can suppress the offer
and read the mail. Twenty has no setting to require it. LeonAid therefore
starts Twenty with its SMTP driver only for `MAIL_SMTP_MODE=tls`. With
`starttls`, Twenty uses its logger driver and sends nothing, and
`pilot-doctor` prints a warning (not an error). LeonAid's own mail is not
affected. Use port 465 when your provider offers it.
:::

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
  without public access (Twenty itself is never public);
- creates the Twenty workspace, schema, roles and the least-privilege API key
  and verifies the key;
- confirms the administrator's e-mail address through Twenty's own
  verification, because production Twenty refuses unverified users;
- writes the key into `production.env` (mode `0600` stays);
- starts the full stack with e-mail verification on (and Twenty's SMTP
  driver when `MAIL_SMTP_MODE=tls`), and signs in as the administrator to
  prove it;
- creates the first encrypted backup, starts monitoring and runs the full
  doctor.

When a step fails, the containers and volumes stay for diagnosis. The error
message shows the `docker compose ... down --volumes` command that removes
them before a new attempt. If the key was already written, set
`TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL` again; the message says so.

## Open the CRM

The Twenty CRM is for the system administrator only. It has no public
domain, and the proxy does not forward to it. `twenty-server` listens on
`127.0.0.1:TWENTY_ADMIN_PORT` of the server. Print the tunnel command as
`leonaid`:

```sh
./leonaid crm-admin --env-file /etc/leonaid/production.env \
  --ssh-target admin@portal.club.org
```

The command checks that `twenty-server` publishes its port on `127.0.0.1`
only and prints the two steps:

```sh
ssh -N -L 3020:127.0.0.1:3020 admin@portal.club.org
```

Keep the tunnel open and browse to `http://localhost:3020` on your
workstation. Twenty builds its links from
`SERVER_URL=http://localhost:TWENTY_ADMIN_PORT`, so the local port must be
the same as on the server. Sign in with the bootstrap administrator.

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

## Schedule the CRM match key repair

LeonAid finds companies and people in Twenty through a stored match key.
Records that someone creates or renames directly in Twenty (UI, CSV
import) have no key, or a stale one, until the repair runs. Two timers
run `./leonaid pilot-repair-crm-match-keys` in the running API container:

- `leonaid-crm-repair.timer` every 15 minutes with `--changed-within 30`:
  the window overlaps the previous run, so one late or skipped run loses
  nothing;
- `leonaid-crm-repair-full.timer` daily at 04:00 (up to 30 minutes of
  random delay) without a window: it repairs everything the short window
  cannot see, for example after a long maintenance or host downtime.

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

A successful run ends with `crm-match-keys: OK:` and the number of
scanned and repaired records. During maintenance mode (for example
inside `pilot-release`) Twenty is stopped on purpose. The command then
reports `SKIPPED` and exits with success, so the unit does not fail. If
maintenance starts during a run, the run also ends as `SKIPPED`; the next
run and the nightly full run catch up. It fails when the API container
does not run or Twenty refuses the request; `journalctl` shows the
error code without secrets.

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
Production Twenty requires verified e-mail addresses. `pilot-install`
verifies the first administrator directly. A further administrator also
needs SSH access for the tunnel and receives the verification mail through
the relay, which requires `MAIL_SMTP_MODE=tls`. Check the path once after
the installation: open the CRM through the tunnel, request a password reset
for the administrator on the sign-in page and confirm that the mail arrives
from `TWENTY_MAIL_FROM_ADDRESS`. If it does not, `docker compose ... logs
twenty-worker` shows the SMTP error.
:::

## Next steps

- Deploy later releases: [Deploy a pilot installation](/en/ops/how-to/deploy-pilot/)
  and the release runbook `infra/pilot/RELEASE-RUNBOOK.md`.
- Practise a restore: [Back up and restore](/en/ops/how-to/backup-and-restore/).
- Upgrades and rollbacks: [Upgrade and roll back](/en/ops/how-to/upgrade-and-rollback/).
- Diagnose problems: [Troubleshoot](/en/ops/how-to/troubleshoot/).
