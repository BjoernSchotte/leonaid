# Golden Dataset v1

Alle Namen, Firmen, Anschriften und E-Mail-Adressen sind synthetisch.
E-Mail-Adressen verwenden ausschließlich die reservierte Testzone
`leonaid.invalid`. Die Daten bilden keinen realen Lions Club und keine realen
Sponsoren ab.

## Personas

- **Simone System** sieht alle drei Aktionen und dient später ausschließlich
  der systemweiten Administration.
- **Klara Kern** verwaltet die aktive und die archivierte Krapfentaxi-Aktion.
- **Felix Fremd** verwaltet nur die fremde, noch nicht veröffentlichte
  Testaktion. Damit werden negative Aktionsgrenzen beweisbar.
- **Anna Akquise**, **Bernd Binder** und **Carla Club** sind aktive
  Akquisiteure der laufenden Aktion.
- **Finn Finanzen** besitzt die aktionsbezogene Finanzrolle.
- **Gesa Gesperrt** hat zwar eine Membership, sieht wegen ihres gesperrten
  Benutzerstatus aber keine Aktion.

## Konflikt- und Sichtbarkeitsfälle

- Musterwerk ist ausschließlich Anna zugeordnet.
- Bäckerei Sonnenseite ist ausschließlich Bernd zugeordnet.
- Doppelkontakt ist Anna und Bernd gemeinsam zugeordnet und besitzt zwei
  Ansprechpartner.
- Freie Firma ist bewusst niemandem zugeordnet.
- Sophie Sponsor ist eine Person ohne Firma und Carla zugeordnet.
- `Baeckerei  Sonnenseite K.G.` normalisiert auf eine vorhandene Firma; beim
  Erfassen muss die bestehende Zuordnung zu Bernd als Warnung erscheinen.
- Zwei Personen heißen Max Mustermann. Firma, E-Mail und PLZ erzwingen eine
  bewusste Disambiguierung.

## Krapfentaxi-Fachwerte

Das aktive Angebot enthält 24 Krapfen pro Box zu 36,00 EUR. Sechs
Commitments decken Entwurf, prüfbereit, öffentlich eingegangen und fakturiert
ab. Zusammen ergeben sie 25 Boxen, 600 Krapfen und 900,00 EUR. Bei einem
manuellen Aktionsziel von 1.000,00 EUR sind das 90,00 Prozent.

Die drei Rechnungen decken offen, bezahlt und storniert ab. Jede enthält einen
eigenen Adress-Snapshot und verweist auf ein fakturiertes Commitment.

## Public Web

`/krapfentaxi` ist der bewegliche Alias der aktiven Aktion. Die aktive Aktion
besitzt zusätzlich den stabilen kanonischen Pfad
`/archive/krapfentaxi-2026`; das Vorjahr ist ausschließlich unter
`/archive/krapfentaxi-2025` erreichbar.

## Dateien und Prüfung

- `manifest.json` verbindet Dataset- und Schemaversion.
- `schema.json` definiert Collections und Enums.
- `dataset.json` enthält ausschließlich Eingabedaten.
- `expected.json` enthält Counts, Sichtbarkeiten, Match-Ergebnisse,
  Mengen-/Geldberechnungen, Feed-Sichten und Public-Auflösung.

Prüfung:

```sh
docker run --rm -v "$PWD:/workspace:ro" \
  python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 \
  /bin/sh /workspace/tools/golden/test.sh /workspace
```
