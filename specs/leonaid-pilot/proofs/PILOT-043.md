# PILOT-043 – Technischer Nachweis

Stand: 2026-07-28
Ergebnis: technische Release-, Migrations- und Rollbackbasis bewiesen;
unabhängiger Operator-Smoke und vollständige Golden Journey je Releasegrenze
bleiben offen.

## Implementierter Vertrag

- `tools/pilot_release/manifest.py` erzeugt ein kanonisches,
  SHA-256-adressierbares Release-Manifest direkt aus der effektiven
  Compose-Konfiguration.
- Das Manifest bindet alle zwölf Laufzeitimages, vollständigen Git-Commit,
  jede Alembic-Migration samt SHA, Core-Head, Golden-Dataset,
  Typst-Rechnungstemplate, OpenAPI, Kompatibilitätsmatrix, Gates und
  Rollbackgrenzen.
- Produktionsmanifeste akzeptieren ausschließlich Images mit Tag und Digest.
  Checkout-, Compose-, Migrations-, Template- oder API-Drift blockiert.
- `tools/pilot_release/promotion.py` führt ein lückenloses,
  personenbezugsfreies JSONL-Ledger. Ein Produktionsereignis wird nur
  akzeptiert, wenn exakt derselbe Manifest-SHA vorher in Staging verifiziert
  wurde.
- [`infra/pilot/RELEASE-RUNBOOK.md`](../../../infra/pilot/RELEASE-RUNBOOK.md)
  beschreibt Build-/Zielgrenze, Wartungsmodus, Recovery Point,
  Migrationsreihenfolge, Smokes und komponentengerechten Restore ohne SQL.

## Realer Test

Ausgeführt:

```text
./leonaid test-pilot-release
```

Ergebnis:

```text
pilot-release-contract: OK: Manifestbindung, Drift, Staging-Promotion und
secretsfreies Ledger bewiesen
upgrade-test: OK: reale Twenty- und RustFS-Upgrades,
upgrade-test:     Wartungsgrenze, Contract/E2E vor und nach dem Upgrade
upgrade-test:     sowie Manifest-Promotion, Migrationsfehler und Recovery
bewiesen
pilot-release-evidence: OK: Promotion, Migrationsfehler, Rollback und
Dokument-SHAs bewiesen
pilot-release-test: OK: zwei reale Releaseversionen, identische Promotion,
pilot-release-test:     Migrationsfehler, Recovery und Rollback bewiesen
```

Der Test verwendet keine Mocks:

1. baut die Testimages einmal vor der Releasegrenze und bindet ihre
   unveränderlichen Image-IDs;
2. startet Release v1 mit Twenty 2.23.2 und RustFS 1.0.0-beta.10;
3. provisioniert Twenty, rendert drei reale Typst-PDFs, seedet Golden Data
   und prüft Dashboard sowie Chromium;
4. erstellt einen verschlüsselten Restic-Recovery-Point und führt
   `restic check` aus;
5. aktiviert Wartungsmodus, stoppt Writer und migriert auf Twenty 2.24.0
   sowie RustFS 1.0.0-beta.11;
6. prüft Release v2 in Staging und protokolliert dessen Manifest-SHA;
7. versucht denselben SHA in einem getrennten Produktionsprojekt, führt
   `alembic upgrade pilot_missing_revision` real aus und beweist Exit ungleich
   null sowie fortbestehende Schreibsperre;
8. entfernt nur das exakte Zielprojekt, restauriert alle vier
   Cross-System-Bestandteile und bestätigt den Golden-Stand;
9. promoted denselben Manifest-SHA erneut, migriert erfolgreich und bestätigt
   den Zielstand;
10. verändert anschließend Core, Twenty, RustFS und Mailzustand bewusst,
    erkennt den fachlichen Post-Smoke-Fehler und restauriert erneut;
11. vergleicht Dokument-Objektschlüssel, Größen und SHA-256 vor Upgrade,
    nach Upgrade und nach Rollback;
12. entfernt beide isolierten Compose-Projekte, Netzwerke und Volumes.

Lokale, ignorierte Belege liegen unter `.artifacts/pilot043/`, darunter:

- `release-v1.json`, `release-v2.json`;
- `release-ledger.jsonl`;
- `core-migration-failure.log`;
- Golden-Snapshots vor/nach Upgrade, nach Migrationsrollback und nach
  fachlichem Rollback;
- unveränderte Dokumentmanifeste;
- Chromium-Screenshots vor/nach Upgrade und nach Rollback;
- secretsfreie Twenty-Migrationslogs und `result.json`.

## Zusätzlich wiederverwendete harte Gates

- PILOT-040 beweist, dass die produktionsähnliche Topologie ausschließlich
  vorab gebaute Images mit `up --no-build` startet.
- PILOT-041 beweist vollständigen, verschlüsselten Cross-System-Restore,
  leeres Ziel, Integritätsprüfung, RPO/RTO und Dokument-SHAs.
- `tools/upgrade/validate_plan.py` bindet Release Notes, Migrationen,
  Recovery-Strategien und externe Systemlocks.

## Bewusst verbleibende Betreibergrenzen

- Ein unabhängiger Operator muss den letzten freigegebenen Zustand allein
  anhand des Runbooks und ohne Implementiererhilfe restaurieren.
- Der bestehende Releasegrenzentest bedient einen realen Chromium-Dashboard-
  und Dokument-Smoke. Die **vollständige** Krapfentaxi Golden Journey je
  Releasegrenze bleibt für die produktionsnahe Generalprobe offen; der
  eigenständige Mehrbrowser-Nachweis aus PILOT-050 wird nicht durch einen
  kleineren Test ersetzt.
