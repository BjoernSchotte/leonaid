# PILOT-040 – Produktions- und Staging-Topologie

Task-ID: `PILOT-040`

Nachweisdatum: 29. Juli 2026

Status: technische Topologie und Doctor bewiesen, reale Stagingdomain offen

## Ergebnis

Die additive Pilot-Topologie unter `infra/pilot/` ist fail-closed und
reproduzierbar:

- Produktionsdienste werden ausschließlich aus digest-gepinnten Images
  gestartet; auf dem Zielsystem gibt es weder Build noch Live-Code-Mount.
- Nur Caddy veröffentlicht 80/443. Core-PostgreSQL, Twenty-PostgreSQL,
  Redis, RustFS, API und Worker bleiben in internen Netzen.
- Staging und Produktion werden durch Stage, Compose-Projekt, Domains,
  Volumes, Datenbanken, Bucket, Backupziel, Mailkonfiguration und getrennte
  Secrets gegeneinander abgegrenzt.
- Die private Environment-Datei muss außerhalb des Repositorys liegen,
  Modus `0600` besitzen und den vollständigen Release-Commit enthalten.
- Caddy setzt HSTS, CSP, Referrer-, Permissions- und Content-Type-Header.
  Das produktive Caddyfile verwendet öffentliches ACME; der
  produktionsähnliche Test verwendet eine echte private CA, damit auch dort
  Hostname und Vertrauenskette geprüft werden.
- Der Betriebsablauf, die TLS-Erneuerung und die verbleibende reale
  Staging-Grenze sind in `infra/pilot/README.md` dokumentiert.

## Deployment Doctor

`./leonaid pilot-doctor` erzeugt zunächst die echte zusammengeführte
Compose-Konfiguration und prüft danach:

1. Secret-Dateirechte, Mindestlänge und paarweise Trennung;
2. Stage-/Projekt-/Bucket-Grenzen und externes Restic-Ziel;
3. Commit, Image-Digests, Ports, Netze und Mounts;
4. Backupinventar und ein maximales Backupalter von 26 Stunden;
5. mindestens 5 GiB freien Speicher;
6. DNS und verifiziertes TLS mit Hostname und Zertifikatsrestlaufzeit;
7. Sicherheitsheader sowie Portal, API, Twenty und Mail-Provider;
8. Uhrversatz gegen den `Date`-Header des externen Mail-Providers;
9. alle für das gewählte produktive Gate fälligen Entscheidungen.

Der Doctor gibt nur stabile Check- und Fehlernamen aus. Ein Negativtest
injiziert bewusst einen Secret-Canary, erzwingt einen Fehler und beweist,
dass der Canary weder auf stdout noch auf stderr erscheint.

## Automatischer Nachweis

```sh
./leonaid test-pilot-deployment
```

Ergebnis:

```text
pilot-deployment-contract: OK: Release-, Port-, Netz-, Mount- und
Produktionsgrenzen
pilot-deployment-contract-test: OK: sieben reale Compose-Mutationen
fail-closed abgewiesen
pilot-deployment-doctor-test: OK: sechs unsichere reale
Datei-/Parameter-Mutationen fail-closed abgewiesen
pilot-deployment-doctor: OK: DNS, TLS, Secrets, Uhrzeit, Speicher,
Backup und Abhängigkeiten
pilot-deployment-test: OK: Contract, Leerstart und realer Deployment
Doctor bewiesen
```

Der Test verwendet keine Test-Doubles:

- Er baut vier Release-Images vor dem Start.
- Er startet zwölf reale Services ohne `--build` aus leeren Volumes.
- Er wartet auf den Healthstatus jedes einzelnen Services.
- Er extrahiert die echte Caddy-Test-CA und prüft die TLS-Verbindungen mit
  Hostnameprüfung, nicht mit `--insecure`.
- Er ruft echte Portal-, API-, Twenty- und Provider-Health-Endpunkte auf.
- Er erzeugt ein aktuelles Backupmanifest im selben Laufzeitkontext und
  prüft Alter und Scope.
- Er mutiert reale Environment-, Compose- und Manifest-Dateien für
  Port-, Build-, Mount-, Image-, URL-, Secret-, Stage-, Commit-,
  Backupziel- und Backupalter-Fehler.

Ein erster Lauf deckte zusätzlich eine reale Uhrabweichung zwischen
macOS-Host und OrbStack-VM auf. Das Backupmanifest wird deshalb korrekt im
Laufzeitkontext erzeugt; produktiv bleibt der unabhängige
Provider-`Date`-Vergleich als strenger Clock-Skew-Check aktiv.

## Ressourcen- und UI-Grenze

Das isolierte Projekt heißt `leonaid-pilot040-test`. Nach jedem erfolgreichen
und fehlgeschlagenen Lauf waren jeweils null Container, Netzwerke und Volumes
mit diesem Projektlabel vorhanden. Auch alle vier temporären
`leonaid-pilot040-release-*`-Images wurden entfernt. Der kanonische
Entwicklungsstack blieb unberührt.

PILOT-040 verändert keine Benutzeroberfläche. Ein sichtbarer
In-App-Browser-Nachweis wäre daher kein zusätzlicher Fachnachweis; die
End-to-End-Grenze dieses Tasks ist der reale HTTPS-/Compose-Lauf.

## Offene formale Gates

PILOT-040 bleibt formal offen:

- Die Abhängigkeiten `PILOT-001` und `PILOT-002` sind wegen externer
  Entscheidungen noch nicht formal abgeschlossen.
- Es existiert noch keine freigegebene öffentliche Stagingdomain.
- Deshalb sind öffentliche DNS-Auflösung, die von einer öffentlichen CA
  gelieferte Vertrauenskette, Header an dieser Domain und beobachtete
  Zertifikatserneuerung noch nicht real belegt.

Die lokale/private CA beweist die technische TLS- und Hostnameprüfung,
ersetzt aber ausdrücklich nicht den noch ausstehenden öffentlichen
Staging-Nachweis.
