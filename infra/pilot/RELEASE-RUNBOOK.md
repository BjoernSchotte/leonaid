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

## 2. Staging

1. `./leonaid pilot-doctor` mit Staging-Environment und aktuellem
   Backupmanifest ausführen.
2. Manifest verifizieren und `staging_started` protokollieren.
3. Images mit `docker compose pull` beziehen; niemals bauen.
4. Wartungsmodus aktivieren und die Schreibsperre mit
   `tools/upgrade/contract.py maintenance` prüfen.
5. Frischen verschlüsselten Recovery Point erzeugen und `restic check`
   erfolgreich abschließen.
6. RustFS-Zielimage starten.
7. Twenty-Zielserver einmal bootstrappen, stoppen und anschließend
   `command:prod run-instance-commands` sowie `command:prod upgrade`
   fail-closed ausführen.
8. Core über `alembic upgrade <Manifest-Head>` migrieren.
9. Alle Services mit `up --detach --no-build --wait` starten.
10. Readiness, Golden Snapshot, Dokument-SHAs und vollständige Golden Journey
    prüfen.
11. Erst danach Wartungsmodus deaktivieren und `staging_verified`
    protokollieren.

Beispiel für das öffentliche, personenbezugsfreie Ereignis:

```sh
./leonaid pilot-release-record \
  --manifest .local/pilot/evidence/release-2026.1.0.json \
  --ledger .local/pilot/evidence/release-ledger.jsonl \
  --event staging_verified \
  --result passed \
  --evidence-id PILOT-RELEASE-STAGING-2026-01 \
  --occurred-at 2026-01-15T19:00:00Z
```

Das Ledger enthält nur Sequenz, Zeitpunkt, Release-ID, Manifest-SHA,
Ereignis, Ergebnis und externe Evidence-ID.

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

## 4. Fehler und Rollback

Bei einem Fehler:

1. Wartungsmodus aktiv lassen.
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
