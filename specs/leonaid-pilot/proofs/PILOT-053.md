# PILOT-053 – Technischer Readiness-Teilnachweis

Stand: 2026-07-29
Ergebnis: Ein fail-closed Readiness-Dossier bewertet den echten
Repositoryzustand, alle 21 Tasks, 16 Hard-Gates, Proof-Links und öffentlichen
Entscheidungs-IDs. Der aktuelle Stand wird korrekt als `blocked` ausgewiesen.
Der Live-Pilot, externe Nachweise, ausdrückliche Abnahmen und die
Milestoneentscheidung bleiben offen.

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
technischen Teilproofs. Während der Implementierung ist zusätzlich der
Arbeitsbaum korrekt als nicht sauber markiert. Der Remote-CI-Report wird auf
dem gepushten Commit erneut erzeugt und darf diesen Git-Blocker nicht
enthalten.

## Bewusst offene Gates

Dieser Nachweis schließt `PILOT-053` nicht. Noch erforderlich sind:

- vollständig bewiesene Tasks `PILOT-000` bis `PILOT-052`;
- geschlossene P0/P1-, Security-, Datenschutz- und Datenverlustbefunde;
- ausdrückliche Abnahme durch Produktverantwortung, Betrieb und Fachrollen;
- nachgeführte Runbooks, Architektur, Datenmodell, API, Personas, Grenzen und
  Entscheidungsregister aus dem realen Betrieb;
- finaler Docker-Cold-Run und produktionsnahe Generalprobe;
- vollständige, private und aufbewahrungsgebundene Pilot-Evidence;
- ausgefülltes privates Abnahmeprotokoll;
- dokumentierte nächste Milestoneentscheidung;
- ausdrückliche Entscheidung zu Laufzeit und Betriebsübergang.
