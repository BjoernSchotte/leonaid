# Upgrade und Rollback

Dieses Runbook beschreibt den fail-closed Upgradepfad für LeonAid Core,
Twenty und RustFS. Es ergänzt das
[`Backup-/Restore-Runbook`](../backup/README.md). Ein Upgrade ohne frischen,
integritätsgeprüften Recovery Point ist nicht zulässig.

## Verbindliche Vorbereitung

1. Quell- und Zielimages mit Tag und Digest in
   `infra/locks/external-systems.lock` und `infra/locks/images.env` pinnen.
2. Release Notes und Migrationen lesen und die Entscheidung in
   `compatibility-matrix.json` aktualisieren.
3. `./leonaid check` auf einem sauberen Checkout ausführen.
4. `./leonaid test-upgrade` gegen einen Golden-Data-Klon ausführen.
5. Wartungsfenster, Verantwortlichen und geprüften Recovery Point
   protokollieren.

Die maschinenlesbare Matrix verweigert fehlende Release Notes, ungeprüfte
Migrationen, unvollständige Gates, ungenaue Images und Komponenten ohne
Backup-Restore-Strategie.

## Wartungsgrenze

```sh
infra/upgrade/maintenance.sh enable
infra/upgrade/maintenance.sh status
```

Der Modus legt seinen Zustand in einem eigenen Compose-Volume ab. FastAPI
beantwortet lesende Requests weiterhin, weist `POST`, `PUT`, `PATCH` und
`DELETE` jedoch mit `503 maintenance_mode` und `Retry-After` ab. Core-Worker,
Twenty Server und Twenty Worker werden gestoppt. Erst wenn die Abhängigkeiten
wieder bereit sind, hebt folgender Befehl die Schreibsperre auf:

```sh
infra/upgrade/maintenance.sh disable
```

## Reihenfolge im Änderungsfenster

1. Wartungsmodus aktivieren und die Schreibsperre mit einem echten Request
   verifizieren.
2. Verschlüsselten Recovery Point mit `./leonaid backup` erzeugen und prüfen.
3. RustFS-Zielimage starten und Healthcheck abwarten.
4. Twenty-Zielserver einmal starten, damit dessen Entrypoint die
   Schema-Voraussetzungen initialisiert.
5. Twenty Server wieder stoppen und beide offiziellen Befehle fail-closed
   ausführen:

   ```sh
   docker compose --env-file .env.local -f infra/compose/compose.yml \
     run --rm --no-deps --entrypoint yarn twenty-server \
     command:prod run-instance-commands
   docker compose --env-file .env.local -f infra/compose/compose.yml \
     run --rm --no-deps --entrypoint yarn twenty-server \
     command:prod upgrade
   ```

6. Twenty Server/Worker und LeonAid starten; Images, Schema und Healthchecks
   prüfen.
7. Contract-Suite, Golden-Snapshot und Browser-Journey ausführen.
8. Erst danach den Wartungsmodus deaktivieren.

Twenty schreibt fehlgeschlagene Entrypoint-Upgrades nur als Warnung und kann
trotzdem gesund erscheinen. LeonAid akzeptiert deshalb weder den Healthcheck
noch den Entrypoint allein als Migrationsbeweis: Beide Befehle müssen mit
Exitcode 0 enden, das erwartete Zielschema muss vorhanden sein und der
fachliche Contract muss unverändert bestehen.

## Rollbackgrenzen

- **Twenty:** Nach dem ersten Instance- oder Workspace-Migrationsschritt wird
  kein älteres Image gegen die vorwärts migrierte Datenbank gestartet.
  Rollback bedeutet Restore von Twenty-PostgreSQL und Twenty-Dateien aus
  demselben Recovery Point.
- **RustFS:** Vor einem Schreibzugriff der Zielversion ist ein Binär-Rollback
  möglich. Danach wird das vollständige RustFS-Volume restauriert.
- **LeonAid Core:** Nach `alembic upgrade head` wird kein älterer Core gegen
  das neue Schema behauptet. Core-PostgreSQL wird aus dem Recovery Point
  wiederhergestellt.

Bei Fehlern bleibt die Schreibsperre aktiv. Das fehlerhafte Projekt wird
gestoppt, nicht weiter beschrieben und nach
[`infra/backup/README.md`](../backup/README.md) in ein neues, explizit
bestätigtes Compose-Projekt restauriert. Erst Golden-Contract, Dokument-
Hashes, Sessions und Browser-Journey geben die Umgebung wieder frei.

## Reproduzierbarer PoC-Nachweis

```sh
./leonaid test-upgrade
```

Der Test verwendet keine Mocks. Er startet Twenty 2.23.2 und RustFS
1.0.0-beta.10 mit echten Golden Data, aktualisiert auf Twenty 2.24.0 und
RustFS 1.0.0-beta.11, prüft Contracts und Chromium vor/nach dem Upgrade,
beschädigt einen separaten Zielklon absichtlich und restauriert ihn aus dem
verschlüsselten Recovery Point. Geheimnisfreie Ergebnisse liegen unter
`.artifacts/poc113/`.

Der Pilot-Release-Nachweis ergänzt diesen Komponentenvertrag um ein
unveränderliches Release-Manifest, identische Staging-/Produktionspromotion,
einen real fehlgeschlagenen Alembic-Lauf und ein secretsfreies
Promotion-Ledger:

```sh
./leonaid test-pilot-release
```

Die Betriebsstrecke ist in
[`../pilot/RELEASE-RUNBOOK.md`](../pilot/RELEASE-RUNBOOK.md) beschrieben.
