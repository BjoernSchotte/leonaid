# `@leonaid/api-client`

Host-neutraler TypeScript-Client für die LeonAid-Core-API.

- `openapi.json` wird direkt aus FastAPI erzeugt.
- `src/generated.ts` wird deterministisch aus diesem Vertrag generiert.
- `src/index.ts` ist der einzige Importpfad für Web, PWA, Public Web und eine
  spätere Tauri-App.

Beide generierten Dateien werden committed. Manuelle Änderungen sind
unzulässig; `tools/openapi/generate.py --check` erkennt Drift.

Der Generator unterstützt die im PoC verwendeten erforderlichen
JSON-Request-Bodies und erforderlichen Pfadparameter. Pfadwerte werden
URL-kodiert, Content-Type-Header mit Aufrufoptionen zusammengeführt und nicht
unterstützte OpenAPI-Formen weiterhin explizit abgewiesen.
