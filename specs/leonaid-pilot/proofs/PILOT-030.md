# PILOT-030 – Private Excel-Analyse und Dry Run

Task-ID: `PILOT-030`

Nachweisdatum: 29. Juli 2026

Status: technischer Intake-/Analysevertrag bewiesen, tatsächliche Datei offen

## Ergebnis

`./leonaid test-pilot-import` erzeugt eine private 0700/0600
Intake-Umgebung und verarbeitet eine echte XLSX-Arbeitsmappe gegen ein
frisches, digest-gepinntes Twenty. Die Quelle wird vor Verarbeitung an ein
privates Manifest mit SHA-256, Zweck, Berechtigungsreferenz, Zeitpunkt,
verantwortlicher Actor-ID und externer Evidence-ID gebunden.

Der Dry Run:

- schreibt nicht nach Twenty oder Core;
- meldet jede Zeile mit `new`, `update`, `unchanged`, `conflict` oder
  `rejected` und einem stabilen `ROW_*`-Code;
- gibt ähnliche oder mehrdeutige Matches nur als Kandidaten aus;
- erzeugt einen Plan-Fingerprint aus Quelle, Mapping, Resolution,
  Zielumgebung, Blatt und vollständigem Plan;
- ist bei identischem Zielstand bytegleich reproduzierbar;
- erzeugt daneben eine Summe ohne Zeilen, Kandidaten oder Personenwerte.

Reale XLSX-Mutationen beweisen fehlende Header, verbotene Formeln, doppelte
Source-IDs und ungültige E-Mail-Adressen. Beide Blätter der Strukturfixture
werden explizit gelesen.

## Nachweis

```text
pilot-import-test: ungeklärter Konflikt bleibt sichtbar
pilot-import: OK: dry-run batch=IMPORT-GOLDEN-001 target=staging-golden
pilot-import-test: zwei identische Dry Runs sind bytegleich
pilot-import-test: OK: privater Intake, echte XLSX, realer
Twenty/Core/RustFS-Recovery-Point, Fingerprint, Vier-Augen-Freigabe,
Konflikte, Concurrency, Apply, Verify und Restore bewiesen
```

## Offene reale Grenze

Die tatsächliche Clubdatei wurde noch nicht geliefert. Daher bleiben
Original-Intake, Rechtsgrundlage, tatsächliche Header-/Formatbewertung,
Source-ID-Strategie und die daraus durch einen Coding-Agent zu erzeugende
personenbezugsfreie Mapping-/Strukturfixture ausdrücklich offen.
