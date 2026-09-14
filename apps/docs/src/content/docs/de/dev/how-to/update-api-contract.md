---
title: Den API-Vertrag aktualisieren
description: FastAPI, kanonisches OpenAPI und den TypeScript-Client in einem reproduzierbaren Ablauf gemeinsam ändern.
docId: DOC-P032
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

1. Ändere Route und Modelle im FastAPI-Core samt passendem Domain- oder
   Vertragstest.
2. Führe `./leonaid generate-api-client` aus. Bearbeite weder
   `packages/api-client/openapi.json` noch `packages/api-client/src/generated.ts`
   von Hand.
3. Prüfe den Diff beider erzeugter Dateien. Feldnamen, Pflichtfelder,
   Statuscodes, Sicherheit und Fehlerformen müssen der beabsichtigten
   Core-Änderung entsprechen.
4. Aktualisiere Verbraucher und die kuratierten DE/EN-Erklärungen. Die
   Docs-API-Referenz wird beim Docs-Gate aus genau diesem JSON erzeugt.
5. Führe `tools/openapi/test.sh` sowie den betroffenen Feature-Test aus. Der
   OpenAPI-Test erzeugt Vertrag und Client erneut, vergleicht bytegenau,
   typecheckt und prüft den realen API-Client.

Eine brechende Änderung benötigt die exakte, begründete Freigabe im
versionierten Breaking-Approval-Vertrag. Ein fehlender oder vom Core
abweichender Vertrag blockiert Build und Docs-Referenz.
