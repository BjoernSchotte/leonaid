# LeonAid-Pilot – Traceability- und Proof-Vertrag

Stand: 28. Juli 2026  
Schema: `leonaid.pilot-contract/v1`

## Stabile IDs

- Task-IDs stehen direkt in `PLAN.md` und bleiben über Refactorings erhalten.
- Jedes Checkbox-Kriterium erhält maschinenlesbar die stabile ID
  `PILOT-NNN-C-<SHA256-12>` aus Task-ID und normalisiertem vollständigem
  Kriterientext. `./leonaid test-pilot-contract` erzeugt den vollständigen
  JSON-Report mit diesen IDs.
- Harte Gates besitzen die expliziten IDs `PILOT-GATE-001` bis
  `PILOT-GATE-016` in der Abnahmematrix des Plans.
- Eine fachliche Änderung am Kriterientext erzeugt bewusst eine neue
  Criterion-ID und muss im zugehörigen Proof erklärt werden. Reiner
  Checkbox-Status verändert die ID nicht.

## Öffentliche und private Nachweise

`specs/leonaid-pilot/proofs/` ist der einzige versionierte Ablageort für
Pilotnachweise. Dort sind ausschließlich personenbezugsfreie Summen,
reproduzierbare Befehle, Commit-/CI-Referenzen, Hashes und externe Evidence-IDs
zulässig.

Private Originale liegen ausschließlich unter `.local/pilot/` oder in einem
zugriffsgeschützten externen Evidence Store. Sie werden nie nach
`specs/leonaid-pilot/proofs/`, `.artifacts/` oder GitHub Actions kopiert.

Temporäre öffentliche CI-Artefakte liegen unter `.artifacts/ci/`, werden vor
jedem Upload fail-closed sanitizt und nach 14 Tagen gelöscht. Ein fehlender
oder fehlgeschlagener Sanitizer verhindert die Veröffentlichung.

## Task- und Proof-Register

`open` bedeutet, dass der reservierte Proof-Pfad noch fehlen darf. `complete`
ist nur zulässig, wenn sämtliche Kriterien und Abhängigkeiten geschlossen sind
und das Proof-Dokument die exakte Task-ID sowie `Status: vollständig bewiesen`
enthält.

| Task-ID | Status | Öffentlicher Proof |
| --- | --- | --- |
| PILOT-000 | complete | [PILOT-000](proofs/PILOT-000.md) |
| PILOT-001 | open | [PILOT-001](proofs/PILOT-001.md) |
| PILOT-002 | open | [PILOT-002](proofs/PILOT-002.md) |
| PILOT-010 | open | [PILOT-010](proofs/PILOT-010.md) |
| PILOT-011 | open | [PILOT-011](proofs/PILOT-011.md) |
| PILOT-012 | open | [PILOT-012](proofs/PILOT-012.md) |
| PILOT-013 | open | [PILOT-013](proofs/PILOT-013.md) |
| PILOT-020 | open | [PILOT-020](proofs/PILOT-020.md) |
| PILOT-021 | open | [PILOT-021](proofs/PILOT-021.md) |
| PILOT-030 | open | [PILOT-030](proofs/PILOT-030.md) |
| PILOT-031 | open | [PILOT-031](proofs/PILOT-031.md) |
| PILOT-032 | open | [PILOT-032](proofs/PILOT-032.md) |
| PILOT-040 | open | [PILOT-040](proofs/PILOT-040.md) |
| PILOT-041 | open | [PILOT-041](proofs/PILOT-041.md) |
| PILOT-042 | open | [PILOT-042](proofs/PILOT-042.md) |
| PILOT-043 | open | [PILOT-043](proofs/PILOT-043.md) |
| PILOT-044 | open | [PILOT-044](proofs/PILOT-044.md) |
| PILOT-050 | open | [PILOT-050](proofs/PILOT-050.md) |
| PILOT-051 | open | [PILOT-051](proofs/PILOT-051.md) |
| PILOT-052 | open | [PILOT-052](proofs/PILOT-052.md) |
| PILOT-053 | open | [PILOT-053](proofs/PILOT-053.md) |
