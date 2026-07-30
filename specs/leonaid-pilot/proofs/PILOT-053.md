# PILOT-053 – Technischer Readiness-Teilnachweis

Stand: 2026-07-30
Ergebnis: Ein fail-closed Readiness-Dossier bewertet den echten
Repositoryzustand, alle 21 Tasks, 16 Hard-Gates, Proof-Links und öffentlichen
Entscheidungs-IDs. Der finale cache-freie technische CI-Lauf ist
nachgewiesen; der Gesamtstand wird weiterhin korrekt als `blocked`
ausgewiesen. Der Live-Pilot, externe Nachweise, ausdrückliche Abnahmen und
die Milestoneentscheidung bleiben offen.

## Implementierter Vertrag

- `./leonaid pilot-readiness` liefert `ready`, `blocked` oder `stop` und
  verwendet dafür stabile Exitcodes `0`, `2` und `3`.
- Ein Vertragsfehler liefert Exit `1`; fehlende Gates werden nicht als
  „nicht relevant“ interpretiert.
- Alle Task-Kriterien und -Abhängigkeiten, die 16 Hard-Gates und ihre
  Task-Zuordnung werden aus dem versionierten Pilotvertrag gelesen.
- Jeder reservierte Proof-Link wird als `missing`, `partial` oder `complete`
  bewertet. Nur exakte Task-ID und `Status: vollständig bewiesen` schließen
  einen Proof.
- Alle für `pilot-release` fälligen Entscheidungen werden ausschließlich als
  öffentliche IDs ausgewertet.
- Branch, Commit, sauberer Arbeitsbaum und Gleichstand mit
  `refs/remotes/origin/main` fließen in die Readiness ein.
- Der sanitizte JSON-Report besitzt eine reproduzierbare SHA-256-Prüfsumme und
  enthält keine privaten Evidence-Inhalte oder Fachpayloads.
- [`../../../infra/pilot/PILOT-ACCEPTANCE-RUNBOOK.md`](../../../infra/pilot/PILOT-ACCEPTANCE-RUNBOOK.md)
  und
  [`../../../infra/pilot/PILOT-ACCEPTANCE-TEMPLATE.md`](../../../infra/pilot/PILOT-ACCEPTANCE-TEMPLATE.md)
  trennen technische Readiness, privates Protokoll und ausdrückliche Abnahme.

## Automatisierter Nachweis ohne Mocks

Ausgeführt:

```text
./leonaid test-pilot-readiness
./leonaid pilot-readiness --json
```

Ergebnis:

```text
pilot-readiness-test: OK: real blocked state, complete fixture,
missing/partial proof, dirty Git and hard-gate drift proven
pilot-readiness: BLOCKED
```

Der Selbsttest verwendet den realen aktuellen Plan und ein echtes temporäres
Git-Repository. Eine strukturell vollständig geschlossene Kopie beweist den
positiven `ready`-Pfad. Danach werden ein Proof real entfernt, ein
Proofmarker verändert, ein unversionierter Dateicanary angelegt und eine
Hard-Gate-ID verfälscht. Die Fälle ergeben deterministisch `blocked`
beziehungsweise einen Vertragsfehler.

Der aktuelle echte Report weist sämtliche 16 Hard-Gates als blockiert aus,
listet die offenen Pilotentscheidungs-IDs und unterscheidet fehlende von
technischen Teilproofs. Auf Commit
`24a6dc4441f9a2c95db3ab6e81ae6c6432cd79fd` meldet er zugleich `main`,
einen sauberen Arbeitsbaum und Gleichstand mit `origin/main`. Damit ist der
Repositoryzustand kein Readiness-Blocker mehr.

## Finaler cache-freier CI-Teilnachweis

Der manuell ausgelöste
[GitHub-Actions-Lauf 30513894673](https://github.com/BjoernSchotte/leonaid/actions/runs/30513894673)
auf Commit `cac3f9833fc2fe206339acdb1221c08e170b2c54` endete terminal mit
`success`. Der Job `Pilot cold rehearsal` (Job-ID `90779482805`) entfernte
vor dem Bootstrap den Docker-Buildcache, startete aus leerem Zustand und lief
vom `2026-07-30T04:27:00Z` bis `2026-07-30T05:19:50Z`.

Das veröffentlichte Artefakt `ci-pilot-cold-rehearsal` belegt den
vollständigen synthetischen Krapfentaxi-Durchlauf auf realen isolierten
Diensten, alle acht Rehearsal-Schritte und Chromium, Firefox sowie WebKit.
Sein JSON-Vertrag meldet `status=passed`, aber ausdrücklich
`productionReadiness=false`; alle fünf externen Gates bleiben offen. Der
CI-Sanitizer und eine unabhängige Prüfung des Downloads akzeptierten die drei
Textartefakte ohne Secret-Redaktion. Dateihashes und fachliche Details sind
im Teilnachweis
[`PILOT-050`](PILOT-050.md#cache-freier-remote-ci-nachweis)
festgehalten.

Damit sind die beiden technischen Kriterien „sanitizte Beweisartefakte aus
finalem Cold-CI-Lauf“ und „Docker-Cold-Start ohne Caches aus leerem Zustand“
bewiesen. Sie ersetzen keine reale Generalprobe, private Evidence oder
Abnahme.

## Letzter Main- und Remote-CI-Baseline-Nachweis

Der
[GitHub-Actions-Lauf 30568363863](https://github.com/BjoernSchotte/leonaid/actions/runs/30568363863)
auf Commit `24a6dc4441f9a2c95db3ab6e81ae6c6432cd79fd` endete am
2026-07-30 terminal mit `success`. Erfolgreich waren Security, Build, Unit,
Lint/Types, Contract, die reale Service-Integration sowie die Browser-Gates
für Aktionen, Public Web, Identität, Rechnungen, Akquise und die vollständige
Golden Journey. Der Integrationsjob lief 38 Minuten und 48 Sekunden gegen die
realen gepinnten Testdienste.

Zum selben Zeitpunkt waren lokales `HEAD` und `origin/main` identisch und der
Arbeitsbaum sauber. Das belegt einen grünen technischen Zwischenstand. Das
finale Kriterium „Abschlusscommit auf `main`, Remote-CI terminal grün und
Arbeitsverzeichnis sauber“ bleibt bis zum tatsächlichen Abschluss aller
Pilot-Gates offen. Der Baseline-Nachweis ersetzt weder das private
Abnahmeprotokoll noch die noch offenen externen Pilot-Gates.

## Bewusst offene Gates

Dieser Nachweis schließt `PILOT-053` nicht. Noch erforderlich sind:

- vollständig bewiesene Tasks `PILOT-000` bis `PILOT-052`;
- geschlossene P0/P1-, Security-, Datenschutz- und Datenverlustbefunde;
- ausdrückliche Abnahme durch Produktverantwortung, Betrieb und Fachrollen;
- nachgeführte Runbooks, Architektur, Datenmodell, API, Personas, Grenzen und
  Entscheidungsregister aus dem realen Betrieb;
- reale Generalprobe mit externen Providern, DNS/TLS, kontrollierten
  Pilotdaten und unabhängiger Operatorhandlung;
- vollständige, private und aufbewahrungsgebundene Pilot-Evidence;
- ausgefülltes privates Abnahmeprotokoll;
- dokumentierte nächste Milestoneentscheidung;
- ausdrückliche Entscheidung zu Laufzeit und Betriebsübergang.
