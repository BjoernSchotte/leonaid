# PILOT-001 – Technischer Entscheidungsvertrag

Task-ID: `PILOT-001`

Nachweisdatum: 29. Juli 2026

Status: technischer Entscheidungsvertrag bewiesen, externe Fachfreigaben offen

## Ergebnis

Das öffentliche Register
[`../DECISIONS.md`](../DECISIONS.md) bildet 14 stabile Entscheidungen ab.
Jeder Datensatz enthält ID, Bereich, Gegenstand, Owner-Rolle, Erfassungsdatum,
Quelle, Evidence-ID, Status, kontrollierten Wert und spätestes Gate.

Die technische Grenze trifft keine Rechts-, Steuer-, Datenschutz- oder
Betriebsentscheidung:

- Offene Entscheidungen verwenden ausschließlich `PENDING`.
- Aufgelöste Entscheidungen benötigen eine opake `EVID-…`-Referenz und einen
  kontrollierten Wert.
- Die Owner-Rollen liegen bei rechtlichem Träger, Steuerberatung,
  Datenschutz, Betrieb und Produktverantwortung.
- [`../DECISION-INTAKE.md`](../DECISION-INTAKE.md) enthält die fachlichen
  Fragen und zulässigen Ergebnisse, aber keine produktiven Antworten.
- Namen, Verträge, Steuerunterlagen, Kontodaten, Zugangsdaten und
  Volltexte bleiben im privaten Evidence Store.

## Fail-closed Gates

Der Vertrag bewertet jedes produktive Gate einzeln:

1. `pilot-deploy`;
2. `pilot-import`;
3. `pilot-backup`;
4. `pilot-restore`;
5. `pilot-release`.

Nur die für das jeweilige Gate fälligen Entscheidungen werden verlangt.
`open` ergibt Exit `2`, ein Scope-Stop Exit `3` und ein vollständig
freigegebenes Register Exit `0`.

Der echte Deployment Doctor übernimmt denselben Vertrag und prüft ihn
zusätzlich zu Environment, Compose, Release-Commit, Backup, DNS, TLS,
Speicher, Uhrzeit und Abhängigkeiten. Produktive Befehle laufen zuerst durch
diesen Doctor.

## Steuer- und Rechnungsgrenze

Die beiden ausdrücklich ausgeschlossenen Scope-Erweiterungen sind
maschinell erzwungen:

- `PILOT-TAX-001=full_accounting_required` ist ausschließlich mit
  Status `stop` zulässig;
- `PILOT-INV-002=required` ist ausschließlich mit Status `stop` zulässig;
- eine Rechnungsfreigabe bei noch offenem Träger oder Steuerfall wird als
  widersprüchlich abgelehnt;
- der synthetische Golden-Data-Steuerfall wird nicht als produktive
  Entscheidung übernommen.

## Automatischer Nachweis ohne Mocks

Ausgeführt:

```text
./leonaid test-pilot-decisions
./leonaid test-pilot-deployment
```

Ergebnis:

```text
pilot-decisions-test: OK: five gate-specific text/JSON checks,
accepted register, both scope-STOP paths and five negative
decision cases proven
pilot-deployment-doctor-test: OK: sechs unsichere reale
Datei-/Parameter-Mutationen fail-closed abgewiesen
pilot-deployment-doctor: OK: DNS, TLS, Secrets, Uhrzeit, Speicher,
Backup und Abhängigkeiten
pilot-deployment-test: OK: Contract, Leerstart und realer Deployment
Doctor bewiesen
```

Der Test liest das echte versionierte Register. Für den Positiv- und die
Negativpfade erzeugt er reale temporäre Registerdateien, nicht simulierte
Parserantworten. Bewiesen werden:

- exakte offene Entscheidungs-IDs je Gate in Text und JSON;
- vollständig akzeptiertes Register als `ready`;
- fehlende Owner-Rolle;
- fehlende Evidence-ID;
- verbotene Freigabe trotz vollständiger Buchhaltung;
- widersprüchliche Rechnungsfreigabe bei offenem Träger/Steuerfall;
- echte `STOP`-Pfade für vollständige Buchhaltung und E-Rechnung.

Der Deployment-Test baut vier releasefähige Images, startet zwölf echte
Dienste aus leeren Volumes und führt den Doctor mit realem Compose, privater
Test-CA, DNS, TLS, Backupmanifest und Dependency-Health aus. Danach waren
null Container, Netze, Volumes und temporäre Release-Images des isolierten
Projekts `leonaid-pilot040-test` vorhanden.

Der übergeordnete `./leonaid check` und die CI führen diesen Vertrag als
eigenes Contract-Gate aus.

## Bewusst offene Fachfreigabe

`PILOT-001` bleibt formal offen. Noch fehlen die echten Entscheidungen und
privaten Evidence-Referenzen von:

- rechtlichem Träger und Steuerberatung;
- Datenschutz;
- Betrieb;
- Produktverantwortung.

Diese Rollen müssen das Register ausdrücklich bestätigen. Die
Implementierung darf ihre Antworten weder erraten noch den Task aufgrund
grüner Technik abhaken.
