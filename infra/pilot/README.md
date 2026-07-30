# Pilot-Betrieb

Diese additive Konfiguration härtet den bestehenden LeonAid-Core für genau
eine Staging- oder Produktionsinstallation. Sie baut keine Images auf dem
Server und veröffentlicht ausschließlich Caddy auf Port 80/443.

## Umgebungsgrenze

Staging und Produktion erhalten jeweils eigene:

- Domains für Portal und Twenty;
- Compose-Projekte und damit eigene Netzwerke, Volumes und Datenbanken;
- RustFS-Buckets und Restic-Repositories;
- Anwendungs-, Datenbank-, Twenty-, RustFS- und SMTP-Secrets;
- SMTP-Zugänge und Absender.

`LEONAID_DEPLOYMENT_STAGE`, `LEONAID_COMPOSE_PROJECT` und `RUSTFS_BUCKET`
müssen dieselbe Umgebung benennen. Der Deployment Doctor blockiert
Verwechslungen. Eine Installation für einen weiteren Club ist eine weitere
vollständig getrennte Umgebung.

## Private Konfiguration

`production.env.example` ist nur eine sichere Vorlage. Die ausgefüllte Datei:

1. liegt außerhalb des Git-Repositorys;
2. gehört ausschließlich dem Betriebsaccount und hat Modus `0600`;
3. enthält für jeden Secret-Namen einen zufälligen, eigenen Wert;
4. referenziert ausschließlich digest-gepinnte Release-Images;
5. bindet `LEONAID_RELEASE_COMMIT` an den freigegebenen vollständigen Git-SHA;
6. verwendet ein externes Restic-Ziel.

Die Datei darf weder in Logs noch in öffentliche CI-Artefakte gelangen.
Container erhalten nur die für ihren Prozess benötigten Werte. Der öffentliche
Evidence-Report enthält ausschließlich Status und Fehlercodes.

Release, Migration, Promotion und Rollback folgen dem
[`RELEASE-RUNBOOK.md`](RELEASE-RUNBOOK.md). Produktion akzeptiert nur ein
Manifest, das zuvor mit exakt demselben SHA in Staging verifiziert wurde.
Pilotnutzer, Rollenwechsel, Offboarding, datensparsames Feedback und die
Support-Code-Strecke folgen dem
[`ONBOARDING-SUPPORT-RUNBOOK.md`](ONBOARDING-SUPPORT-RUNBOOK.md).
Der tägliche technische Pilotcheck und der sanitizte JSON-Report folgen dem
[`LIVE-PILOT-RUNBOOK.md`](LIVE-PILOT-RUNBOOK.md).
Technisches Readiness-Dossier, privates Abnahmeprotokoll und ausdrückliche
Milestoneentscheidung folgen dem
[`PILOT-ACCEPTANCE-RUNBOOK.md`](PILOT-ACCEPTANCE-RUNBOOK.md).
Produktive Absenderidentitäten, öffentlicher DNS-Check, Bounce-/Complaint-Weg,
Rotation und Provider-Wiederanlauf folgen dem
[`MAIL-RUNBOOK.md`](MAIL-RUNBOOK.md).
Der einmalige Excel-Intake, Dry Run, Konfliktentscheidungen, Vier-Augen-Apply
und Verify folgen dem [`IMPORT-RUNBOOK.md`](IMPORT-RUNBOOK.md).

## Compose- und Release-Prüfung

Vor einem Start wird die effektive Konfiguration erzeugt und geprüft:

```sh
docker compose \
  --project-name leonaid-staging-club-111 \
  --env-file /etc/leonaid/staging.env \
  --file infra/compose/compose.yml \
  --file infra/pilot/compose.yml \
  config --format json
```

Der Vertrag blockiert Builds auf dem Zielsystem, ungepinnte Images,
Live-Code-Mounts, zusätzliche Hostports, öffentliche Datennetze,
Loopback-URLs, Mailpit und Default-Secrets. Der Operator startet oder
aktualisiert die Umgebung ausschließlich mit dem gebundenen Release-Manifest:

```sh
./leonaid pilot-deploy \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest .local/pilot/evidence/release-2026.1.0.json
```

Der Befehl verifiziert vor dem Start Checkout, Manifest, effektive
Compose-Images und alle für `pilot-deploy` fälligen Entscheidungen. Er
verwendet ausschließlich `up --no-build --pull missing`, wartet auf alle
Healthchecks und führt danach den vollständigen Deployment Doctor aus. Ein
Manifest-/Compose-Drift erreicht den Start nicht.

Die vollständige technische Promotion mit frischem Backup, Wartungsmodus,
expliziten Twenty-/Core-Migrationen und sequenziellem Release-Ledger läuft
über:

```sh
./leonaid pilot-release \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --evidence-id PILOT-RELEASE-STAGING-2026-01
```

Die Evidence-ID referenziert den privaten fachlichen Browser- und
Dokumentnachweis für denselben Manifest-SHA; sie ersetzt ihn nicht.
Produktion wird vor jeder Mutation blockiert, solange genau dieser SHA nicht
als `staging_verified` im Ledger steht.

## Backup und Restore

Produktive Sicherungen laufen ebenfalls ausschließlich durch einen
Doctor-geschützten Operatorbefehl:

```sh
./leonaid pilot-backup \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env
```

Ein Recovery Drill benötigt ein frisches `leonaid-restore-*`-Projekt, ein
separates Ziel-Environment und die exakte Bestätigung. Der Zielstart ist
buildfrei:

```sh
./leonaid pilot-restore \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --target-env-file /etc/leonaid/restore-drill-2026-07.env \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --confirm RESTORE:leonaid-restore-drill-2026-07
```

Quell- und Ziel-Environment müssen dasselbe externe Restic-Repository
referenzieren. Bestehende Zielcontainer oder -volumes sowie eine abweichende
Bestätigung blockieren den Restore vor einer Mutation.

## Deployment Doctor

Für eine reine Diagnose und danach vor jedem weiteren produktiven Gate:

```sh
./leonaid pilot-doctor \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --gate pilot-deploy
```

Der Doctor prüft ohne Secret-Ausgabe:

- private Dateirechte, getrennte Secrets, Stage-/Projekt-/Bucket-Grenzen;
- freigegebenen Commit, Digests, Compose-Ports, Netze und Mounts;
- externes Backupziel, Manifest-Inventar und maximal 26 Stunden Backupalter;
- mindestens 5 GiB freien Speicher;
- DNS-Auflösung, Hostname-validiertes TLS und mindestens 14 Tage
  Zertifikatsrestlaufzeit;
- HSTS, CSP und weitere Sicherheitsheader;
- Portal, API-/Datenbank-Readiness, Twenty und Mail-Provider;
- Uhrversatz gegen den `Date`-Header des externen Mail-Providers;
- alle für das gewählte Gate fälligen fachlichen Entscheidungen.

Exit `0` bedeutet bereit, `1` einen technischen Blocker, `2` offene
Entscheidungen und `3` eine fachliche STOP-Entscheidung. `--json` liefert
denselben Status maschinenlesbar. `--deployment-only` existiert nur für
Diagnose und Tests; produktive Befehle verwenden immer den vollständigen
Doctor.

## TLS, Header und Erneuerung

Caddy beschafft und erneuert öffentlich vertrauenswürdige Zertifikate
automatisch. Port 80 bleibt für ACME und die permanente HTTPS-Weiterleitung
erreichbar. HSTS wird erst nach dem erfolgreichen Staging-Nachweis auf die
Produktionsdomains übernommen. Die Caddy-Daten- und Konfigurationsvolumes
bleiben persistent; ein Zertifikatsfehler ist ein Doctor-Blocker.

Der noch offene reale Staging-Nachweis muss die öffentlichen DNS-Einträge, die
vollständige Vertrauenskette, Sicherheitsheader und eine beobachtete
Erneuerung bzw. einen dokumentierten Renewal-Dry-Run enthalten.

## Abbruch und Aufräumen

Diagnose zuerst:

```sh
docker compose \
  --project-name leonaid-staging-club-111 \
  --env-file /etc/leonaid/staging.env \
  --file infra/compose/compose.yml \
  --file infra/pilot/compose.yml \
  ps
```

Ein fehlgeschlagener erstmaliger Staging-Leerstart darf mit dem exakten
Projektnamen inklusive Volumes entfernt werden. Für Produktion ist das Löschen
von Volumes verboten; dort folgt ein Rollback ausschließlich dem
Backup-/Restore-Runbook aus PILOT-041.
