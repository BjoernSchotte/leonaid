# Backup

Backup-, Restore- und Recovery-Werkzeuge folgen in M11.

## Schemaändernde Migrationen

Bis POC-112 den automatisierten Backup-/Restore-Prozess nachgewiesen hat,
dürfen schemaändernde Migrationen nur auf wegwerfbaren PoC-Datenbanken oder
nach einem expliziten PostgreSQL-Backup ausgeführt werden. Das Backup wird mit
dem in `infra/compose/compose.yml` gepinnten PostgreSQL-Container als
Custom-Format-Dump erzeugt und vor der Migration in eine leere
PostgreSQL-Instanz zurückgespielt. Ein produktiver Einsatz bleibt bis zum
vollständigen POC-112-Nachweis gesperrt.

Jede destruktive Vorwärtsmigration referenziert diesen Abschnitt und beschreibt
zusätzlich ihre konkrete Datenüberführung im Modul. Der CI-Migrationstest
beweist weiterhin sowohl den Leeraufbau als auch das Upgrade eines
versionierten Vorgängersnapshots.
