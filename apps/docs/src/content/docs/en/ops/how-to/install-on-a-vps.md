---
title: Install LeonAid on a fresh VPS
description: Prepare an empty Ubuntu or Debian server and run the first installation with mail, daily backups, the scheduled CRM repair, a heartbeat and an uptime check.
docId: DOC-P039
audience: [ops]
diataxis: how-to
contentRevision: 9
reviewedRevision: 9
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
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

Decide first whether the installation uses one host or two:

- **One host** (`portal.club.org`): members, editors and public pages share
  one name.
- **Admin host and public host** (recommended): members and editors use
  `app.club.org`; public pages, campaign pages, surveys and the legal pages
  stay on `club.org`. An existing single host becomes the public host, so
  printed QR codes and mailed links keep working. Old member links
  (`/admin/`, `/app/`, `/login`) redirect to the admin host.

Create an `A` record (and an `AAAA` record if the server has IPv6) for every
name: the one host, or the admin host, the public host and each further name
of the public host (for example `www.club.org`). Check them before the
installation:

```sh
dig +short app.club.org
dig +short club.org
```

Caddy requests the TLS certificates on the first start. Port 80 must be
reachable from the internet for that.

**Domains for single campaigns** (`krapfentaxi.org`) need no change to the
installation. The system administration adds them under **System** ›
**Domains**; the club creates `A`/`AAAA` (own domain) or a `CNAME`
(subdomain) pointing to this server. Caddy gets their certificate on the
first request, but only for a domain LeonAid has checked (at most ten new ones
per hour). Port 80 must stay open for this, and a `CAA` record of the domain
must allow `letsencrypt.org`. Every `A`/`AAAA` record of the domain must
name an address of this server; LeonAid takes the addresses of the admin host
or `LEONAID_SITE_HOST_EDGE_ADDRESSES`. LeonAid also asks public DNS
servers (default `1.1.1.1` and `9.9.9.9`, `LEONAID_SITE_HOST_PUBLIC_RESOLVERS`);
outgoing port 53 must be open for this. A domain whose certificate has less
than 20 days left fails the check. The outside proof:

```sh
python3 tools/site_hosts/acme_probe.py krapfentaxi.org --admin app.club.org
```

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
# Admin host app.club.org and public host club.org (plus www.club.org):
./leonaid pilot-secrets --output /etc/leonaid/production.env \
  --public-domain club.org --alias www.club.org
# Or one host only:
./leonaid pilot-secrets --output /etc/leonaid/production.env \
  --public-domain portal.club.org --single-host
```

With `--public-domain` the command also writes every host setting: the
admin host (`app.<domain>`, or `--admin-domain` for another name), the base
URLs of the member mails and of the public links, the allowed origins and
`LEONAID_PROXY_CADDYFILE=Caddyfile.split`. It refuses an admin host equal to
the public host or one of its names. Without `--public-domain` you fill in
the host lines of the template by hand.

The command fills every random secret of `infra/pilot/production.env.example`
with a fresh, distinct value, writes the file with mode `0600` and never
overwrites an existing file. It lists the keys that you still fill in by hand:

- the tenant ID in `LEONAID_COMPOSE_PROJECT`, `RUSTFS_BUCKET` and
  `RESTIC_REPOSITORY`;
- the nine lines from `release-images.env` (replace the template lines);
- `LEONAID_CLUB_NAME`, the club name the admin rail shows (the API does not
  start in production without it);
- the host names, if you did not pass `--public-domain`;
- `CADDY_ACME_EMAIL`, `MAIL_*` and the SMTP account;
- `TWENTY_ADMIN_PORT` only if port 3020 is taken on the server;
- `TWENTY_MAIL_FROM_ADDRESS` and `TWENTY_MAIL_FROM_NAME`, the sender of
  Twenty's own mail (see [Mail for LeonAid and Twenty](#mail-for-leonaid-and-twenty));
- the S3 endpoint and bucket in `RESTIC_REPOSITORY`.

Keep `TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL`. `pilot-install`
creates the real key.

Keep `LEONAID_CMS_ENABLED=false` for the first installation;
`pilot-install` refuses `true`. The campaign pages (`campaign-site`, EmDash
editor) follow after the installation with `pilot-cms-provision` (see
[Set up the campaign pages](#set-up-the-campaign-pages)). With
`LEONAID_CMS_ENABLED=true` every `pilot-*` command adds the campaign site to
the stack, and the release needs `release-manifest-cms.json` instead of
`release-manifest.json`.

With an admin host, every member signs in on `app.club.org` (the session
cookie belongs to one host). The acquisition app lives at
`https://app.club.org/app/`. Nobody has installed it from an older single
host yet; should a device still hold the app of the old host, the public host
replaces its service worker with one that removes itself, and the next visit
lands on the admin host.

The public host sends `Strict-Transport-Security` without
`includeSubDomains`: on the club's main domain it would force HTTPS on every
other name of the club (webmail, intranet, devices) for a year. The admin host
keeps `includeSubDomains`.

### Switch to an admin host

An installation that runs on one host today keeps that host as its public
host; printed and mailed public links stay valid. In this order:

1. Create the DNS record for `app.club.org` and check it with `dig`.
2. In `/etc/leonaid/production.env` set `LEONAID_PUBLIC_BASE_URL` and
   `LEONAID_ALLOWED_ORIGINS` to `https://app.club.org` and add
   `LEONAID_ADMIN_DOMAIN=app.club.org`,
   `LEONAID_PROXY_CADDYFILE=Caddyfile.split`,
   `LEONAID_SITE_BASE_URL=https://club.org` and
   `LEONAID_PUBLIC_ORIGINS=https://club.org` (the old host, unchanged in
   `LEONAID_PUBLIC_DOMAIN`). Further names go into
   `LEONAID_PUBLIC_DOMAIN_ALIASES`, separated by ", ".
3. Run `./leonaid pilot-doctor` with the env file; it refuses inconsistent
   host settings.
4. Deploy with `./leonaid pilot-deploy`. Caddy requests the certificate of
   the admin host on its first start.
5. Run `./leonaid pilot-revoke-sessions --env-file /etc/leonaid/production.env`.
   Old sessions of the single host stay valid on the server until they
   expire; this signs every member out once. Tell the members to sign in on
   `https://app.club.org/`.

### Mail for LeonAid and Twenty

You configure the SMTP relay once with the `MAIL_SMTP_*` keys. The core
worker sends login codes, invitations and invoices through it. Twenty
sends address verification and password reset mail through the same
relay. Both senders reach the relay only through the dedicated
`mail-egress` network; all other internal networks have no route out.

| `MAIL_SMTP_MODE`         | `MAIL_SMTP_PORT`     | Core worker           | Twenty                |
| ------------------------ | -------------------- | --------------------- | --------------------- |
| `tls` (template default) | 465                  | implicit TLS          | implicit TLS          |
| `starttls`               | not 465, usually 587 | requires STARTTLS     | sends no mail         |
| `plain`                  | –                    | refused in production | refused in production |

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

## Set up the campaign pages

The campaign pages and their editor (EmDash) need a database, a media bucket,
a first setup by a LeonAid System Admin and the campaign schema.
`./leonaid pilot-cms-provision` does these four steps on the running
installation. Before it, `pilot-deploy`, `pilot-release` and `pilot-doctor`
refuse `LEONAID_CMS_ENABLED=true` with the hint to run it.

You need:

- a running installation from `pilot-install` and a backup younger than 26
  hours;
- `release-manifest-cms.json` of the same release (from the release files);
- the e-mail address of an active LeonAid System Admin who can sign in now.

As `leonaid` in `/opt/leonaid`:

1. Set `LEONAID_CMS_ENABLED=true` in `/etc/leonaid/production.env`. Until
   the setup in step 3 is complete, `pilot-backup` keeps working and leaves
   the unfinished CMS out (it prints a note); from then on every backup also
   holds the CMS database, its media and its setup state.
2. Start the provisioning:

   ```sh
   ./leonaid pilot-cms-provision \
     --env-file /etc/leonaid/production.env \
     --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
     --release-manifest /var/lib/leonaid/releases/release-manifest-cms.json \
     --system-admin-email admin@club.org
   ```

   The command creates the database role, the database and the media bucket
   with its own access key. Then it allows the EmDash setup for 15 minutes,
   for this System Admin only, and ends with `PENDING` (exit status 75).
   While that grant is open, another `--system-admin-email` is refused with
   the time the grant ends.
3. Within the 15 minutes, the System Admin signs in at
   `https://app.club.org/admin/` (or the one host), opens
   `https://app.club.org/_emdash/admin/setup` and completes the setup. Any
   other account gets a refusal. If EmDash rejects an entry, correct it and
   submit again: a refused setup does not use up the grant.
4. Run the same command again; `--system-admin-email` is no longer needed.
   It installs the campaign schema while the CMS is closed and opens the CMS
   again. The last line is `pilot-cms-provision: OK`.
5. Run `./leonaid pilot-backup` once: the doctor now requires a backup with
   the CMS data. Then `./leonaid pilot-deploy` with
   `release-manifest-cms.json`. Later releases also use the CMS manifest.

Each step first checks its own state. A second run changes nothing and
prints `already` for every step. When a run stops with an error, fix the
cause and run the command again: it continues at the open step.

- **The grant expired** (the setup did not happen within 15 minutes): run
  the command again with `--system-admin-email`. Only an unused grant is
  replaced.
- **"the editor setup started but did not complete"**: a setup request was
  interrupted (for example the CMS restarted during it), so the grant is
  used up. Run the command with `--reset-setup --system-admin-email ...`. It
  stops the campaign site first, so no setup request is still running, and
  withdraws the grant only while the CMS is unused (no completed setup, no
  campaign schema, no media, only LeonAid's own sign-in users). It removes
  those sign-in users too, records the withdrawal in the LeonAid audit log
  and allows the setup again, also for another System Admin.
- **The setup finished, but the grant was not marked** (for example the
  campaign site stopped right after the setup): the next run confirms the
  completed setup against the mapped System Admin, marks the grant complete,
  writes an audit entry and continues.
- **"the CMS setup state cannot be read"** (`pilot-backup`): the backup
  stops instead of leaving the CMS out. Check Docker and the
  `cms-bootstrap-state` volume, then run the backup again.
- **The schema step stopped halfway** (for example a timeout under load):
  run the command again. It finds the parts already installed and installs
  the rest; CMS traffic stays closed until then.
- **"the CMS database exists with another EmDash migration state"**: the
  database was not created by this release. The command does not provision
  over it.
- **"existing CMS bucket policy requires review"** (`emdash-rustfs:
  FAILED`): the bucket `emdash-media` already has a policy. Check who set it;
  the CMS media stay private and get no bucket policy.

Published campaign pages are served at `https://club.org/campaigns/<slug>/`
(or on the one host).

### Switch the CMS off again before it went live

Until the setup is complete you can stop without a restore: set
`LEONAID_CMS_ENABLED=false` again and stop the campaign site:

```sh
docker compose --project-name <project> --env-file /etc/leonaid/production.env \
  --file infra/compose/compose.yml --file infra/pilot/compose.yml \
  --profile emdash stop campaign-site
```

Deploys, releases and backups then run as before; backups leave the
unfinished CMS out. The CMS database and bucket stay; a later
`pilot-cms-provision` continues with them. After the setup is complete,
switching off is refused by `pilot-backup`, because the live CMS data would
be missing from every backup.

## Next steps

- Deploy later releases: [Deploy a pilot installation](/en/ops/how-to/deploy-pilot/)
  and the release runbook `infra/pilot/RELEASE-RUNBOOK.md`.
- Practise a restore: [Back up and restore](/en/ops/how-to/backup-and-restore/).
- Upgrades and rollbacks: [Upgrade and roll back](/en/ops/how-to/upgrade-and-rollback/).
- Diagnose problems: [Troubleshoot](/en/ops/how-to/troubleshoot/).
