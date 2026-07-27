# ADR-0012: Gepinnte Upgrades mit Wartungsgrenze und Backup-Rollback

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 9.2

## Kontext

LeonAid Core, Twenty und RustFS besitzen voneinander unabhängige Schemata,
Migrationsmechanismen und Rollbackgrenzen. Ein Container-Healthcheck beweist
nicht, dass eine Twenty-Migration vollständig war: der Upstream-Entrypoint
kann einen fehlgeschlagenen Upgrade-Befehl als Warnung protokollieren und den
Server trotzdem starten.

## Entscheidung

Jedes Upgrade besitzt eine geprüfte, maschinenlesbare
Kompatibilitätsmatrix. Quell- und Zielimages externer Systeme sind mit Tag und
Digest gepinnt. Release Notes, konkrete Migrationsbefehle, erwartete
Datenänderung und Restore-Grenze müssen vor dem ersten Schreibzugriff
dokumentiert sein.

Während inkompatibler Phasen bleibt FastAPI lesbar, blockiert aber alle
schreibenden HTTP-Methoden. Core- und Twenty-Worker sowie der Twenty-Server
werden angehalten. Die Freigabe erfolgt erst nach bereitstehenden
Abhängigkeiten.

Twenty wird in seiner tatsächlichen Reihenfolge aktualisiert:

1. Ziel-Entrypoint stellt Schema-Voraussetzungen her;
2. `run-instance-commands` läuft mit strengem Exitcode;
3. `upgrade` migriert alle Workspaces mit strengem Exitcode;
4. Zielschema, Golden-Contract und Browser-Journey werden geprüft.

Nach einer vorwärts laufenden Datenmigration ist der einzige behauptete
Rollback die vollständige Wiederherstellung aller betroffenen Daten aus
demselben verschlüsselten Recovery Point. Ein älteres Image wird nicht gegen
ein neueres Schema gestartet.

## Konsequenzen

- Upgrades brauchen ein kurzes geplantes Wartungsfenster.
- Ein Golden-Data-Klon und ein frischer Recovery Point sind verpflichtende
  Gates, keine optionalen Empfehlungen.
- Healthchecks bleiben Betriebsindikatoren, ersetzen aber weder explizite
  Migrationsbefehle noch fachliche Contracts.
- Rollback dauert länger als ein reiner Imagewechsel, stellt dafür eine klar
  definierte, systemübergreifende Konsistenzgrenze wieder her.
- Zero-Downtime- oder Down-Migrationsstrategien sind nicht Teil des PoC und
  erfordern eine neue Architekturentscheidung.
