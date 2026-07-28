# PILOT-002 – Private Daten- und Evidence-Grenze

Task-ID: `PILOT-002`  
Nachweisdatum: 28. Juli 2026  
Status: technische Grenze bewiesen, formaler Abschluss blockiert

## Ergebnis

Die lokale, Git- und CI-seitige Grenze für private Pilotdaten ist
implementiert und reproduzierbar grün:

- [`DATA-HANDLING.md`](../DATA-HANDLING.md) klassifiziert öffentliche,
  synthetische, private, Recovery- und Secret-Daten.
- `./leonaid pilot-evidence-init` legt `.local/pilot/` und alle
  Unterverzeichnisse mit Modus `0700` an.
- `tools/pilot/evidence.py` erzeugt ausschließlich `0600`-Manifeste mit
  SHA-256, Counts, Fehlerklassen, Zeitpunkten, Actor-ID und externer
  Evidence-ID.
- `tools/pilot/boundary.py` blockiert private Pilotpfade im echten Git-Index,
  in der erreichbaren Git-Historie und in öffentlichen GitHub-Uploadpfaden.
  Alle Workflows und Upload-Actions werden fail-closed geprüft. Erlaubt sind
  ausschließlich sanitisierte CI-Texte unter `.artifacts/ci/` und
  CycloneDX-SBOMs unter `.artifacts/sbom/`.
- Reale Negativtests lehnen Uploads von produktiven Backups, privater
  Evidence, Testlogin-Dateien, Failure-Verzeichnissen und unbekannten
  Upload-Actions ab.
- Golden-Seed und Testlogin-Generator akzeptieren ausschließlich
  `LEONAID_ENV=local` oder `LEONAID_ENV=test`. `production` und unbekannte
  Umgebungen werden vor jedem Daten- oder Dateizugriff abgewiesen.
- Der CI-Sanitizer redigiert bekannte Secrets in sicheren Textformaten und
  lehnt PII, nicht freigegebene Binärformate, Screenshots, PDFs,
  Pfadtraversal, verschlüsselte Archive und verschachtelte private
  Playwright-Traces fail-closed ab.
- Golden-Journey-Screenshots und -PDFs werden nicht mehr als
  GitHub-Artefakte veröffentlicht, sondern ausschließlich unter
  `.local/pilot/evidence/` abgelegt.

## Automatischer Grenznachweis

```sh
./leonaid test-pilot-data-boundary
```

Ergebnis:

```text
pilot-evidence: OK: private Pfade bereit: /boundary/.local/pilot
pilot-data-boundary-test: OK: 0700/0600, minimales Manifest,
echter Git-Index, Git-Historie und alle Workflow-Uploads bewiesen
ci-artifact-sanitize-test: OK: Secrets werden redigiert; PII,
Screenshots, PDFs und verschachtelte Traces werden fail-closed abgewiesen
test-login-handoff: BLOCKED: Testlogins sind in production verboten
pilot-data-boundary-test: OK: Produktions-Testlogin blockiert und keine
Datei erzeugt
pilot-data-boundary-test: OK: Host-, Docker-, Git- und Artefaktgrenze bewiesen
```

Der Test verwendet:

1. ein echtes Host-Bind-Mount für die von Docker erzeugten Dateirechte;
2. zwei echte temporäre Git-Repositories für Index und Historie;
3. synthetische PII-/Secret-Canaries in Text, JSON, HTML, PNG, PDF,
   verschachteltem ZIP und Playwright-Trace;
4. echte Workflow-Dateien mit erlaubten und verbotenen Uploadpfaden;
5. einen realen Docker-Prozess mit `LEONAID_ENV=production`, der keine
   Testlogin-Datei erzeugen darf;
6. ausschließlich digest-gepinnte Python- und Playwright-Images.

Der Golden-Data-Integrationstest beweist dieselbe Grenze zusätzlich vor dem
Datenbankzugriff:

```sh
/bin/sh tools/seed/test.sh /Users/bjoern/code/leonaid
```

Ergebnis:

```text
golden-seed-core: ERROR: Golden Data sind ausschließlich in local/test
erlaubt; Produktion und unbekannte Umgebungen werden abgewiesen
seed-test: OK: Sicherheit, Idempotenz, Mutation und exakter Reset bewiesen
```

Der Test lief im isolierten Compose-Projekt `leonaid-poc012-test`. Nach seinem
Cleanup waren null Container, Netze und Volumes mit diesem Projektlabel
vorhanden.

## Zusätzliche Verträge

```text
ci-workflow-contract: OK: neun getrennte Jobs und Failure-Artefakte
ci-workflow-contract-test: OK: neun Jobs und fehlender Upload werden geprüft
ci-lint-types: OK
ci-security: OK: Policies, Secrets und kritische Abhängigkeiten/Images
```

Ruff, Formatierung, striktes MyPy, OpenAPI-/Client-Grenze, sämtliche
TypeScript-/Astro-Prüfungen und Prettier sind grün.

Die umgestellte Evidence-Ablage wurde zusätzlich durch die vollständige
Golden Journey bewiesen:

```text
golden-journey: OK: vollständiger Persona-Weg in Chromium, Firefox und WebKit,
golden-journey:     zwei zusätzliche Fachrunden ohne technische Duplikate
golden-journey:     sowie deterministische Wiederholung aus Golden Reset bewiesen
```

Alle neun Browserläufe waren grün. Die privaten Ergebnisdateien besitzen
Modus `0600`, ihre drei Verzeichnisebenen Modus `0700`. Nach dem Test waren
null Container, Netze und Volumes des Projekts `leonaid-poc122-test`
vorhanden. Ein zusätzlicher sichtbarer In-App-Browser-Smoke navigierte als
synthetischer Akquisiteur von „Meine Sponsoren“ zur vorausgefüllten
Musterwerk-Bestellung; die Seite blieb für die gemeinsame Prüfung geöffnet.

## Formale Taskgrenze

Der Task bleibt formal offen, weil seine Abhängigkeit `PILOT-001` noch
externe Träger-, Steuer-, Datenschutz- und Betriebsentscheidungen enthält.
Alle Akzeptanzkriterien von `PILOT-002` sind technisch bewiesen: Der
Workflow-Vertrag verhindert entsprechende GitHub-Uploads und die
Produktionssperren verhindern Golden- sowie Testlogin-Erzeugung vor jedem
Systemzugriff. Der spätere Produktionsschnitt aus `PILOT-040` muss diese
Verträge beibehalten und wird sie erneut als Deployment-Gate prüfen. Der
formale Taskabschluss wird wegen der offenen Abhängigkeit nicht vorgezogen.
