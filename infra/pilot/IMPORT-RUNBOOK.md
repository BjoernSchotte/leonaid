# Pilot-Import

Der historische Kontaktimport ist eine einmalige, Dry-Run-first Migration.
Die fachliche Excel-Datei bestimmt das Mapping; LeonAid stellt dafür keinen
beliebigen Endnutzer-Importer bereit. Original, personenbezogene Reports,
Entscheidungen und Freigaben bleiben ausschließlich unter `.local/pilot/`
oder in einem gleichwertig geschützten privaten Store.

## 1. Intake

```sh
./leonaid pilot-evidence-init
install -m 600 /geschuetzt/original.xlsx \
  .local/pilot/intake/historic-contacts.xlsx
```

Vor jeder Analyse wird
`.local/pilot/manifests/intake.json` mit `schemaVersion: 1` angelegt:

```json
{
  "schemaVersion": 1,
  "sourceSha256": "<sha256>",
  "authorizationReference": "AUTH-PILOT-001",
  "purpose": "historic-sponsor-contact-import",
  "receivedAt": "2026-07-29T20:00:00Z",
  "responsibleActorId": "ACTOR-DATA-01",
  "externalEvidenceId": "EVID-IMPORT-001"
}
```

IDs sind opak. Namen, E-Mail-Adressen und sonstige Quelldaten gehören nicht
in das Manifest.

## 2. Mapping durch den Coding-Agent

Der Coding-Agent analysiert die tatsächlichen Header, Blätter, Formate,
Formeln, Pflichtfelder, leeren Spalten, Dubletten und Zeichensätze. Er erzeugt:

- ein versioniertes, personenbezugsfreies Mapping;
- eine synthetische Arbeitsmappe mit derselben Struktur;
- beschädigte Varianten für fehlende Header, Formeln, doppelte Schlüssel und
  ungültige Werte;
- eine stabile Source-ID-Strategie. Zeilennummern und Reihenfolge sind keine
  IDs.

Unsichere oder ähnliche Matches bleiben Konflikte. Der Agent darf sie nicht
automatisch zusammenführen.

## 3. Dry Run

Der Zielstack muss bereits aus dem freigegebenen Manifest laufen. Pfade werden
repository-relativ angegeben, damit ausschließlich die private
`.local/pilot/`-Ablage in den Operatorcontainer eingebunden wird:

```sh
./leonaid pilot-import dry-run \
  .local/pilot/intake/historic-contacts.xlsx \
  --env-file /etc/leonaid/staging.env \
  --batch-id IMPORT-PILOT-001 \
  --target-environment staging-club-111 \
  --manifest .local/pilot/manifests/intake.json \
  --mapping infra/twenty/import-mapping.json \
  --sheet Kontakte \
  --report .local/pilot/evidence/import-dry-run.json \
  --summary .local/pilot/evidence/import-summary.json
```

Der private Report enthält zeilenbezogene Status, stabile Fehlercodes und
Kandidaten. Die sanitizte Summe enthält keine Zeilen oder Personenwerte.
Zwei Dry Runs gegen denselben Zielstand müssen bytegleich sein.

## 4. Konfliktauflösung

Konflikte werden ausschließlich in
`.local/pilot/manifests/resolutions.json` aufgelöst:

```json
{
  "schemaVersion": 1,
  "batchId": "IMPORT-PILOT-001",
  "decisions": [
    {
      "sourceId": "00000000-0000-4000-8000-000000000001",
      "decision": "use-existing",
      "targetTwentyId": "00000000-0000-4000-8000-000000000002",
      "decidedBy": "ACTOR-REVIEWER-01",
      "decidedAt": "2026-07-29T20:10:00Z"
    }
  ]
}
```

`create-new` ist ebenfalls möglich und besitzt keine `targetTwentyId`.
`use-existing` akzeptiert nur eine ID, die der Dry Run als Kandidat gemeldet
hat.

Danach wird der Dry Run mit `--resolutions` wiederholt. Sein
`planFingerprint` bindet Quelldatei, Mapping, Resolution, Zielumgebung,
Blatt und den vollständigen aktuellen Twenty-Plan.

## 5. Recovery Point und Vier-Augen-Freigabe

Vor Apply existiert ein vollständiger Cross-System-Recovery-Point aus Core,
Twenty, Twenty-Dateien und RustFS. Das private Freigabeobjekt
`.local/pilot/manifests/approval.json` bindet:

- Batch und Zielumgebung;
- Plan-, Source-, Mapping- und Resolution-Fingerprint;
- SHA-256 des bytegenau geprüften Backup-Manifests;
- opake Recovery-Point-ID;
- zwei unterschiedliche Freigabe-IDs und einen Zeitzonen-Zeitpunkt.

Eine Änderung an nur einem gebundenen Byte blockiert Apply.

## 6. Apply und Verify

```sh
./leonaid pilot-import apply \
  .local/pilot/intake/historic-contacts.xlsx \
  --env-file /etc/leonaid/staging.env \
  --batch-id IMPORT-PILOT-001 \
  --target-environment staging-club-111 \
  --manifest .local/pilot/manifests/intake.json \
  --mapping infra/twenty/import-mapping.json \
  --resolutions .local/pilot/manifests/resolutions.json \
  --sheet Kontakte \
  --approval .local/pilot/manifests/approval.json \
  --backup-manifest .local/pilot/backups/manifest.json \
  --report .local/pilot/evidence/import-apply.json

./leonaid pilot-import verify \
  .local/pilot/intake/historic-contacts.xlsx \
  --env-file /etc/leonaid/staging.env \
  --batch-id IMPORT-PILOT-001 \
  --target-environment staging-club-111 \
  --manifest .local/pilot/manifests/intake.json \
  --mapping infra/twenty/import-mapping.json \
  --resolutions .local/pilot/manifests/resolutions.json \
  --sheet Kontakte \
  --backup-manifest .local/pilot/backups/manifest.json \
  --report .local/pilot/evidence/import-verify.json
```

Apply führt vor dem ersten Write erneut den aktuellen Dry Run aus und prüft
die Freigabe. Ein exklusiver Batch-Lock verhindert paralleles Apply. Verify
ist nur grün, wenn keine neuen, zu ändernden oder ungeklärten Datensätze
verbleiben.

Bei einem Fehler werden keine Daten manuell korrigiert. Operator und
Produktverantwortlicher entscheiden anhand des privaten Reports zwischen
Stop, kontrolliertem Retry oder vollständigem Restore.
