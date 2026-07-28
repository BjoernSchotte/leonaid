# Private Daten- und Evidence-Grenze

Status: technische Pilotbasis  
Gültig für: lokale Entwicklung, Staging, Produktion und GitHub Actions

Dieses Dokument beschreibt, welche Pilotdaten LeonAid verarbeiten darf und
welche Grenze zwischen privater Evidence und öffentlich teilbaren
Entwicklungsnachweisen gilt. Es ersetzt keine Datenschutz-, Steuer- oder
Rechtsfreigabe.

## 1. Datenklassen

| Klasse | Beispiele | Erlaubter Speicherort | GitHub-Artefakt |
| --- | --- | --- | --- |
| Öffentlich | Quellcode, Spezifikation, neutrale Status- und Summenwerte | Repository | ja |
| Synthetisch | Golden Data mit `.invalid`-Adressen und erfundenen Personen | Tests, kurzlebige Testsysteme | nur sanitisierte Textsummen |
| Privat | Excel-Import, echte Namen, Adressen, E-Mails, Telefone, Belege | `.local/pilot/intake/` oder externer privater Store | nein |
| Private Evidence | Screenshots, Playwright-Traces, PDFs, Freigaben | `.local/pilot/evidence/` oder externer privater Store | nein |
| Recovery | Datenbank-, Twenty-, RustFS- und Konfigurationsbackups | `.local/pilot/backups/` für lokale Übungen, produktiv ausschließlich off-host verschlüsselt | nein |
| Geheim | Tokens, Passwörter, Sessionwerte, Provider-Schlüssel | Secret Store beziehungsweise lokale `0600`-Env-Datei | nein |

Alle Pfade unter `.local/pilot/` sind explizit ignoriert. `./leonaid
pilot-evidence-init` legt Verzeichnisse als `0700` an. Private Dateien und
Evidence-Manifeste werden als `0600` geschrieben.

## 2. Minimales Evidence-Manifest

LeonAid kopiert private Quelldokumente nicht in öffentliche Nachweise. Das
lokale Manifest darf ausschließlich enthalten:

- SHA-256 der privaten Quelldatei;
- Counts, zunächst nur die Byteanzahl;
- kontrollierte Fehlerklassen ohne Payload;
- Zeitpunkte;
- eine opake Actor-ID;
- eine opake externe Evidence-ID.

Dateiname, Name, E-Mail, Anschrift, Telefon, Rechnungsinhalt, Dokumentbytes,
Token und freie Notizen sind im Manifest verboten. Beispiel:

```json
{
  "actor_id": "ACTOR-ADMIN-01",
  "counts": {
    "bytes": 12345
  },
  "error_classes": [],
  "external_evidence_id": "EVID-TAX-001",
  "sha256": "…",
  "timestamps": {
    "recorded_at": "2026-07-28T08:00:00Z"
  }
}
```

## 3. Öffentliche CI-Evidence

`tools/ci/sanitize_artifacts.py` ist die letzte Grenze vor jedem
GitHub-Upload:

- bekannte Secrets werden in UTF-8-Text, JSON, HTML und Textanteilen
  verschachtelter ZIPs redigiert;
- reale E-Mail-/Telefon- und private Canary-Signaturen blockieren den Upload;
- JSON mit Personen-, Adress-, Bank-, Steuer- oder Rechnungsfeldern sowie
  CSV-, HAR- und Trace-Rohdaten blockieren den Upload;
- Pfadtraversal, verschlüsselte ZIP-Einträge, ZIP-Bombs und zu tiefe
  Verschachtelung, ZIP-Symlinks und private ZIP-Metadaten blockieren den
  Upload;
- Screenshots, PDFs, Office-Dateien und sonstige nicht beweisbar prüfbare
  Binärdateien werden fail-closed abgewiesen;
- bei einer Blockade verwirft der CI-Wrapper den gesamten öffentlichen
  Artefaktsatz und veröffentlicht nur `SANITIZATION-FAILED.txt`.

Playwright-Traces, Screenshots und erzeugte Belege bleiben deshalb private
Evidence. Öffentliche CI-Artefakte enthalten ausschließlich sanitisierte
Textzusammenfassungen unter `.artifacts/ci/`.

## 4. Git- und Workflow-Grenze

`tools/pilot/boundary.py` prüft:

1. alle dokumentierten privaten Pfade werden ignoriert;
2. kein privater Pfad liegt im aktuellen Git-Index;
3. kein privater Pfad liegt in der erreichbaren Git-Historie;
4. GitHub Actions lädt nur die sanitisierte `.artifacts/ci/`-Grenze hoch.

Der Test verwendet zwei echte temporäre Git-Repositories. Eines enthält eine
absichtlich gestagte Intake-Datei, das andere eine bereits wieder gelöschte
private Evidence in der Historie. Beide müssen abgewiesen werden.

## 5. Testlogins

Golden-Testlogins verwenden ausschließlich synthetische `.invalid`-Adressen.
Sie dürfen lokal und in isoliertem Staging erzeugt werden. Produktion wird nie
mit Golden Data geseedet und erhält keine gemeinsam genutzten Testaccounts.
Reale Pilotpersonen erhalten individuelle Einladungen; Entzug und Audit
bleiben dadurch einer Person zuordenbar.

## 6. Operatorablauf

```text
./leonaid pilot-evidence-init
./leonaid test-pilot-data-boundary
```

Private Intake-Dateien werden anschließend manuell oder durch den autorisierten
Import-Agenten unter `.local/pilot/intake/` abgelegt. Nur opake Evidence-IDs
werden in öffentliche Entscheidungs- und Freigaberegister übernommen.
