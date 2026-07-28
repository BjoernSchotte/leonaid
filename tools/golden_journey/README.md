# Krapfentaxi Golden Journey

`./leonaid test-golden-journey` beweist den vollständigen PoC-Weg mit echten
Diensten und ohne Mocks oder direkte fachliche Datenbankeingriffe.

## Voraussetzungen

```sh
./leonaid bootstrap
```

OrbStack oder Docker muss laufen. Der Test verwendet ein eigenes
Compose-Projekt, eigene Volumes und die Ports `18142` sowie `18502`. Er
verändert den normalen lokalen Entwicklungsstack nicht.

## Ablauf

Der Test:

1. baut API, Worker, Web, PWA und Public Web aus dem aktuellen Stand;
2. startet PostgreSQL, Twenty, RustFS und Mailpit auf leeren Volumes;
3. provisioniert das eingeschränkte Twenty-Schema und Golden Dataset v1;
4. führt die vollständige Journey nacheinander in Chromium, Firefox und
   WebKit aus;
5. prüft die Fachsummen und realen Artefakte nach der ersten Runde;
6. führt eine zweite Runde ohne Reset aus und schließt technische Duplikate
   aus;
7. löscht alle Testvolumes, startet noch einmal vollständig leer und
   wiederholt die erste Runde in allen drei Browsern;
8. vergleicht die normalisierten Fachergebnisse bytegenau.

Jede frische Twenty-Instanz erhält eine eigene kurzlebige Token-Datei. So
kann kein API-Key aus dem vorherigen, bereits gelöschten Workspace
wiederverwendet werden.

## Determinismus und Beweisartefakte

Innerhalb jedes Laufs müssen Browserdownload, RustFS-Objekt und
Mail-MIME-Anhang exakt denselben SHA-256 besitzen. Das vollständige
Beweisprotokoll enthält diese laufbezogenen Hashes.

Beim Vergleich zweier zeitlich nacheinander ausgeführter Golden Resets werden
die echten Ausstellungszeitpunkte und daraus abgeleiteten PDF-Hashes
normalisiert. Verglichen werden Fachsummen, Firmen, Rechnungsnummern und
PDF-Größen. Dadurch bleiben fachliche Abweichungen sichtbar, ohne einen
identischen Echtzeitstempel vorzutäuschen.

Erfolgreiche Läufe legen die privaten, nicht versionierten Nachweise unter
`.local/pilot/evidence/golden-journey/` ab:

- vollständige und normalisierte JSON-Protokolle;
- Admin- und Akquisiteur-Screenshots aller Browser und Runden;
- die im Browser heruntergeladenen Typst-PDFs;
- Screenshots des sichtbaren In-App-Browser-Smokes.

Die Verzeichnisse besitzen Modus `0700`, Dateien Modus `0600`. Screenshots,
PDFs und Rohdaten werden nie als öffentliche GitHub-Artefakte hochgeladen.
Bei einem Fehler entstehen zusätzlich sanitisierte Service-Diagnosen unter
`.artifacts/failures/poc122/`. Sobald ein Screenshot, PDF, Trace oder anderes
nicht sicher prüfbares Artefakt die öffentliche Grenze erreicht, verwirft der
CI-Wrapper den gesamten öffentlichen Artefaktsatz fail-closed.
