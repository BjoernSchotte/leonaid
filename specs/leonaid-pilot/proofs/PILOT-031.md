# PILOT-031 – Staging-Import und Konfliktauflösung

Task-ID: `PILOT-031`

Nachweisdatum: 29. Juli 2026

Status: technischer Apply-/Recovery-Vertrag bewiesen, reales Staging offen

## Ergebnis

Der isolierte Test startet echte, gepinnte Core-, Twenty- und RustFS-Dienste
unter dem eigenen Compose-Projekt `leonaid-pilot030-test`. Er provisioniert
Twenty über dessen Metadata/Data API, lädt Golden Data und erstellt vor Apply
einen realen Cross-System-Recovery-Point:

- `core.dump`;
- `twenty.dump`;
- `twenty-storage.tar`;
- `rustfs-data.tar`;
- ein bytegenau validiertes Manifest.

Ein Konflikt wird in einer privaten Resolution-Datei mit Source-ID,
Ziel-Twenty-ID, Entscheidung, Entscheider-ID und Zeitpunkt aufgelöst. Die
Freigabe bindet anschließend unter Vier-Augen-Prinzip exakt Plan, Input,
Mapping, Resolution, Ziel und Recovery Point.

Der Nachweis erzeugt real:

- `UNRESOLVED_CONFLICT` vor dem ersten Write;
- `BATCH_APPLY_CONCURRENT` bei gehaltenem Betriebssystem-Dateilock;
- `APPROVAL_FINGERPRINT_MISMATCH` nach einem einzelnen Mapping-Byte;
- `STALE_RESOLUTION` für eine nicht mehr vorhandene Source-ID;
- `RECOVERY_POINT_TARGET_MISMATCH` für ein Backup einer anderen Umgebung;
- einen erfolgreichen Apply mit einer Neuanlage und zwei Updates;
- einen Verify-Lauf mit drei unveränderten und einer abgewiesenen Zeile;
- einen Restore der echten Core-/Twenty-Datenbanken auf den Vorzustand;
- null verbleibende Container, Netze und Volumes des Testprojekts.

Der vorhandene CRM-Importvertrag bleibt ebenfalls grün.

Sanitizte, personenbezugsfreie Testsummen:
[`PILOT-031-summary.json`](PILOT-031-summary.json)

## Offene reale Grenze

Die echte Clubdatei, eine getrennte reale Staginginstallation, fachlich
bestätigte Konfliktentscheidungen und Operatorfreigaben fehlen noch.
PILOT-031 bleibt deshalb formal offen.
