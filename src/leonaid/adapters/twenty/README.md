# Twenty CRM Gateway

Der Gateway implementiert den fachlichen Port aus
`leonaid.application.crm`. Application Services sprechen ausschließlich über
`CompanyData`, `PersonData`, kontrollierte Update-Typen und
`CrmSyncReceipt`. Twentys Wire-Felder und Transportdetails bleiben in
`gateway.py`.

## Bewusste Grenzen

- Companies und People bleiben in Twenty fachlich führend.
- LeonAid dupliziert keine CRM-Partei. Ein `CrmSyncReceipt` verbindet die ID
  des auslösenden LeonAid-Fachobjekts mit der Twenty-Record-ID, Status und
  Korrelation.
- Create und Update akzeptieren ausschließlich die expliziten semantischen
  Felder des jeweiligen Datentyps. Beliebige Twenty-Payloads sind nicht Teil
  des Ports.
- Ein partielles Personen-Update sendet nur tatsächlich gesetzte Bestandteile
  des zusammengesetzten Namens; ein Vorname-Update leert nicht stillschweigend
  den Nachnamen.
- Löschen, Merge und freie Metadata-Operationen gehören nicht zum Gateway.
- Browser und Akquisiteure sprechen ausschließlich mit der LeonAid-Core-API.
  Sie erhalten weder einen Twenty-Login noch einen Twenty-API-Key. Der
  eingeschränkte Integrations-Key wird nur serverseitig injiziert.

## Transportvertrag für Twenty 2.24.0

- REST Data API für Suche, Read, einzelnes Create und kontrolliertes Patch.
- GraphQL Data API für Create-Batches.
- maximal 60 Records je Batch; größere Eingaben werden in stabile 60er-Chunks
  geteilt.
- maximal 100 Requests pro Minute und Gateway-Prozess durch Sliding-Window-
  Throttling.
- konfigurierbarer Gesamt-/Connect-/Read-/Write-/Pool-Timeout.
- `429` wird nur nach einem begrenzten, gedeckelten `Retry-After` erneut
  versucht.
- REST-Pagination folgt ausschließlich `pageInfo.endCursor` über
  `starting_after`. Doppelte IDs, wiederholte Cursor, fehlende Folgecursor und
  eine unendliche Seitenfolge werden abgewiesen.

Twenty 2.24.0 benötigt für die People-Batch-Projektion das direkte Feld
`companyId`. Eine GraphQL-Auswahl der Relation `company { id }` versucht
zusätzlich das nicht freigegebene technische Company-Feld `deletedAt` zu lesen
und wird von der Least-Privilege-Rolle korrekt verweigert. Der Gateway fordert
deshalb keine weitergehenden Rechte an.

## Fehler- und Korrelationsvertrag

Jeder Request trägt `X-Request-ID` und `X-Correlation-ID`. Erfolgreiche Writes
geben `CrmSyncReceipt(status=SYNCED)` zurück und loggen ausschließlich
Operation, Korrelation, LeonAid-ID, Twenty-ID, Party-Typ und Status.

`CrmGatewayError` enthält einen stabilen Code, Retry-Hinweis, HTTP-Status,
Korrelation und – soweit bekannt – beide IDs. Response-Bodies, Nutzdaten und
API-Keys werden weder in Fehlertexte noch in Logs übernommen.

Transportfehler während Reads sind sicher wiederholbar. Bei Writes führt der
Gateway keinen blinden Retry aus, weil die Antwort nach erfolgreicher
Verarbeitung verloren gegangen sein könnte. Der Fehler trägt dann
`outcome_unknown=True`; der aufrufende Use Case muss anhand der fachlichen
Matching-/Idempotenzregeln reconciliieren. Bei mehreren 60er-Chunks enthält ein
Fehler zusätzlich die bereits bestätigten Receipts.

## Reale Prüfung

```sh
./leonaid test-twenty-gateway
```

Der Test startet eine leere, isolierte gepinnte Twenty-Instanz, provisioniert
die Least-Privilege-Rolle und prüft reale Batches, CRUD, Suche, Pagination,
Korrelation, Ausfall und Neustart. Es werden keine Mocks, HTTP-Fixtures,
direkten Datenbankzugriffe oder festen Sleeps verwendet.

`./leonaid test-policy` ergänzt diesen Transportnachweis um die
fachdatensatzgenauen Core-Policies gegen dasselbe echte Twenty und echtes
PostgreSQL. Twenty stellt dabei ausschließlich die bereits autorisierten
Firmen und Kontakte bereit; der Core leitet diese IDs bei jedem Request aus
Membership und Assignment ab.
