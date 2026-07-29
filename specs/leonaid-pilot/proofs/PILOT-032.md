# PILOT-032 – Kontrollierter Produktionsimport

Task-ID: `PILOT-032`

Nachweisdatum: 29. Juli 2026

Status: technischer Produktionsbefehl fail-closed vorbereitet, Durchführung offen

## Vorbereiteter Vertrag

`./leonaid pilot-import apply` ist kein Platzhalter mehr. Der Befehl:

- akzeptiert nur `dry-run`, `apply` oder `verify`;
- verlangt ein eindeutig benanntes Staging-/Produktionsziel;
- verwendet ausschließlich die bereits laufenden, digest-gepinnten Images
  und baut auf dem Zielsystem nicht;
- führt vor Apply den vollständigen `pilot-doctor --gate pilot-import` aus;
- bindet Input, Mapping, Resolution, Plan und Recovery Point an die
  Vier-Augen-Freigabe;
- verweigert ungeklärte Konflikte und paralleles Apply vor dem ersten Write;
- schreibt private Reports ausschließlich unter `.local/pilot/evidence/`;
- lässt Verify nur ohne neue, zu ändernde oder ungeklärte Zeilen passieren.

Bedienung, Stop-/Restore-Weg und private Dateiverträge sind im
[`IMPORT-RUNBOOK.md`](../../../infra/pilot/IMPORT-RUNBOOK.md) dokumentiert.
Der technische Vertrag ist mit synthetischer Strukturfixture gegen echte
Core-, Twenty- und RustFS-Dienste bewiesen; siehe
[`PILOT-031.md`](PILOT-031.md).

## Offene Produktionsgrenze

Es wurde ausdrücklich kein Produktionsimport simuliert oder behauptet.
PILOT-032 benötigt noch:

- die rechtmäßig verwendbare tatsächliche Clubdatei;
- abgeschlossene Träger-, Steuer-, Datenschutz- und Betriebsentscheidungen;
- das freigegebene Release in einer realen Staging- und
  Produktionsinstallation;
- reale Mapping-, Konflikt- und Vier-Augen-Freigaben;
- Wartungsfenster, Produktverantwortlichen und Operator;
- privaten Vorher-/Nachher-, Audit-, Stichproben- und Sign-off-Nachweis.

Bis dahin blockiert der Doctor den produktiven Befehl wie vorgesehen.
