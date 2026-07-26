# Twenty-Vertrag für LeonAid

## Verbindlicher Stand

LeonAid provisioniert ausschließlich die in
[`schema.json`](./schema.json) deklarierte Teilmenge der Twenty-API. Geprüft ist:

- Twenty `2.24.0`, Upstream-Tag `twenty/v2.24.0`
  (`b91c2a6457578ea4a017242fc1fe8efd1f463eb0`)
- Container-Digest
  `sha256:333b6e3d06904293b3bdad9f4a5eb1489fa8719d886b3e6811aff1d0b85b860c`
- GraphQL Metadata API unter `/metadata`
- REST Metadata API unter `/rest/metadata`
- generierte REST Data API unter `/rest/<objectPlural>`

Ein Upgrade von Twenty ist eine bewusste Vertragsänderung. Vor dem Merge müssen
der Pin, das Manifest und `tools/twenty/test.sh` gemeinsam aktualisiert und
gegen eine leere Instanz bewiesen werden.

Der produktive Data-API-Vertrag ist separat im
[`Twenty CRM Gateway`](../../src/leonaid/adapters/twenty/README.md)
dokumentiert und wird durch `./leonaid test-twenty-gateway` real geprüft.

## Einmaliger Kontaktimport

Twenty 2.24.0 kann über seine Oberfläche CSV-, XLSX- und XLS-Dateien
importieren, allerdings jeweils nur für ein Objekt. LeonAid verwendet für den
PoC bewusst den eigenen API-Importpfad, weil er die fachlichen
Primärschlüssel, einen prüfbaren Dry Run und einen gemeinsamen zeilenbezogenen
Report für Companies und People benötigt. Der Weg bleibt auf Twentys
unterstützter Data API und greift nicht auf interne Tabellen zu.

Die versionierte
[Golden-Arbeitsmappe](../../tests/fixtures/golden/v1/outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx)
und [`import-mapping.json`](./import-mapping.json) bilden die Vorlage für eine
echte Bestandsdatei. Die erste Zeile muss exakt diese Spalten enthalten:

```text
source_id, record_type, company_name, given_name, family_name, email,
street_line_1, postal_code, city, country
```

- `source_id` ist pro Zeile eine stabile UUIDv4 und macht Berichte über
  Wiederholungen vergleichbar.
- `record_type` ist `COMPANY` oder `PERSON`.
- Firmen benötigen `company_name`; Personen benötigen `given_name` und
  `family_name`.
- Leere Zellen löschen keine vorhandenen CRM-Werte.
- Firmennamen werden Unicode-, Groß-/Kleinschreibungs-, Whitespace- und
  Interpunktions-unabhängig verglichen. Ohne Firma gilt Vor- plus Nachname als
  Match-Schlüssel.
- Kein Treffer wird als `new`, genau ein Treffer als `update` oder
  `unchanged`, mehrere Treffer als `conflict` und ungültige Zeilen als
  `rejected` berichtet.
- Konflikte und verworfene Zeilen werden niemals automatisch geschrieben.

Die Arbeitsdatei wird in das Repository oder in das ignorierte Verzeichnis
`.local/` gelegt. Vor dem ersten Lauf:

```sh
./leonaid provision-twenty
./leonaid import-crm dry-run .local/kontakte.xlsx \
  --report .local/import-dry-run.json
```

Der JSON-Report besitzt Dateimodus `0600` und nennt für jede Excel-/CSV-Zeile
Status, Begründung, Trefferkandidaten und die betroffene Twenty-ID. Erst nach
fachlicher Prüfung wird derselbe Stand angewendet:

```sh
./leonaid import-crm apply .local/kontakte.xlsx \
  --report .local/import-apply.json
```

Ein erneuter Dry Run muss nur noch `unchanged`, weiterhin bewusst ungelöste
`conflict`-Fälle oder `rejected`-Zeilen zeigen. Vorhandene Firmen werden nicht
umbenannt; nichtleere Adressfelder und bei Personen E-Mail/Firmenrelation
werden kontrolliert ergänzt oder aktualisiert.

Referenzen zum nativen Twenty-Import:

- [Import overview](https://docs.twenty.com/user-guide/data-migration/overview)
- [Supported file formats](https://docs.twenty.com/user-guide/data-migration/capabilities/file-formats)
- [Update existing records](https://docs.twenty.com/user-guide/data-migration/how-tos/update-existing-records-via-import)

## Fachliche Grenze

Twenty bleibt führend für Companies, People, Kontaktwege und allgemeine
CRM-Aktivitäten. LeonAid Core bleibt führend für Charity-Aktionen,
aktionsbezogene Rollen, Zuweisungshistorie, Bestellungen und Rechnungen.

Für den Charity-Admin-Spike werden zwei klar als Lesemodell beschriebene Custom
Objects gespiegelt:

- `charityAction`: Zeitraum, Lifecycle, Ziel und Archiv-Slug
- `acquisitionAssignment`: Akquisiteur, Status, Wiedervorlage sowie Relationen
  zu Aktion und wahlweise Company oder Person

Die stabilen `leonaidId`-Felder verbinden beide Systeme. Änderungen in Twenty
dürfen die fachlichen Invarianten des Core nicht umgehen.

## Deklarativ verwaltete Capabilities

Das Manifest beschreibt und der Provisioner prüft:

- zwei Custom Objects mit Text-, Zahl-, Datum-/Zeit- und Select-Feldern,
- drei `MANY_TO_ONE`-Relationen und die von Twenty erzeugten Gegenfelder,
- zwei tabellarische Charity-Admin-Views mit expliziten sichtbaren Spalten,
- die Benutzerrolle `LeonAid Charity-Admin`,
- die technische Rolle `LeonAid Integration`,
- genau einen dieser technischen Rolle zugeordneten API-Key.

Die Provisionierung nutzt nur unterstützte Metadata-Mutationen:

- `createOneObject`
- `createOneField`
- `createView`, `createViewField`, `updateViewField`
- `createOneRole`
- `upsertObjectPermissions`, `upsertFieldPermissions`,
  `upsertPermissionFlags`
- `createApiKey`, `generateApiKeyToken`

Interne Twenty-Tabellen werden weder gelesen noch verändert.

## Least-Privilege-Key

`LeonAid Integration` darf nur Companies, People, Charity-Aktionen und
Akquise-Zuweisungen lesen und kontrolliert aktualisieren. Die Rolle besitzt:

- keine globalen Lese-, Schreib- oder Löschrechte,
- keine Settings-, Rollen-, Datenmodell-, Workflow-, Import-, Export- oder
  Tool-Flags,
- keine Soft-Delete- oder Destroy-Rechte,
- explizite Feld-Whitelists.

Twenty modelliert Feldrechte als Einschränkungen. Relation-Feldrechte müssen
auf beiden Seiten identisch sein; deshalb sind die benötigten Gegenrelationen
ebenfalls freigegeben. `position`, `createdBy` und `updatedBy` benötigen beim
Record-Create Schreibrecht, obwohl Twenty ihre Werte serverseitig setzt. Diese
technischen Pflichtrechte sind im Manifest sichtbar.

Der Contracttest beweist mit dem erzeugten Key:

1. Company-Create und Reads der beiden LeonAid-Objekte funktionieren.
2. Nicht freigegebene Company-Felder werden nicht ausgeliefert.
3. Opportunities werden mit `PERMISSION_DENIED` verweigert.
4. Administrative Rollen-Metadaten werden verweigert.

Der Token wird nur einmal in der ignorierten Datei
`.local/twenty/integration.env` mit Dateimodus `0600` abgelegt. Er wird nie in
Logs, Snapshots oder Git geschrieben.

## Betrieb und Drift

```sh
./leonaid provision-twenty
```

Der Befehl:

1. startet die gepinnte Twenty-Instanz,
2. legt fehlende deklarierte Objekte an,
3. reconciliert die technisch erforderlichen Rechte,
4. bricht bei abweichenden verwalteten Objekt-, Feld-, Relations-, View-,
   Rollen- oder API-Key-Eigenschaften mit einem exakten Pfad ab,
5. schreibt einen geheimnisfreien kanonischen Snapshot nach
   `.local/twenty/schema-snapshot.json`.

Bestehender Drift wird nicht stillschweigend durch Umbenennen oder Löschen
kaschiert. Eine gewollte Änderung braucht ein angepasstes Manifest, eine
bewusste Migration und den vollständigen Contracttest.

## Verifizierte Grenzen von Twenty 2.24.0

- Custom Fields können im Produkt nicht als fachlich verpflichtend markiert
  werden. Pflichtfeldregeln bleiben deshalb im LeonAid Core.
- Die hier genutzte Relations-API unterstützt `MANY_TO_ONE` und
  `ONE_TO_MANY`. Für den PoC wird kein Many-to-many-Lab-Feature verwendet.
- Objekt- und Feldrechte ersetzen keine aktionsbezogene Row-Level-
  Autorisierung. Akquisiteure greifen ausschließlich über LeonAid Core zu.
- Charity-Admins mit direktem Twenty-Zugriff sehen innerhalb der freigegebenen
  Objekte alle Records. Die Zuordnung zu selbst verwalteten Aktionen wird
  weiterhin serverseitig im Core geprüft.
- Die API ist auf 100 Requests pro Minute und Batches von höchstens 60 Records
  ausgelegt. POC-031 muss Pagination, Backoff und Batching innerhalb dieser
  Grenzen umsetzen.
- Workflows, Webhooks und Twenty-Mailversand gehören nicht zu POC-030.

Referenzen:

- [Twenty APIs](https://docs.twenty.com/developers/extend/api)
- [Twenty Custom Objects](https://docs.twenty.com/developers/contribute/capabilities/backend-development/custom-objects)
- [Twenty v2.24.0 source](https://github.com/twentyhq/twenty/tree/twenty/v2.24.0)

## Reale Prüfung

```sh
./tools/twenty/test.sh
./leonaid test-twenty-gateway
./leonaid test-crm-import
```

Der Schematest startet Twenty aus leeren Volumes, provisioniert zweimal, vergleicht
kanonische Snapshots bytegenau, prüft den echten Integrations-Key und verändert
anschließend ein Feld über `updateOneField`. `check` muss den konkreten
Feldpfad samt Ist-Wert melden.

Der Importtest startet ein eigenes leeres Twenty, provisioniert und befüllt es
über die öffentlichen APIs, führt Dry Run, initialen Import, gezieltes Update
und identische Wiederholung aus und verifiziert Reports sowie Records erneut
über den produktiven CRM-Gateway.
