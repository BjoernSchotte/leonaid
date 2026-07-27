# ADR-0011: Verschlüsselte systemübergreifende Recovery Points mit Restic

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 9.2

## Kontext

LeonAid verteilt dauerhafte Fachdaten auf Core-PostgreSQL, Twenty-PostgreSQL,
Twenty lokale Dateien und RustFS. Ein reiner VPS-Snapshot oder ein einzelner
`pg_dump` beweist weder die fachliche Konsistenz noch die Wiederherstellbarkeit
von Rechnungs-PDFs, Sitzungen, Audit und Outbox.

Der PoC braucht einen einfachen, providerneutralen und tatsächlich prüfbaren
Recovery-Pfad ohne einen weiteren dauerhaft laufenden Steuerungsdienst.

## Entscheidung

Restic `0.19.1` wird als Image mit Tag und Digest gepinnt. Der
Produktionsvertrag akzeptiert ausschließlich Remote-Backends; lokale Ziele
bleiben auf den isolierten POC-112-Test beschränkt. Restic verschlüsselt,
rotiert und liest nach jeder Sicherung alle gespeicherten Daten zur
Integritätsprüfung.

Vor dem Recovery Point werden alle schreibenden LeonAid- und Twenty-Dienste
kurz angehalten. Die beiden laufenden PostgreSQL-Instanzen werden im
Custom-Format gedumpt; Twenty-Dateien und das RustFS-Datenvolume werden in
denselben Recovery Point aufgenommen. Manifest und SHA-256 schützen die
entpackten Bestandteile zusätzlich.

Restore ist ausschließlich in ein leeres Compose-Projekt mit dem Präfix
`leonaid-restore-` erlaubt. Eine exakte Bestätigung bindet die Operation an
dieses Ziel. Secrets werden getrennt gesichert und niemals Bestandteil des
Recovery Points.

## Betriebsziele

- RPO: 24 Stunden bei mindestens täglicher Sicherung.
- RTO: 2 Stunden bis zu einer verifizierten Mitgliederoberfläche.
- Rotation: 7 täglich, 5 wöchentlich, 12 monatlich, 3 jährlich.
- Quartalsweiser Fresh-Volume-Recovery-Test und zusätzlicher Test vor
  schemaändernden Upgrades.

## Konsequenzen

- Der PoC akzeptiert einen kurzen geplanten Schreibstopp zugunsten einer
  klaren Konsistenzgrenze.
- Twenty Redis und Mailpit sind nicht Teil des dauerhaften Recovery Points.
- Ein Remote-Backend kann ohne Änderung des Backupformats gewechselt werden.
- Off-VPS-Lage und Secret-Notfallkopie bleiben Betreiberpflichten; der Code
  verhindert unsichere lokale Produktionsziele, kann aber keine physische
  Infrastruktur vortäuschen.
- Ein späteres Zero-Downtime-Verfahren benötigt koordinierte Snapshots oder
  kontinuierliche Replikation und eine neue ADR.
