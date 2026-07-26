# `@leonaid/api-client`

Host-neutraler TypeScript-Client für die LeonAid-Core-API.

- `openapi.json` wird direkt aus FastAPI erzeugt.
- `src/generated.ts` wird deterministisch aus diesem Vertrag generiert.
- `src/index.ts` ist der einzige Importpfad für Web, PWA, Public Web und eine
  spätere Tauri-App.

Beide generierten Dateien werden committed. Manuelle Änderungen sind
unzulässig; `tools/openapi/generate.py --check` erkennt Drift.

Der Generator unterstützt die im PoC verwendeten erforderlichen
JSON-Request-Bodies, erforderlichen Pfadparameter sowie typisierte skalare
Query-Parameter. Pfad- und Query-Werte werden URL-kodiert,
Content-Type-Header mit Aufrufoptionen zusammengeführt und nicht unterstützte
OpenAPI-Formen weiterhin explizit abgewiesen.

Seit POC-042 enthält der Vertrag außerdem Login-Anforderung und -Abschluss,
Fresh-Login-Status und -Abschluss, Logout sowie administrativen
Sitzungswiderruf. Das eigentliche Sitzungstoken bleibt ausschließlich im
`HttpOnly`-Cookie und ist deshalb kein Wert des TypeScript-Clients.

Seit POC-043 umfasst der Vertrag die serverseitig zugeschnittenen
Akquise-Endpunkte für Liste, Count, CSV-Export, Detail, Aktivitäten und
Dokumentmetadaten. Der Client übermittelt keine Actor-, Rollen- oder
Assignee-ID; die Core-Sitzung ist die einzige Identitätsquelle.

Seit POC-050 umfasst der Vertrag außerdem das Erstellen und Lesen neutraler
Charity-Aktionen sowie typisierte Änderungen an Ziel, Capabilities,
Begünstigten und Lifecycle. Dezimalwerte werden verlustfrei als kanonische
Strings übertragen. Schreibzugriffe bleiben serverseitig an eine frische
Sitzung und die zentrale Aktionsberechtigung gebunden.
