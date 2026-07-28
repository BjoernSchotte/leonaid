# PILOT-000 – Pilot-Traceability und Proof-Infrastruktur

Task-ID: `PILOT-000`  
Nachweisdatum: 28. Juli 2026  
Status: vollständig bewiesen  
Implementierungsbasis:
`e8d63a1e6e39c474314259e1d00530c186abf5cf`

## Ergebnis

Der Pilot besitzt einen ausführbaren Vertrag für alle 21 Tasks, sämtliche 237
Checkbox-Kriterien und die 16 harten Abnahme-Gates.

- Task-IDs stehen stabil im Plan.
- Kriterien-IDs werden aus Task-ID und normalisiertem vollständigem Text als
  `PILOT-NNN-C-<SHA256-12>` erzeugt. Der Checkbox-Status beeinflusst die ID
  nicht.
- Harte Gates stehen als `PILOT-GATE-001` bis `PILOT-GATE-016` direkt in der
  Abnahmematrix.
- [`TRACEABILITY.md`](../TRACEABILITY.md) reserviert für jeden Task genau einen
  öffentlichen Proof-Link und hält Plan- und Proofstatus synchron.
- [`proofs/`](./README.md) ist der einzige versionierte Proof-Ort und erlaubt
  ausschließlich personenbezugsfreie Nachweise.
- Private Evidenz bleibt unter `.local/pilot/` oder im geschützten externen
  Evidence Store; öffentliche temporäre CI-Evidenz läuft über
  `.artifacts/ci/` und den fail-closed Sanitizer.

## Automatischer Vertragsnachweis

```sh
./leonaid test-pilot-contract
```

Ergebnis nach Schließen dieses Tasks:

```text
pilot-contract-test: OK: positive plan and four contract-drift cases passed
pilot-contract: OK: 21 tasks, 237 criteria, 16 hard gates, 1 complete
```

Der Positivtest verwendet den echten versionierten Plan. Vier isolierte
Kopien beweisen konkrete Ablehnungen für:

1. fehlenden oder fehlerhaften Proof-Link;
2. Checkbox-Kriterium außerhalb eines Tasks;
3. unbekannte Task-Abhängigkeit;
4. als abgeschlossen markierten Task mit offenen Kriterien.

Der maschinenlesbare Bericht verwendet das Schema
`leonaid.pilot-contract/v1` und wird im Contract-CI-Job als
`pilot-contract.json` veröffentlicht.

## CI- und Sanitizer-Nachweis

Der echte gemeinsame CI-Wrapper wurde lokal mit dem Pilotvertrag ausgeführt:

```text
ci-artifact-sanitize: OK: 3 Artefakte geprüft,
0 Secret-Vorkommen redigiert
```

`tools/ci/contract.sh` führt den Pilotvertrag vor den bestehenden OpenAPI- und
Systemverträgen aus. Der vorhandene Contract-Job lädt sein Artefakt mit
`if: always()` auch nach Fehlern hoch. `tools/ci/run-job.sh` verwirft den
gesamten Inhalt fail-closed, falls die Sanitizer-Prüfung nicht erfolgreich ist.

Der bestehende absichtlich fehlschlagende Realstack-Artefakt-Probevertrag und
der Workflow-Negativtest bleiben Teil von `./leonaid check`.

## Unveränderte PoC-Traceability

Der bestehende PoC-Vertrag wird weiterhin separat und unverändert ausgeführt:

```text
traceability: OK: 50 tasks, 14 scope requirements, 23 hard gates
traceability-test: OK: positive and four traceability-drift cases passed
```

Pilot- und PoC-Traceability besitzen getrennte Checker. Dadurch kann ein neuer
Pilotstatus keine abgeschlossene PoC-Historie umdeuten.

## Docker-Ressourcen

Der Contract-Test verwendet ausschließlich kurzlebige
`docker run --rm`-Container und erzeugt keine Compose-Netze oder Volumes. Eine
Vorher-/Nachher-Inventur bestätigte null Ressourcen mit Präfix
`leonaid-pilot`.

Bei der Baseline-Inventur gefundene, eindeutig isolierte alte
PoC-Testressourcen (`leonaid-poc113-upgrade` und
`leonaid-poc091-pdf-viewer`) wurden entfernt. Der kanonische sichtbare
Entwicklungsstack `leonaid` blieb unverändert aktiv.
