# Pilot-Betriebsrunbooks

Jeder Alarm enthält ausschließlich technische Labels, eine feste
Zusammenfassung und einen Link auf diesen Ablauf. Personen-, Bestell-,
Rechnungs-, Dokument- und Tokeninhalte gehören weder in Metriken noch in
Alarme.

## Backup

1. Alarm in dem unabhängigen Betreiberkanal quittieren.
2. `pilot-doctor` mit dem privaten neuesten Manifest ausführen.
3. Restic-Ziel, Credentials, freien Zielplatz und den letzten vollständigen
   Vier-Komponenten-Snapshot prüfen.
4. Bei unvollständigem oder altem Backup einen neuen Recovery Point erzeugen
   und `restic check --read-data` ausführen.
5. Alarm erst nach erfolgreichem Check und sichtbar zugestelltem
   Recovery-Event schließen.

## Dependency

1. Betroffenen Dienst am `dependency`-Label erkennen.
2. Zustand in `/admin/system` gegenprüfen.
3. Dienstlogs ausschließlich nach Request-ID und stabilen Fehlercodes prüfen.
4. Gepinnten Dienst kontrolliert neu starten; keine Datenvolumes löschen.
5. Readiness und gelöste Alarmzustellung abwarten.

## Worker

1. PostgreSQL-Erreichbarkeit und Worker-Health prüfen.
2. Worker mit unverändertem Release-Image neu starten.
3. Outbox-Zähler und Dead-Letter-Bestand kontrollieren.
4. Fachjobs nur über den abgesicherten Admin-Retry erneut anstoßen.

## Dead Letter

1. Abhängigkeiten zuerst wiederherstellen.
2. In `/admin/system` den stabilen Fehlercode prüfen.
3. Mit frischer Anmeldung `Sicher wiederholen` auslösen.
4. Genau eine erfolgreiche Verarbeitung und den gelösten Alarm prüfen.

## Disk

1. Schreibintensive Prozesse stoppen, ohne Backup-/Security-Alarme zu
   unterdrücken.
2. Große technische Logs, temporäre Dateien und alte freigegebene
   Prometheus-Blöcke identifizieren.
3. Keine Datenbank-, RustFS- oder Restic-Dateien manuell löschen.
4. Kapazität erweitern oder ausschließlich dokumentierte Retention anwenden.

## TLS

1. Öffentliche Domain, Zertifikatskette, Hostname und Ablaufdatum prüfen.
2. Caddy-ACME-Logs und DNS-Auflösung kontrollieren.
3. Bei fehlgeschlagener Erneuerung ACME-Kontakt, Erreichbarkeit von 80/443 und
   Rate Limits prüfen.
4. Kein HSTS zurücknehmen; Zertifikat kontrolliert erneuern.

## API

1. 5xx-Zeitraum und Release-Commit bestimmen.
2. Request-IDs aus strukturierten Logs verwenden; niemals Payloads kopieren.
3. Abhängigkeiten, Datenbankmigration und letzten Release prüfen.
4. Bei Release-Regressionsverdacht das Release-Runbook anwenden.

## Login

1. Rate-Limit-, Provider- und Zustellzustand getrennt prüfen.
2. Keine E-Mail-Adressen, Codes oder Magic Links in den Alarmkanal übertragen.
3. Bei Missbrauchsverdacht Security-Owner eskalieren und AuditEvents
   payloadfrei auswerten.
