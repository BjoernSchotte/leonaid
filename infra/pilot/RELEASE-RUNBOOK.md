# Pilot-Release, Migration und Rollback

Dieses Runbook ist die verbindliche Betriebsstrecke für ein LeonAid-Release.
Es verbindet die gehärtete Pilot-Topologie, den Deployment Doctor, den
verschlüsselten Recovery Point, den Wartungsmodus und die bestehenden
Core-/Twenty-/RustFS-Migrationen. Es ersetzt keine fachliche Freigabe und
keine der in `specs/leonaid-pilot/DECISIONS.md` fälligen Entscheidungen.

## Rollen und harte Grenzen

- **Release-Verantwortlicher** baut, scannt und publiziert die vier
  LeonAid-Images in CI und erzeugt das Release-Manifest.
- **Operator** promoted exakt dieses Manifest zuerst nach Staging und erst
  nach grünen Gates nach Produktion.
- **Fachliche Freigabe** bestätigt Golden Journey, Rechnungsinhalt und
  relevante Konfiguration; sie arbeitet nicht direkt in der Datenbank.
- Auf dem Zielsystem laufen ausschließlich `pull`, `up --no-build`,
  dokumentierte Migrationen, Smokes und bei Bedarf Restore. Ein Build,
  Live-Code-Mount oder spontanes Auflösen neuer Abhängigkeiten ist verboten.
- Ein fehlgeschlagener Migrations-, Readiness- oder Fach-Smoke hebt den
  Wartungsmodus nicht auf.

## 1. Manifest aus der effektiven Konfiguration erzeugen

Der freigegebene Commit, die private `0600`-Environment-Datei und alle
publizierten Images mit Tag **und** Digest müssen bereits feststehen. Zuerst
wird die effektive Compose-Konfiguration geschrieben:

```sh
docker compose \
  --project-name leonaid-staging-club-111 \
  --env-file /etc/leonaid/staging.env \
  --file infra/compose/compose.yml \
  --file infra/pilot/compose.yml \
  config --format json >.local/pilot/evidence/staging-compose.json
```

Das Manifest übernimmt die zwölf tatsächlich verwendeten Service-Images und
bindet zusätzlich:

- vollständigen Git-Commit und Release-ID;
- alle Alembic-Revisionen samt SHA-256 und erwarteten Head;
- OpenAPI, Kompatibilitätsmatrix und Typst-Rechnungstemplate samt SHA-256;
- Golden-Dataset- und Templateversion;
- erforderliche Gates und Rollbackgrenze je zustandsbehafteter Komponente.

```sh
./leonaid pilot-release-manifest create \
  --release-id pilot-2026-01 \
  --version 2026.1.0 \
  --git-commit "$(git rev-parse HEAD)" \
  --deployment-mode production \
  --compose-config .local/pilot/evidence/staging-compose.json \
  --output .local/pilot/evidence/release-2026.1.0.json

./leonaid pilot-release-manifest verify \
  --manifest .local/pilot/evidence/release-2026.1.0.json \
  --expected-commit "$(git rev-parse HEAD)" \
  --compose-config .local/pilot/evidence/staging-compose.json
```

`production` akzeptiert kein lokales Image, keinen schwebenden Tag und keinen
Digest ohne Tag. Eine abweichende Migration, ein verändertes Template oder
eine Differenz zwischen Manifest und Compose blockiert vor dem ersten Write.
`pilot-deploy` ist der technische, manifestgebundene Start/Reconcile ohne
Migration. Er kann für den ersten Staging-Aufbau und die fachliche
Vorabnahme verwendet werden:

```sh
./leonaid pilot-deploy \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest .local/pilot/evidence/release-2026.1.0.json
```

`pilot-deploy` prüft die fälligen Entscheidungen vor dem Start, verwendet
kein `build`, wartet auf den realen Healthzustand und führt anschließend den
vollständigen Doctor gegen die laufende Umgebung aus.

Die eigentliche Promotion erfolgt ausschließlich mit `pilot-release`. Der
Befehl verifiziert Manifest und Doctor, schreibt das Started-Ereignis,
erzeugt einen frischen verschlüsselten Recovery Point, aktiviert den
Wartungsmodus, führt die expliziten Twenty- und Core-Migrationen aus, startet
buildfrei und hebt den Wartungsmodus erst nach grünem Abschluss-Doctor auf.
`--evidence-id` ist die Referenz auf den privaten, bereits abgeschlossenen
fachlichen Browser-/Dokumentnachweis für genau diesen Manifest-SHA; der
Befehl selbst simuliert keine menschliche Abnahme.

## 2. Staging

1. Mit `pilot-deploy` das freigegebene Manifest erstmals in Staging
   bereitstellen.
2. Vollständige Golden Journey, relevante Dokumente und fachliche
   Konfiguration prüfen; den privaten Beleg fest mit Manifest-SHA und
   Evidence-ID verbinden.
3. Anschließend die technische Promotion desselben Manifests ausführen:

```sh
./leonaid pilot-release \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/staging-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --evidence-id PILOT-RELEASE-STAGING-2026-01 \
```

Der Befehl erzwingt die oben beschriebene Reihenfolge und protokolliert
`staging_started` sowie erst nach dem grünen Abschluss-Doctor
`staging_verified`. Das Ledger enthält nur Sequenz, Zeitpunkt, Release-ID,
Manifest-SHA, Ereignis, Ergebnis und externe Evidence-ID.

## 3. Produktion

Vor `production_started` prüft das Ledger, dass **derselbe Manifest-SHA**
bereits als `staging_verified` vorliegt. Danach gilt dieselbe Reihenfolge wie
in Staging. Ein neues Manifest, auch bei vermeintlich identischen Images,
beginnt wieder bei Staging.

Vor jedem Write werden festgehalten:

- Wartungsfenster und Operator;
- Manifest-SHA und freigegebener Commit;
- externer, integritätsgeprüfter Recovery Point;
- private Evidence-ID der Freigabe.

Produktion baut keine Images und führt keine ungebundene Migration `head`
aus. Zielrevision, Dateien und SHAs stammen aus dem bereits verifizierten
Manifest.

```sh
./leonaid pilot-release \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/production-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --evidence-id PILOT-RELEASE-PRODUCTION-2026-01
```

Fehlt im Ledger das `staging_verified` desselben Manifest-SHA, endet der
Befehl vor Started-Ereignis, Backup, Wartungsmodus und Deployment.

## 4. Fehler und Rollback

Bei einem Fehler:

1. Falls der Wartungsmodus bereits angefordert wurde, dessen Zustand prüfen
   und ihn aktiv lassen. Ein Fehler vor dem Backup aktiviert ihn nicht; ein
   fehlgeschlagener Abschluss-Doctor kann nach bereits beendetem
   Wartungsmodus auftreten und wird ausdrücklich so gemeldet.
2. `production_failed` mit stabiler Fehlerklasse und privater Evidence-ID
   protokollieren; keine Logs oder Payloads ins öffentliche Ledger kopieren.
3. Fehlerhaftes Projekt stoppen. Keine manuelle Datenkorrektur durchführen.
4. `rollback_started` protokollieren.
5. Nach den Grenzen aus
   [`../upgrade/README.md`](../upgrade/README.md) alle betroffenen
   Zustandskomponenten gemeinsam aus dem frischen Recovery Point in das
   explizit bestätigte Ziel restaurieren.
6. Quellrelease mit dessen unverändertem Manifest und `--no-build` starten.
7. Golden Snapshot, Dokument-SHAs, Readiness und Browser-Journey wiederholen.
8. Erst bei vollständigem Erfolg Wartungsmodus deaktivieren und
   `rollback_verified` protokollieren.

Ein Operator benötigt dafür keinen SQL-Zugriff. Direkte Datenbankarbeit gilt
als fehlgeschlagener Betriebsnachweis.

## Reproduzierbarer technischer Nachweis

```sh
./leonaid test-pilot-release
```

Der Test verwendet keine Mocks. Er führt Release v1 und v2 mit realem Core
PostgreSQL, Twenty, RustFS, Restic, Typst-PDFs und Chromium aus. Er erzeugt
eine echte fehlende Alembic-Revision, beweist die fortbestehende
Schreibsperre, restauriert, promoted denselben Manifest-SHA erneut, erzeugt
zusätzlich einen systemübergreifenden Post-Smoke-Fehler und restauriert
nochmals. Beide isolierten Compose-Projekte und ihre Volumes werden
anschließend entfernt. Sanitizte lokale Evidence liegt unter
`.artifacts/pilot043/`.
